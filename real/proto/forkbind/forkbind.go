// Package forkbind implements fork-bound reveals: an opening is valid only together
// with the sender's signature over the hash of the S1 it opens against. A reveal
// gossiped for one S1 therefore cannot be replayed against a PHT re-included on a
// competing fork, even though (recipient, value, calldata, salt) are public by then.
package forkbind

import (
	"crypto/ecdsa"
	"math/big"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/p2s/proto/commit"
	"github.com/p2s/proto/wire"
)

// Digest is what the sender signs: the PHT reference, the S1 it was included in,
// and a hash of the opening, under a domain tag.
func Digest(ref, s1 common.Hash, m *wire.MT) common.Hash {
	v := m.Value
	if v == nil {
		v = new(big.Int)
	}
	body := crypto.Keccak256(m.Recipient.Bytes(), common.LeftPadBytes(v.Bytes(), 32), m.CallData, m.Salt[:])
	return crypto.Keccak256Hash([]byte("P2S-reveal-v1"), ref.Bytes(), s1.Bytes(), body)
}

// Sign binds an opening to one S1.
func Sign(key *ecdsa.PrivateKey, ref, s1 common.Hash, m *wire.MT) ([]byte, error) {
	return crypto.Sign(Digest(ref, s1, m).Bytes(), key)
}

// Verify accepts a reveal only if it opens the commitment AND the sender signed it
// for exactly this S1.
func Verify(p *wire.PHT, ref, s1 common.Hash, m *wire.MT, sig []byte) bool {
	if !commit.VerifyReveal(p.Commitment, p.GasLimit, m.Recipient, m.Value, m.CallData, m.GasLimit, m.Salt) {
		return false
	}
	pub, err := crypto.SigToPub(Digest(ref, s1, m).Bytes(), sig)
	if err != nil {
		return false
	}
	return crypto.PubkeyToAddress(*pub) == p.Sender
}
