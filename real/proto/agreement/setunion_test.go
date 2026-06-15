package agreement

import (
	"fmt"
	"testing"

	"github.com/ethereum/go-ethereum/common"
)

func ref(s string) Ref { return common.HexToHash(s) }

var (
	a = ref("0x0a")
	b = ref("0x0b")
	c = ref("0x0c")
	x = ref("0xff") // bogus ref fabricated by Byzantine proposers
)

func set(rs ...Ref) map[Ref]struct{} {
	m := make(map[Ref]struct{})
	for _, r := range rs {
		m[r] = struct{}{}
	}
	return m
}

func has(m map[Ref]struct{}, r Ref) bool { _, ok := m[r]; return ok }

// n=4, f=1: 3 honest saw {a,b,c}; 1 Byzantine withholds them and injects a bogus
// ref x. Decision must be exactly {a,b,c}: real refs vouched by 3 >= f+1=2, bogus
// vouched by only 1 < 2.
func TestValidityAndNoInjection_n4f1(t *testing.T) {
	if !QuorumOK(4, 1) {
		t.Fatal("n=4,f=1 should satisfy n>=3f+1")
	}
	reports := map[int]map[Ref]struct{}{
		0: set(a, b, c),
		1: set(a, b, c),
		2: set(a, b, c),
		3: set(x), // Byzantine: withhold real, inject bogus
	}
	d := Decide(1, reports)
	for _, r := range []Ref{a, b, c} {
		if !has(d, r) {
			t.Errorf("validity: real ref %s missing from decision", r.Hex())
		}
	}
	if has(d, x) {
		t.Error("no-injection: bogus ref x was included")
	}
	if len(d) != 3 {
		t.Fatalf("expected 3 refs, got %d", len(d))
	}
}

// n=7, f=2: 5 honest saw {a,b}; 2 Byzantine inject x (and equivocate by sending
// different junk). x has only 2 vouchers < f+1=3 -> excluded; a,b have 5 -> kept.
func TestNoInjection_n7f2(t *testing.T) {
	reports := map[int]map[Ref]struct{}{
		0: set(a, b), 1: set(a, b), 2: set(a, b), 3: set(a, b), 4: set(a, b),
		5: set(x, c), // Byzantine
		6: set(x),    // Byzantine (echoes x to try to reach threshold)
	}
	d := Decide(2, reports)
	if !has(d, a) || !has(d, b) {
		t.Error("validity: a/b missing")
	}
	if has(d, x) {
		t.Error("no-injection: x reached threshold with only 2 Byzantine vouchers")
	}
	if has(d, c) {
		t.Error("no-injection: c (1 voucher) included")
	}
}

// Agreement: any honest proposer applying Decide to the same reliably-broadcast
// reports gets the identical set (determinism).
func TestAgreementDeterministic(t *testing.T) {
	reports := map[int]map[Ref]struct{}{
		0: set(a, b, c), 1: set(a, b), 2: set(a, b, c), 3: set(x),
	}
	d1 := Decide(1, reports)
	d2 := Decide(1, reports)
	if fmt.Sprint(keys(d1)) == "" || len(d1) != len(d2) {
		t.Fatal("nondeterministic size")
	}
	for r := range d1 {
		if !has(d2, r) {
			t.Fatalf("disagreement on %s", r.Hex())
		}
	}
}

// A ref seen by all honest is always decided, even at the maximum fault budget.
func TestValidityAtMaxFaults(t *testing.T) {
	// n=7, f=2: exactly n-f=5 honest report a; 2 Byzantine withhold.
	reports := map[int]map[Ref]struct{}{
		0: set(a), 1: set(a), 2: set(a), 3: set(a), 4: set(a), 5: {}, 6: {},
	}
	d := Decide(2, reports)
	if !has(d, a) {
		t.Fatal("validity broken: a seen by all honest but not decided")
	}
}

// Censorship-resistance: a Byzantine slot leader (validator 0) tries to drop an
// honestly-revealed MT `a` by omitting it from its own report. Because inclusion
// is decided by the f+1-voucher union rule and not by the leader, the f+1=2 other
// honest validators that saw `a` force it into the decided set. n=4, f=1.
// This is the formal content of "leader censorship reduces to non-reveal".
func TestLeaderCannotCensorRevealedMT_n4f1(t *testing.T) {
	reports := map[int]map[Ref]struct{}{
		0: set(b),       // Byzantine leader: omits a, hoping to censor it
		1: set(a, b),    // honest, saw the reveal of a
		2: set(a, b),    // honest, saw the reveal of a
		3: set(a, b),    // honest, saw the reveal of a
	}
	d := Decide(1, reports)
	if !has(d, a) {
		t.Fatal("censorship-resistance broken: leader omission dropped an MT seen by f+1 honest validators")
	}
	if !has(d, b) {
		t.Error("validity: b missing")
	}
}

func keys(m map[Ref]struct{}) []Ref {
	out := make([]Ref, 0, len(m))
	for r := range m {
		out = append(out, r)
	}
	return out
}
