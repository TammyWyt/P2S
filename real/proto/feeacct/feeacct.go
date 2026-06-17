// Package feeacct implements P2S reservation-fee accounting. The reservation fee
//
//	F_res = phi * gasLimit * baseFee
//
// is a FLOOR on the base fee, not an additive surcharge. It is prepaid at B1
// inclusion; on revelation the transaction pays
//
//	G = max(F_res, F_base) + F_tip,   F_base = gasUsed*baseFee, F_tip = gasUsed*priorityFee
//
// so a transaction that consumes at least phi*gasLimit of gas pays exactly an
// ordinary EIP-1559 fee (the floor is absorbed). F_res is forfeited only when
// the matching MT is never revealed (gasUsed = 0), which is what deters
// block-stuffing and speculative slot reservation (over-declaring gasLimit
// inflates the floor proportionally). phi is in basis points (phiBps = 1000 => 0.10).
package feeacct

import "math/big"

// ReservationFee returns the floor F_res (wei) for one PHT: phiBps/10000 * gasLimit * baseFee.
func ReservationFee(phiBps uint64, gasLimit uint64, baseFee *big.Int) *big.Int {
	if baseFee == nil {
		return new(big.Int)
	}
	f := new(big.Int).Mul(baseFee, new(big.Int).SetUint64(gasLimit))
	f.Mul(f, new(big.Int).SetUint64(phiBps))
	f.Div(f, big.NewInt(10000))
	return f
}

// TotalFee returns the user's total fee G = max(F_res, F_base) + F_tip for a
// revealed-and-executed transaction, with fBase = gasUsed*baseFee and
// fTip = gasUsed*priorityFee. The reservation acts as a floor on the base
// component, so a transaction consuming >= phi*gasLimit pays only fBase + fTip.
func TotalFee(fRes, fBase, fTip *big.Int) *big.Int {
	base := fBase
	if fRes != nil && (fBase == nil || fRes.Cmp(fBase) > 0) {
		base = fRes
	}
	out := new(big.Int)
	if base != nil {
		out.Set(base)
	}
	if fTip != nil {
		out.Add(out, fTip)
	}
	return out
}

// TotalReserved sums the reservation floor prepaid at B1 over a slot's gas
// limits (all PHTs pay at the same baseFee within a slot). A PHT that reveals
// and executes recovers this against its base fee via TotalFee; one that never
// reveals forfeits it.
func TotalReserved(phiBps uint64, gasLimits []uint64, baseFee *big.Int) *big.Int {
	total := new(big.Int)
	for _, gl := range gasLimits {
		total.Add(total, ReservationFee(phiBps, gl, baseFee))
	}
	return total
}
