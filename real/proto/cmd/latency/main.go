// Command latency measures P2S's network-round latency over a REAL full-mesh of
// TCP connections (loopback), with a configurable injected one-way link delay to
// model propagation. It reports, vs proposer count N:
//
//   - broadcast latency: leader -> all (the B1 and B2 phases), and
//   - agreement latency: the all-to-all set-union round.
//
// Each message carries a real payload (K MT-refs, 33 bytes each) so serialization
// is exercised. The transport is real TCP; only orchestration is in-process.
//
// Key question answered: does the all-to-all agreement round stay ~1 link-delay
// (sends fan out in parallel) as N grows, or degrade? Latency is the round
// structure; the O(N*K) byte volume (see cmd/bandwidth) is the separate cost that
// a bandwidth-limited link (netem) would convert into additional transfer time.
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"sync"
	"time"
)

// one-way injected link delay (propagation model)
var linkDelay = 50 * time.Millisecond

type node struct {
	id    int
	ln    net.Listener
	peers []net.Conn // outgoing connection to every other node
	recv  chan int   // one signal per received message
}

func framedWrite(c net.Conn, payload []byte) error {
	var hdr [4]byte
	binary.BigEndian.PutUint32(hdr[:], uint32(len(payload)))
	if _, err := c.Write(hdr[:]); err != nil {
		return err
	}
	_, err := c.Write(payload)
	return err
}

func reader(c net.Conn, recv chan<- int) {
	br := bufio.NewReader(c)
	for {
		var hdr [4]byte
		if _, err := io.ReadFull(br, hdr[:]); err != nil {
			return
		}
		n := binary.BigEndian.Uint32(hdr[:])
		buf := make([]byte, n)
		if _, err := io.ReadFull(br, buf); err != nil {
			return
		}
		recv <- 1
	}
}

// send to all peers in parallel, each preceded by the injected one-way delay.
func (nd *node) sendAll(payload []byte) {
	var wg sync.WaitGroup
	for _, c := range nd.peers {
		wg.Add(1)
		go func(c net.Conn) {
			defer wg.Done()
			time.Sleep(linkDelay)
			framedWrite(c, payload)
		}(c)
	}
	wg.Wait()
}

func buildMesh(n int) []*node {
	nodes := make([]*node, n)
	addrs := make([]string, n)
	for i := 0; i < n; i++ {
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			panic(err)
		}
		nodes[i] = &node{id: i, ln: ln, recv: make(chan int, n*n)}
		addrs[i] = ln.Addr().String()
	}
	// accept loop: each node reads from every inbound conn
	var accepting sync.WaitGroup
	for i := 0; i < n; i++ {
		accepting.Add(1)
		go func(nd *node) {
			accepting.Done()
			for {
				c, err := nd.ln.Accept()
				if err != nil {
					return
				}
				go reader(c, nd.recv)
			}
		}(nodes[i])
	}
	accepting.Wait()
	// dial full mesh
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			if i == j {
				continue
			}
			c, err := net.Dial("tcp", addrs[j])
			if err != nil {
				panic(err)
			}
			nodes[i].peers = append(nodes[i].peers, c)
		}
	}
	return nodes
}

func drain(nodes []*node, want int) {
	var wg sync.WaitGroup
	for _, nd := range nodes {
		wg.Add(1)
		go func(nd *node) {
			defer wg.Done()
			for k := 0; k < want; k++ {
				<-nd.recv
			}
		}(nd)
	}
	wg.Wait()
}

func main() {
	K := 1000 // MT-refs carried in each agreement message
	payload := make([]byte, K*33)
	fmt.Printf("one-way link delay = %v; agreement payload = %d KB (K=%d refs)\n",
		linkDelay, len(payload)/1024, K)
	type row struct {
		N                       int
		BroadcastMs, AgreementMs float64
	}
	out := struct {
		LinkDelayMs float64
		K           int
		Rows        []row
	}{float64(linkDelay.Milliseconds()), K, nil}

	fmt.Printf("%-4s %-22s %-22s\n", "N", "broadcast (B1/B2)", "agreement (all-to-all)")
	for _, n := range []int{4, 7, 16, 31, 64} {
		nodes := buildMesh(n)

		// broadcast: leader (node 0) -> all others. Each non-leader receives 1.
		t0 := time.Now()
		nodes[0].sendAll(payload)
		drain(nodes[1:], 1)
		bcast := time.Since(t0)

		// agreement: every node sends to every other in parallel. Each receives n-1.
		t1 := time.Now()
		var wg sync.WaitGroup
		for _, nd := range nodes {
			wg.Add(1)
			go func(nd *node) { defer wg.Done(); nd.sendAll(payload) }(nd)
		}
		go func() { wg.Wait() }()
		drain(nodes, n-1)
		agree := time.Since(t1)

		bms := float64(bcast.Microseconds()) / 1000
		ams := float64(agree.Microseconds()) / 1000
		out.Rows = append(out.Rows, row{n, bms, ams})
		fmt.Printf("%-4d %-22s %-22s\n", n,
			fmt.Sprintf("%.1f ms", bms), fmt.Sprintf("%.1f ms", ams))

		for _, nd := range nodes {
			nd.ln.Close()
			for _, c := range nd.peers {
				c.Close()
			}
		}
	}
	if b, err := json.MarshalIndent(out, "", "  "); err == nil {
		_ = os.WriteFile("../data/latency.json", b, 0o644)
	}
}
