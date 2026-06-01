// Package expool implements the P2S "expool": the proposer-local mempool that
// holds Partially Hidden Transactions during the B1 window and their revealed
// Matching Transactions during the B2 window.
//
// It enforces the two invariants the protocol relies on:
//   - at most one live PHT per (sender, nonce), so a sender cannot occupy two
//     ordering slots with the same nonce;
//   - an MT is only retained if it references a known PHT.
package expool

import (
	"sync"

	"github.com/ethereum/go-ethereum/common"
	"github.com/p2s/proto/wire"
)

type senderNonce struct {
	sender common.Address
	nonce  uint64
}

// Expool is safe for concurrent use by the networking and orchestration layers.
type Expool struct {
	mu   sync.RWMutex
	phts map[common.Hash]*wire.PHT // by PHT hash
	seen map[senderNonce]common.Hash
	mts  map[common.Hash]*wire.MT // by referenced PHT hash
}

func New() *Expool {
	return &Expool{
		phts: make(map[common.Hash]*wire.PHT),
		seen: make(map[senderNonce]common.Hash),
		mts:  make(map[common.Hash]*wire.MT),
	}
}

// AddPHT inserts a PHT. It returns the PHT hash and whether it was accepted.
// A PHT is rejected as a duplicate if (sender, nonce) is already occupied by a
// different PHT, or if the identical PHT hash is already present.
func (e *Expool) AddPHT(p *wire.PHT) (common.Hash, bool) {
	h := p.Hash()
	key := senderNonce{p.Sender, p.Nonce}
	e.mu.Lock()
	defer e.mu.Unlock()
	if existing, ok := e.seen[key]; ok && existing != h {
		return h, false // (sender, nonce) already taken by a different PHT
	}
	if _, ok := e.phts[h]; ok {
		return h, false // exact duplicate
	}
	e.phts[h] = p
	e.seen[key] = h
	return h, true
}

// AddMT retains a revealed MT iff it references a known PHT. The caller is
// responsible for cryptographic verification (commit.VerifyReveal) before
// trusting the contents.
func (e *Expool) AddMT(m *wire.MT) bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	if _, ok := e.phts[m.Ref]; !ok {
		return false
	}
	e.mts[m.Ref] = m
	return true
}

// PHT returns the PHT with the given hash, if present.
func (e *Expool) PHT(h common.Hash) (*wire.PHT, bool) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	p, ok := e.phts[h]
	return p, ok
}

// MT returns the revealed MT for a PHT hash, if present.
func (e *Expool) MT(ref common.Hash) (*wire.MT, bool) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	m, ok := e.mts[ref]
	return m, ok
}

// PendingPHTs returns a snapshot of all live PHT hashes for the orderer.
func (e *Expool) PendingPHTs() []common.Hash {
	e.mu.RLock()
	defer e.mu.RUnlock()
	out := make([]common.Hash, 0, len(e.phts))
	for h := range e.phts {
		out = append(out, h)
	}
	return out
}

// RevealedCount reports how many PHTs have a matching MT (B2 set-union input).
func (e *Expool) RevealedCount() int {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return len(e.mts)
}
