package orchestrator

import (
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/p2s/proto/execdriver"
)

const (
	keyA = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
	keyB = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
	keyC = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)

func eth(n float64) *big.Int {
	f := new(big.Float).Mul(big.NewFloat(n), big.NewFloat(1e18))
	i, _ := f.Int(nil)
	return i
}

func gwei(n int64) *big.Int { return new(big.Int).Mul(big.NewInt(n), big.NewInt(1e9)) }

// The committed B1 order is by priority fee (content-blind); execution at B2
// follows that order and threads state. We arrange a dependency A->B->C that
// only succeeds if the higher-tip A->B runs before the lower-tip B->C. Input
// order is reversed to prove the orchestrator sorts by tip, not arrival.
func TestContentBlindOrderingAndThreading(t *testing.T) {
	A, _ := execdriver.NewAccount(keyA)
	B, _ := execdriver.NewAccount(keyB)
	C, _ := execdriver.NewAccount(keyC)

	alloc := map[common.Address]execdriver.AllocAccount{
		A.Addr: {Balance: eth(2), Nonce: 0},
		B.Addr: {Balance: big.NewInt(0), Nonce: 0},
		C.Addr: {Balance: big.NewInt(0), Nonce: 0},
	}
	env := execdriver.DefaultEnv()

	// A->B with HIGH tip; B->C with LOW tip. B can only fund its send after A's.
	subAB := &Submission{From: A, To: B.Addr, Value: eth(1.5), Gas: 21000,
		GasFeeCap: gwei(10), GasTipCap: gwei(10), Nonce: 0}
	subBC := &Submission{From: B, To: C.Addr, Value: eth(1.0), Gas: 21000,
		GasFeeCap: gwei(2), GasTipCap: gwei(2), Nonce: 0}

	// pass in REVERSE of the tip order to ensure sorting, not arrival, decides
	res, err := RunSlot([]*Submission{subBC, subAB}, alloc, env, 1000)
	if err != nil {
		t.Fatalf("RunSlot: %v", err)
	}
	if len(res.Order) != 2 {
		t.Fatalf("expected 2 ordered PHTs, got %d", len(res.Order))
	}
	// C ends with 1.0 ETH ONLY if A->B executed before B->C
	cBal := res.Exec.Post[C.Addr]
	if cBal == nil || cBal.Cmp(eth(1.0)) != 0 {
		t.Fatalf("C balance = %v, want 1e18 (proves A->B ran before B->C)", cBal)
	}
	if len(res.Exec.Rejected) != 0 {
		t.Fatalf("unexpected rejected txs: %+v", res.Exec.Rejected)
	}
}

// Reservation fee F_res = phiBps/10000 * gasLimit * baseFee, summed over PHTs,
// burned at B1 regardless of execution.
func TestFResBurn(t *testing.T) {
	A, _ := execdriver.NewAccount(keyA)
	B, _ := execdriver.NewAccount(keyB)
	alloc := map[common.Address]execdriver.AllocAccount{
		A.Addr: {Balance: eth(10), Nonce: 0},
		B.Addr: {Balance: eth(10), Nonce: 0},
	}
	env := execdriver.DefaultEnv() // BaseFee = 1 wei
	subs := []*Submission{
		{From: A, To: B.Addr, Value: eth(1), Gas: 21000, GasFeeCap: gwei(5), GasTipCap: gwei(5), Nonce: 0},
		{From: B, To: A.Addr, Value: eth(1), Gas: 50000, GasFeeCap: gwei(3), GasTipCap: gwei(3), Nonce: 0},
	}
	res, err := RunSlot(subs, alloc, env, 1000) // phi = 0.10
	if err != nil {
		t.Fatalf("RunSlot: %v", err)
	}
	// 1000/10000 * (21000 + 50000) * 1 wei = 0.1 * 71000 = 7100 wei
	want := big.NewInt(7100)
	if res.FResBurned.Cmp(want) != 0 {
		t.Fatalf("F_res burned = %v, want %v", res.FResBurned, want)
	}
}
