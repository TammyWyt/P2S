// Package wire defines the canonical on-the-wire P2S transaction and block
// types. The field layout is ported from the original scaffolding in
// core/types/types.go (PHTTransaction/MTTransaction) but the unsound crypto
// (Pedersen commitment, Merkle proof, time-based nonce) is intentionally
// dropped; commitments are salted-keccak (see package commit).
package wire

import (
	"math/big"

	"github.com/ethereum/go-ethereum/common"
)

// TxKind discriminates a partially-hidden transaction from its later reveal.
type TxKind uint8

const (
	KindPHT TxKind = 1 // Partially Hidden Transaction (visible at B1)
	KindMT  TxKind = 2 // Matching Transaction (revealed at B2)
)

// PHT is a Partially Hidden Transaction: the fields visible during the B1
// ordering phase, plus a hash commitment that seals the hidden intent fields.
// Recipient/Value/CallData are NOT transmitted at B1 — only Commitment is.
type PHT struct {
	// Visible at B1 (used for ordering and reservation-fee accounting).
	Sender     common.Address `json:"sender"`
	Nonce      uint64         `json:"nonce"`
	GasFeeCap  *big.Int       `json:"gasFeeCap"`
	GasTipCap  *big.Int       `json:"gasTipCap"`
	GasLimit   uint64         `json:"gasLimit"`
	Commitment common.Hash    `json:"commitment"` // salted keccak over hidden fields
	Timestamp  uint64         `json:"timestamp"`
}

// MT is a Matching Transaction: the reveal of a PHT's hidden fields plus the
// salt, submitted during the B2 phase. Verification recomputes the commitment.
type MT struct {
	Ref       common.Hash    `json:"ref"`       // hash of the PHT this reveals
	Recipient common.Address `json:"recipient"`
	Value     *big.Int       `json:"value"`
	CallData  []byte         `json:"callData"`
	GasLimit  uint64         `json:"gasLimit"` // must equal the PHT's visible GasLimit
	Salt      [32]byte       `json:"salt"`
	Timestamp uint64         `json:"timestamp"`
}

// B1 is the preliminary block: an ordered list of PHTs. The order fixed here is
// the order in which the corresponding MTs are executed in B2.
type B1 struct {
	Number    uint64        `json:"number"`
	Parent    common.Hash   `json:"parent"`
	Proposer  common.Address `json:"proposer"`
	Order     []common.Hash `json:"order"` // PHT hashes, in committed order
	Timestamp uint64        `json:"timestamp"`
}

// B2 is the final block: the revealed MTs substituted into the B1 order and
// executed on real EVM state.
type B2 struct {
	Number   uint64        `json:"number"`
	B1Hash   common.Hash   `json:"b1Hash"`
	Proposer common.Address `json:"proposer"`
	Order    []common.Hash `json:"order"` // mirrors B1.Order; MTs in this order
}
