// Package commit implements the P2S partially-hidden-transaction commitment.
//
// The commitment is a salted keccak hash over the hidden intent fields:
//
//	C = keccak256( recipient[20] ‖ value[32 BE] ‖ len(calldata)[4 BE] ‖ calldata
//	               ‖ gasLimit[8 BE] ‖ salt[32] )
//
// This matches the paper's random-oracle-model security argument exactly:
//   - hiding   comes from the 32-byte salt (drawn from crypto/rand), which makes
//     C indistinguishable from random even for low-entropy fields (value,
//     recipient);
//   - binding  comes from keccak256 collision resistance.
//
// It deliberately replaces the original scaffolding's Pedersen commitment (which
// had no blinding factor and a string-compare "Verify") and Merkle proof stub,
// neither of which was hiding or binding.
package commit

import (
	"crypto/rand"
	"encoding/binary"
	"math/big"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

// RandSalt returns a fresh 32-byte salt from a cryptographic RNG.
func RandSalt() [32]byte {
	var s [32]byte
	if _, err := rand.Read(s[:]); err != nil {
		panic("commit: crypto/rand failure: " + err.Error())
	}
	return s
}

// Commit computes the salted-keccak commitment over the hidden fields.
func Commit(recipient common.Address, value *big.Int, calldata []byte, gasLimit uint64, salt [32]byte) common.Hash {
	if value == nil {
		value = new(big.Int)
	}
	var (
		valBytes = common.LeftPadBytes(value.Bytes(), 32)
		lenBuf   [4]byte
		gasBuf   [8]byte
	)
	binary.BigEndian.PutUint32(lenBuf[:], uint32(len(calldata)))
	binary.BigEndian.PutUint64(gasBuf[:], gasLimit)

	buf := make([]byte, 0, 20+32+4+len(calldata)+8+32)
	buf = append(buf, recipient.Bytes()...)
	buf = append(buf, valBytes...)
	buf = append(buf, lenBuf[:]...)
	buf = append(buf, calldata...)
	buf = append(buf, gasBuf[:]...)
	buf = append(buf, salt[:]...)
	return crypto.Keccak256Hash(buf)
}

// Verify checks that a revealed (recipient, value, calldata, gasLimit, salt)
// opens the given commitment. The caller must SEPARATELY check that the revealed
// gasLimit equals the PHT's visible gasLimit (so the reservation fee cannot be
// gamed); see VerifyReveal for the combined check.
func Verify(c common.Hash, recipient common.Address, value *big.Int, calldata []byte, gasLimit uint64, salt [32]byte) bool {
	return Commit(recipient, value, calldata, gasLimit, salt) == c
}

// VerifyReveal checks both that the reveal opens the commitment and that the
// revealed gasLimit matches the value that was visible (and fee-charged) at B1.
func VerifyReveal(c common.Hash, visibleGasLimit uint64, recipient common.Address, value *big.Int, calldata []byte, revealedGasLimit uint64, salt [32]byte) bool {
	if revealedGasLimit != visibleGasLimit {
		return false
	}
	return Verify(c, recipient, value, calldata, revealedGasLimit, salt)
}
