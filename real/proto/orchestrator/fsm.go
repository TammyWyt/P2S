// Package orchestrator runs one P2S slot end to end (single proposer).
//
// B1 phase: PHTs enter the expool; the proposer ORDERS them using only
// B1-visible fields (greedy by priority fee, content-blind) and charges the
// reservation fee. The order is frozen here.
//
// B2 phase: senders reveal MTs; each is verified against its PHT commitment;
// the revealed transactions are substituted into the B1 order and executed on
// real EVM state via execdriver (evm t8n). Execution order == B1 order, never a
// content-optimized order -- this is the structural basis of content-ordering
// independence (validated by TestOrderingPreservation and the M5 MEV result).
//
// Ground truth for the lifecycle: scripts/simulation/simulator.py:716-815.
package orchestrator

import (
	"fmt"
	"math/big"
	"sort"

	"github.com/ethereum/go-ethereum/common"
	"github.com/p2s/proto/commit"
	"github.com/p2s/proto/execdriver"
	"github.com/p2s/proto/expool"
	"github.com/p2s/proto/feeacct"
	"github.com/p2s/proto/wire"
)

// Submission is a user's intent: the signed transaction (revealed at B2) whose
// intent fields are sealed in a PHT at B1.
type Submission struct {
	From      *execdriver.Account
	To        common.Address
	Value     *big.Int
	Data      []byte
	Gas       uint64
	GasFeeCap *big.Int
	GasTipCap *big.Int
	Nonce     uint64
}

// SlotResult reports the committed B1 order, the floor-model reservation-fee
// accounting, and the real-EVM execution of B2. The reservation fee is a floor
// on the base fee (max(F_res, F_base)), not an additive surcharge: a revealed
// transaction that consumes at least phi*gasLimit pays only the ordinary base
// fee (its F_res is fully credited); a PHT that never reveals forfeits F_res.
type SlotResult struct {
	Order               []common.Hash      // PHT hashes in committed (B1) order
	FResReserved        *big.Int           // reservation floor prepaid at B1, summed over all PHTs (wei)
	FResForfeited       *big.Int           // F_res forfeited by PHTs that never revealed (wei)
	ReservationCredited *big.Int           // F_res absorbed into the base fee of executed txs, min(F_res,F_base) (wei)
	TotalBaseBurned     *big.Int           // base burned over B1+B2: sum of max(F_res,F_base) executed + F_res unrevealed (wei)
	Exec                *execdriver.Result
}

// RunSlot executes one P2S slot: derive PHTs/MTs from submissions, order
// content-blind at B1, verify reveals, and execute in B1 order at B2.
func RunSlot(subs []*Submission, alloc map[common.Address]execdriver.AllocAccount, env execdriver.Env, phiBps uint64) (*SlotResult, error) {
	pool := expool.New()

	type bundle struct {
		sub *Submission
		pht *wire.PHT
		mt  *wire.MT
	}
	bundles := make(map[common.Hash]*bundle)

	// --- B1: build PHTs (seal intent), admit to expool ---
	for _, s := range subs {
		salt := commit.RandSalt()
		c := commit.Commit(s.To, s.Value, s.Data, s.Gas, salt)
		pht := &wire.PHT{
			Sender:     s.From.Addr,
			Nonce:      s.Nonce,
			GasFeeCap:  s.GasFeeCap,
			GasTipCap:  s.GasTipCap,
			GasLimit:   s.Gas,
			Commitment: c,
		}
		h, ok := pool.AddPHT(pht)
		if !ok {
			continue // duplicate (sender,nonce) — dropped at B1
		}
		mt := &wire.MT{Ref: h, Recipient: s.To, Value: s.Value, CallData: s.Data, GasLimit: s.Gas, Salt: salt}
		pool.AddMT(mt)
		bundles[h] = &bundle{sub: s, pht: pht, mt: mt}
	}

	// content-blind ordering: greedy by priority fee (GasTipCap), then hash for
	// determinism. Uses ONLY B1-visible fields -- never recipient/value/calldata.
	order := pool.PendingPHTs()
	sort.Slice(order, func(i, j int) bool {
		ti, tj := bundles[order[i]].pht.GasTipCap, bundles[order[j]].pht.GasTipCap
		if c := ti.Cmp(tj); c != 0 {
			return c > 0 // higher tip first
		}
		return order[i].Hex() > order[j].Hex()
	})

	// --- B1: reservation floor F_res prepaid per PHT (phi*gasLimit*baseFee) ---
	fResByHash := make(map[common.Hash]*big.Int, len(order))
	fResReserved := new(big.Int)
	for _, h := range order {
		r := feeacct.ReservationFee(phiBps, bundles[h].pht.GasLimit, env.BaseFee)
		fResByHash[h] = r
		fResReserved.Add(fResReserved, r)
	}

	// --- B2: verify reveals, substitute MTs into the B1 order, execute ---
	calls := make([]*execdriver.Call, 0, len(order))
	revealed := make([]common.Hash, 0, len(order)) // revealed PHTs, in call order
	for _, h := range order {
		b := bundles[h]
		mt, ok := pool.MT(h)
		if !ok {
			continue // unrevealed PHT: F_res forfeited (accounted below), no execution
		}
		if !commit.VerifyReveal(b.pht.Commitment, b.pht.GasLimit, mt.Recipient, mt.Value, mt.CallData, mt.GasLimit, mt.Salt) {
			return nil, fmt.Errorf("MT reveal failed verification for %s", h.Hex())
		}
		to := mt.Recipient
		calls = append(calls, &execdriver.Call{
			From:     b.sub.From,
			To:       &to,
			Value:    mt.Value,
			Data:     mt.CallData,
			Gas:      b.pht.GasLimit,
			GasPrice: b.pht.GasFeeCap,
			Nonce:    b.pht.Nonce,
		})
		revealed = append(revealed, h)
	}

	exec, err := execdriver.Run(alloc, env, calls)
	if err != nil {
		return nil, err
	}

	// --- Floor reconciliation: total base burned = max(F_res, F_base) per tx ---
	// (F_base = gasUsed*baseFee). Unrevealed PHTs forfeit the full F_res; an
	// executed tx pays the larger of F_res and F_base, so the smaller of the two
	// is credited (refunded) against the reservation already prepaid in B1.
	revealedSet := make(map[common.Hash]bool, len(revealed))
	for _, h := range revealed {
		revealedSet[h] = true
	}
	fResForfeited := new(big.Int)
	for _, h := range order {
		if !revealedSet[h] {
			fResForfeited.Add(fResForfeited, fResByHash[h])
		}
	}
	reservationCredited := new(big.Int)
	totalBaseBurned := new(big.Int).Set(fResForfeited) // unrevealed reservations are burned
	for j, h := range revealed {
		fRes := fResByHash[h]
		fBase := new(big.Int)
		if j < len(exec.Receipts) {
			fBase.Mul(env.BaseFee, new(big.Int).SetUint64(uint64(exec.Receipts[j].GasUsed)))
		}
		if fRes.Cmp(fBase) >= 0 { // floor binds: pay F_res, credit the unused base
			totalBaseBurned.Add(totalBaseBurned, fRes)
			reservationCredited.Add(reservationCredited, fBase)
		} else { // ordinary fee: pay F_base, credit the full reservation
			totalBaseBurned.Add(totalBaseBurned, fBase)
			reservationCredited.Add(reservationCredited, fRes)
		}
	}

	return &SlotResult{
		Order:               order,
		FResReserved:        fResReserved,
		FResForfeited:       fResForfeited,
		ReservationCredited: reservationCredited,
		TotalBaseBurned:     totalBaseBurned,
		Exec:                exec,
	}, nil
}
