// Package agreement implements the P2S set-union agreement over revealed MTs.
//
// In B2, proposers must agree on WHICH matching transactions were revealed. Each
// proposer reliably broadcasts the set of MT refs it has seen; the agreed set is
// every ref vouched for by at least f+1 proposers. With n >= 3f+1 and up to f
// Byzantine faults this gives:
//
//   - validity:    a ref every honest proposer saw appears in >= n-f >= 2f+1 >=
//                  f+1 reports, so it is included;
//   - no injection: a ref only Byzantine proposers claim appears in <= f reports,
//                  below the f+1 threshold, so it is excluded;
//   - agreement:   the threshold is applied deterministically to the same
//                  reliably-broadcast reports, so all honest proposers decide
//                  the same set.
//
// This reuses the host chain's f<n/3 fault-tolerance rather than adding a new
// trusted committee.
package agreement

import "github.com/ethereum/go-ethereum/common"

// Ref identifies a revealed MT (its PHT hash).
type Ref = common.Hash

// QuorumOK reports whether n proposers tolerate f Byzantine faults (n >= 3f+1).
func QuorumOK(n, f int) bool { return f >= 0 && n >= 3*f+1 }

// Decide returns the agreed MT set: every ref vouched for by at least f+1 of the
// reports. reports maps proposer id -> set of refs that proposer broadcast
// (Byzantine proposers may submit arbitrary sets). The result is deterministic
// in the reports, so honest proposers given the same reports agree.
func Decide(f int, reports map[int]map[Ref]struct{}) map[Ref]struct{} {
	counts := make(map[Ref]int)
	for _, set := range reports {
		for r := range set {
			counts[r]++
		}
	}
	decided := make(map[Ref]struct{})
	for r, c := range counts {
		if c >= f+1 {
			decided[r] = struct{}{}
		}
	}
	return decided
}
