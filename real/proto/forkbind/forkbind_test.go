package forkbind

import (
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
	"github.com/p2s/proto/commit"
	"github.com/p2s/proto/wire"
)

func fixture(t *testing.T) (*wire.PHT, *wire.MT, common.Hash) {
	t.Helper()
	key, _ := crypto.HexToECDSA("b71c71a67e1177ad4e901695e1b4b9ee17ae16c6668d313dac2d0ed7ddf4b4a1")
	salt := commit.RandSalt()
	to := common.HexToAddress("0x7a250d5630b4cf539739df2c5dacb4c659f2488d")
	val, data := big.NewInt(1e17), []byte{0x38, 0xed, 0x17, 0x39, 1, 2, 3}
	c := commit.Commit(to, val, data, 150000, salt)
	p := &wire.PHT{Sender: crypto.PubkeyToAddress(key.PublicKey), GasLimit: 150000, Commitment: c}
	m := &wire.MT{Recipient: to, Value: val, CallData: data, GasLimit: 150000, Salt: salt}
	return p, m, crypto.Keccak256Hash(c.Bytes())
}

var key, _ = crypto.HexToECDSA("b71c71a67e1177ad4e901695e1b4b9ee17ae16c6668d313dac2d0ed7ddf4b4a1")

func TestHonestRevealAccepted(t *testing.T) {
	p, m, ref := fixture(t)
	s1 := common.HexToHash("0xa1")
	sig, _ := Sign(key, ref, s1, m)
	if !Verify(p, ref, s1, m, sig) {
		t.Fatal("honest reveal rejected")
	}
}

// The reorg attack: the opening is public, the PHT sits in a competing S1', and the
// attacker replays the gossiped reveal there.
func TestGossipedRevealRejectedOnCompetingFork(t *testing.T) {
	p, m, ref := fixture(t)
	s1, s1fork := common.HexToHash("0xa1"), common.HexToHash("0xb2")
	sig, _ := Sign(key, ref, s1, m)
	if Verify(p, ref, s1fork, m, sig) {
		t.Fatal("reveal replayed on fork")
	}
}

func TestAttackerCannotReSignForFork(t *testing.T) {
	p, m, ref := fixture(t)
	s1fork := common.HexToHash("0xb2")
	atk, _ := crypto.GenerateKey()
	sig, _ := Sign(atk, ref, s1fork, m)
	if Verify(p, ref, s1fork, m, sig) {
		t.Fatal("foreign signature accepted")
	}
}

func TestSubstitutedOpeningRejected(t *testing.T) {
	p, m, ref := fixture(t)
	s1 := common.HexToHash("0xa1")
	sig, _ := Sign(key, ref, s1, m)
	m2 := *m
	m2.CallData = []byte{9, 9}
	if Verify(p, ref, s1, &m2, sig) {
		t.Fatal("substituted opening accepted")
	}
}
