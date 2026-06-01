package commit

import (
	"bytes"
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
)

var (
	recip = common.HexToAddress("0x70997970C51812dc3A010C7d01b50e0d17dc79C8")
	val   = big.NewInt(1_500_000_000_000_000_000) // 1.5 ETH
	data  = []byte{0xa6, 0xf2, 0xae, 0x3a}         // buy() selector
	gas   = uint64(100_000)
)

// Hiding: the same plaintext under fresh salts must yield all-distinct
// commitments, so an observer learns nothing about content from C.
func TestHiding(t *testing.T) {
	const n = 10000
	seen := make(map[common.Hash]struct{}, n)
	for i := 0; i < n; i++ {
		c := Commit(recip, val, data, gas, RandSalt())
		if _, dup := seen[c]; dup {
			t.Fatalf("collision among %d salted commitments of identical plaintext", n)
		}
		seen[c] = struct{}{}
	}
	if len(seen) != n {
		t.Fatalf("expected %d distinct commitments, got %d", n, len(seen))
	}
}

// Determinism: identical (plaintext, salt) reproduces the commitment, and a
// correct reveal verifies.
func TestDeterminismAndVerify(t *testing.T) {
	salt := RandSalt()
	c := Commit(recip, val, data, gas, salt)
	if c != Commit(recip, val, data, gas, salt) {
		t.Fatal("commitment not deterministic for fixed inputs+salt")
	}
	if !Verify(c, recip, val, data, gas, salt) {
		t.Fatal("correct reveal failed to verify")
	}
}

// Binding: altering ANY committed field (with the same salt) must change C and
// fail verification against the original commitment.
func TestBinding(t *testing.T) {
	salt := RandSalt()
	c := Commit(recip, val, data, gas, salt)

	other := common.HexToAddress("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC")
	cases := []struct {
		name string
		ok   bool
	}{
		{"recipient", Verify(c, other, val, data, gas, salt)},
		{"value", Verify(c, recip, big.NewInt(1), data, gas, salt)},
		{"calldata", Verify(c, recip, val, append(bytes.Clone(data), 0x01), gas, salt)},
		{"gasLimit", Verify(c, recip, val, data, gas+1, salt)},
		{"salt", Verify(c, recip, val, data, gas, RandSalt())},
	}
	for _, tc := range cases {
		if tc.ok {
			t.Errorf("binding broken: altered %s still verified", tc.name)
		}
	}
}

// Length-prefixing must prevent concatenation ambiguity between calldata and the
// trailing fields (no second preimage by shifting bytes across the boundary).
func TestCalldataBoundary(t *testing.T) {
	salt := RandSalt()
	c1 := Commit(recip, val, []byte{0x01, 0x02}, gas, salt)
	c2 := Commit(recip, val, []byte{0x01}, gas, salt) // shorter calldata
	if c1 == c2 {
		t.Fatal("calldata length not bound into commitment")
	}
}

// VerifyReveal must reject a reveal whose gasLimit differs from the value that
// was visible (and fee-charged) at B1, even if it opens the commitment.
func TestVerifyRevealGasMismatch(t *testing.T) {
	salt := RandSalt()
	// Commit at the revealed gasLimit, but pretend B1 saw a different one.
	c := Commit(recip, val, data, gas, salt)
	if VerifyReveal(c, gas+1, recip, val, data, gas, salt) {
		t.Fatal("VerifyReveal accepted a gasLimit that differs from the visible B1 value")
	}
	if !VerifyReveal(c, gas, recip, val, data, gas, salt) {
		t.Fatal("VerifyReveal rejected a consistent reveal")
	}
}
