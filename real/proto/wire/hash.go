package wire

import (
	"encoding/binary"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/crypto"
)

// Hash is the canonical identifier of a PHT, computed over its B1-visible fields
// plus the commitment. This is the value referenced by B1.Order and by MT.Ref.
func (p *PHT) Hash() common.Hash {
	var buf []byte
	buf = append(buf, p.Sender.Bytes()...)
	var n8, gl8 [8]byte
	binary.BigEndian.PutUint64(n8[:], p.Nonce)
	buf = append(buf, n8[:]...)
	if p.GasFeeCap != nil {
		buf = append(buf, common.LeftPadBytes(p.GasFeeCap.Bytes(), 32)...)
	} else {
		buf = append(buf, make([]byte, 32)...)
	}
	if p.GasTipCap != nil {
		buf = append(buf, common.LeftPadBytes(p.GasTipCap.Bytes(), 32)...)
	} else {
		buf = append(buf, make([]byte, 32)...)
	}
	binary.BigEndian.PutUint64(gl8[:], p.GasLimit)
	buf = append(buf, gl8[:]...)
	buf = append(buf, p.Commitment.Bytes()...)
	return crypto.Keccak256Hash(buf)
}
