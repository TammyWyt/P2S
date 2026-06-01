// Package feeacct implements P2S reservation-fee accounting. A PHT included in
// B1 burns an irrecoverable reservation fee
//
//	F_res = phi * gasLimit * baseFee
//
// charged at B1 inclusion regardless of whether the matching MT is ever
// revealed. This is what deters block-stuffing and speculative slot reservation
// (over-declaring gasLimit inflates F_res proportionally). Ground truth:
// scripts/simulation/simulator.py:753-764. phi is expressed in basis points
// (phiBps = 1000 => 0.10).
package feeacct

import "math/big"

// ReservationFee returns F_res (wei) for one PHT: phiBps/10000 * gasLimit * baseFee.
func ReservationFee(phiBps uint64, gasLimit uint64, baseFee *big.Int) *big.Int {
	if baseFee == nil {
		return new(big.Int)
	}
	f := new(big.Int).Mul(baseFee, new(big.Int).SetUint64(gasLimit))
	f.Mul(f, new(big.Int).SetUint64(phiBps))
	f.Div(f, big.NewInt(10000))
	return f
}

// TotalBurned sums the reservation fee over a slot's gas limits (all PHTs pay
// at the same baseFee within a slot).
func TotalBurned(phiBps uint64, gasLimits []uint64, baseFee *big.Int) *big.Int {
	total := new(big.Int)
	for _, gl := range gasLimits {
		total.Add(total, ReservationFee(phiBps, gl, baseFee))
	}
	return total
}
