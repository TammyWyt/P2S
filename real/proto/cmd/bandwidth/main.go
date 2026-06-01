// Command bandwidth measures the REAL wire-byte overhead of P2S vs a baseline
// single-phase block, using actual RLP encoding of the protocol messages.
//
// P2S sends, per transaction: a PHT at B1 (visible header + 32-byte commitment,
// NO intent fields) and an MT at B2 (the revealed transaction + 32-byte salt).
// The MT carries the same content a baseline tx would, so the marginal overhead
// is the PHT plus the salt. Per slot, the set-union agreement adds, for each of
// N proposers, a broadcast of the K seen MT-refs (32 bytes each).
//
// All sizes below are measured by rlp.EncodeToBytes on the real structs, not
// estimated.
package main

import (
	"encoding/json"
	"fmt"
	"math/big"
	"os"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/rlp"
	"github.com/p2s/proto/wire"
)

func size(v any) int {
	b, err := rlp.EncodeToBytes(v)
	if err != nil {
		panic(err)
	}
	return len(b)
}

func main() {
	key, _ := crypto.HexToECDSA("ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
	to := common.HexToAddress("0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc")

	// representative Uniswap V2 swap calldata: selector + ~5 words + a 2-hop path
	calldata := make([]byte, 4+32*8)
	for i := range calldata {
		calldata[i] = byte(i)
	}

	// baseline: a real signed Ethereum tx (what PoS puts on the wire once)
	signer := types.LatestSignerForChainID(big.NewInt(1))
	tx, _ := types.SignNewTx(key, signer, &types.LegacyTx{
		Nonce: 7, GasPrice: big.NewInt(20e9), Gas: 200000, To: &to,
		Value: big.NewInt(1e18), Data: calldata,
	})
	baseBytes := size(tx)

	salt := [32]byte{}
	pht := &wire.PHT{Sender: crypto.PubkeyToAddress(key.PublicKey), Nonce: 7,
		GasFeeCap: big.NewInt(20e9), GasTipCap: big.NewInt(2e9), GasLimit: 200000,
		Commitment: crypto.Keccak256Hash(calldata), Timestamp: 1_700_000_000}
	mt := &wire.MT{Ref: pht.Hash(), Recipient: to, Value: big.NewInt(1e18),
		CallData: calldata, GasLimit: 200000, Salt: salt, Timestamp: 1_700_000_000}

	phtBytes := size(pht)
	mtBytes := size(mt)
	refBytes := size(pht.Hash()) // one MT-ref in an agreement broadcast

	fmt.Println("== per-message RLP sizes (bytes) ==")
	fmt.Printf("  baseline signed tx : %d\n", baseBytes)
	fmt.Printf("  PHT (B1)           : %d\n", phtBytes)
	fmt.Printf("  MT  (B2)           : %d\n", mtBytes)
	fmt.Printf("  MT-ref (agreement) : %d\n", refBytes)

	// per-tx overhead = (PHT + MT) - baseline; MT ~ baseline content, PHT is extra
	perTxOverhead := (phtBytes + mtBytes) - baseBytes
	fmt.Println("\n== per-transaction overhead ==")
	fmt.Printf("  P2S per tx (PHT+MT): %d   baseline: %d   overhead: %+d bytes (%.1f%%)\n",
		phtBytes+mtBytes, baseBytes, perTxOverhead, 100*float64(perTxOverhead)/float64(baseBytes))

	type row struct {
		K, N                    int
		TxOverheadB, AgreeB, TotalB int
	}
	out := struct {
		BaselineTxB, PHTB, MTB, RefB, PerTxOverheadB int
		Rows                                         []row
	}{baseBytes, phtBytes, mtBytes, refBytes, perTxOverhead, nil}

	fmt.Println("\n== per-slot overhead vs block size K and proposer count N ==")
	fmt.Printf("  %-8s %-4s %-14s %-16s %-14s\n", "K(txs)", "N", "tx-overhead", "agreement", "total-overhead")
	for _, K := range []int{50, 100, 250, 500, 1000} {
		for _, N := range []int{4, 10, 31, 64} {
			txOv := K * perTxOverhead
			// each of N proposers broadcasts its set of K refs once (reliable broadcast)
			agree := N * K * refBytes
			total := txOv + agree
			out.Rows = append(out.Rows, row{K, N, txOv, agree, total})
			fmt.Printf("  %-8d %-4d %-14s %-16s %-14s\n", K, N,
				kb(txOv), kb(agree), kb(total))
		}
	}
	if b, err := json.MarshalIndent(out, "", "  "); err == nil {
		_ = os.WriteFile("../data/bandwidth.json", b, 0o644)
	}
}

func kb(b int) string { return fmt.Sprintf("%.1f KB", float64(b)/1024) }
