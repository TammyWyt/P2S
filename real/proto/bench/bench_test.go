// Package bench measures the per-operation COMPUTE latency P2S adds, to show it
// is negligible relative to network propagation (so the only material latency
// cost is the extra B2 propagation phase + one agreement round, not computation).
package bench

import (
	"fmt"
	"math/big"
	"testing"

	"github.com/ethereum/go-ethereum/common"
	"github.com/p2s/proto/agreement"
	"github.com/p2s/proto/commit"
)

var (
	recip    = common.HexToAddress("0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc")
	val      = big.NewInt(1e18)
	calldata = make([]byte, 4+32*8) // representative swap calldata
	gas      = uint64(200000)
)

func BenchmarkCommit(b *testing.B) {
	salt := commit.RandSalt()
	b.ReportAllocs()
	for i := 0; i < b.N; i++ {
		commit.Commit(recip, val, calldata, gas, salt)
	}
}

func BenchmarkVerifyReveal(b *testing.B) {
	salt := commit.RandSalt()
	c := commit.Commit(recip, val, calldata, gas, salt)
	b.ReportAllocs()
	for i := 0; i < b.N; i++ {
		if !commit.VerifyReveal(c, gas, recip, val, calldata, gas, salt) {
			b.Fatal("verify failed")
		}
	}
}

// Agreement decision over a full slot: N proposers each reporting K MT-refs.
func BenchmarkAgreementDecide(b *testing.B) {
	for _, nk := range []struct{ N, K int }{{4, 100}, {31, 500}, {64, 1000}} {
		b.Run(fmt.Sprintf("N%d_K%d", nk.N, nk.K), func(b *testing.B) {
			refs := make([]agreement.Ref, nk.K)
			for i := range refs {
				refs[i] = common.BigToHash(big.NewInt(int64(i)))
			}
			reports := make(map[int]map[agreement.Ref]struct{}, nk.N)
			for p := 0; p < nk.N; p++ {
				s := make(map[agreement.Ref]struct{}, nk.K)
				for _, r := range refs {
					s[r] = struct{}{}
				}
				reports[p] = s
			}
			f := (nk.N - 1) / 3
			b.ResetTimer()
			b.ReportAllocs()
			for i := 0; i < b.N; i++ {
				agreement.Decide(f, reports)
			}
		})
	}
}
