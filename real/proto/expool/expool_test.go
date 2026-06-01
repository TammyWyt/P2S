package expool

import (
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/p2s/proto/commit"
	"github.com/p2s/proto/wire"
)

func mkPHT(sender common.Address, nonce uint64, recip common.Address, val int64) (*wire.PHT, *wire.MT) {
	salt := commit.RandSalt()
	value := big.NewInt(val)
	data := []byte{0x01}
	gl := uint64(100000)
	c := commit.Commit(recip, value, data, gl, salt)
	p := &wire.PHT{Sender: sender, Nonce: nonce, GasFeeCap: big.NewInt(1e9),
		GasTipCap: big.NewInt(1e9), GasLimit: gl, Commitment: c}
	m := &wire.MT{Ref: p.Hash(), Recipient: recip, Value: value, CallData: data, GasLimit: gl, Salt: salt}
	return p, m
}

var (
	alice = common.HexToAddress("0x1111111111111111111111111111111111111111")
	bob   = common.HexToAddress("0x2222222222222222222222222222222222222222")
)

func TestAddAndDedup(t *testing.T) {
	e := New()
	p, _ := mkPHT(alice, 0, bob, 5)
	h, ok := e.AddPHT(p)
	if !ok {
		t.Fatal("first PHT rejected")
	}
	if _, ok := e.AddPHT(p); ok {
		t.Fatal("exact duplicate PHT accepted")
	}
	// same (sender, nonce), different content -> rejected
	p2, _ := mkPHT(alice, 0, bob, 99)
	if _, ok := e.AddPHT(p2); ok {
		t.Fatal("second PHT at same (sender,nonce) accepted")
	}
	if got, _ := e.PHT(h); got == nil {
		t.Fatal("PHT not retrievable")
	}
}

func TestMTRequiresKnownPHT(t *testing.T) {
	e := New()
	p, m := mkPHT(alice, 1, bob, 5)
	// MT before its PHT -> rejected
	if e.AddMT(m) {
		t.Fatal("MT accepted without a known PHT")
	}
	e.AddPHT(p)
	if !e.AddMT(m) {
		t.Fatal("MT rejected after its PHT was present")
	}
	if e.RevealedCount() != 1 {
		t.Fatalf("revealed count = %d, want 1", e.RevealedCount())
	}
	got, ok := e.MT(p.Hash())
	if !ok || got.Recipient != bob {
		t.Fatal("revealed MT not retrievable")
	}
}

func TestDistinctNoncesCoexist(t *testing.T) {
	e := New()
	p0, _ := mkPHT(alice, 0, bob, 1)
	p1, _ := mkPHT(alice, 1, bob, 2)
	e.AddPHT(p0)
	e.AddPHT(p1)
	if len(e.PendingPHTs()) != 2 {
		t.Fatalf("want 2 pending PHTs, got %d", len(e.PendingPHTs()))
	}
}
