// Package execdriver executes an explicitly ordered list of transactions on a
// given EVM pre-state using go-ethereum's `evm t8n` (stateless state-transition)
// tool. This is the P2S execution backend: the B2 phase hands the orchestrator's
// B1-committed order to Run, and t8n executes it on real EVM state with NO
// priority-fee reordering -- which is exactly the property the protocol relies
// on (validated by the M1 spike: reordering the same txs changes the result).
package execdriver

import (
	"crypto/ecdsa"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/common/hexutil"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/crypto"
)

// Account is a signing key plus its address.
type Account struct {
	Addr common.Address
	key  *ecdsa.PrivateKey
}

func NewAccount(hexKey string) (*Account, error) {
	k, err := crypto.HexToECDSA(stripHex(hexKey))
	if err != nil {
		return nil, err
	}
	return &Account{Addr: crypto.PubkeyToAddress(k.PublicKey), key: k}, nil
}

func stripHex(s string) string {
	if len(s) >= 2 && (s[:2] == "0x" || s[:2] == "0X") {
		return s[2:]
	}
	return s
}

// Call is one transaction to execute, in the order given to Run.
type Call struct {
	From     *Account
	To       *common.Address // nil => contract creation
	Value    *big.Int
	Gas      uint64
	GasPrice *big.Int
	Data     []byte
	Nonce    uint64
}

// AllocAccount is a pre-state entry: balance, nonce, optional code and storage.
type AllocAccount struct {
	Balance *big.Int
	Nonce   uint64
	Code    []byte
	Storage map[common.Hash]common.Hash
}

// Env is the block environment for the transition.
type Env struct {
	Coinbase   common.Address
	GasLimit   uint64
	Number     uint64
	Timestamp  uint64
	BaseFee    *big.Int
	Random     common.Hash
}

func DefaultEnv() Env {
	return Env{GasLimit: 0x7fffffffffffffff, Number: 1, Timestamp: 1000, BaseFee: big.NewInt(1)}
}

// Receipt is the subset of t8n's per-tx result we expose.
type Receipt struct {
	Status          hexutil.Uint64 `json:"status"`
	GasUsed         hexutil.Uint64 `json:"gasUsed"`
	ContractAddress *common.Address `json:"contractAddress"`
}

type rejected struct {
	Index int    `json:"index"`
	Error string `json:"error"`
}

// Result is the outcome of a transition.
type Result struct {
	Receipts []Receipt
	Rejected []rejected
	// Post is the resulting state: address -> balance (wei). Only balances are
	// parsed here; extend if storage/nonce are needed.
	Post map[common.Address]*big.Int
}

// chainID is fixed to mainnet (1); signing and t8n use the same value.
var chainID = big.NewInt(1)

// Run executes calls in order on alloc under env via `evm t8n` and returns the
// receipts and resulting balances. The fork is Shanghai (matches the spike).
func Run(alloc map[common.Address]AllocAccount, env Env, calls []*Call) (*Result, error) {
	dir, err := os.MkdirTemp("", "execdriver")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(dir)

	if err := writeJSON(filepath.Join(dir, "alloc.json"), allocJSON(alloc)); err != nil {
		return nil, err
	}
	if err := writeJSON(filepath.Join(dir, "env.json"), envJSON(env)); err != nil {
		return nil, err
	}
	txs, err := signedTxsJSON(calls)
	if err != nil {
		return nil, err
	}
	if err := writeJSON(filepath.Join(dir, "txs.json"), txs); err != nil {
		return nil, err
	}

	evmBin := os.Getenv("EVM")
	if evmBin == "" {
		evmBin = "evm"
	}
	cmd := exec.Command(evmBin, "t8n",
		"--input.alloc", filepath.Join(dir, "alloc.json"),
		"--input.env", filepath.Join(dir, "env.json"),
		"--input.txs", filepath.Join(dir, "txs.json"),
		"--output.basedir", dir,
		"--output.alloc", "out_alloc.json",
		"--output.result", "out_result.json",
		"--state.fork", "Shanghai",
		"--state.chainid", "1",
	)
	if out, err := cmd.CombinedOutput(); err != nil {
		return nil, fmt.Errorf("evm t8n failed: %v\n%s", err, out)
	}
	return parseResult(dir)
}

func writeJSON(path string, v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o600)
}

func allocJSON(alloc map[common.Address]AllocAccount) map[string]any {
	out := make(map[string]any, len(alloc))
	for addr, a := range alloc {
		bal := "0x0"
		if a.Balance != nil {
			bal = hexutil.EncodeBig(a.Balance)
		}
		entry := map[string]any{"balance": bal, "nonce": hexutil.EncodeUint64(a.Nonce)}
		if len(a.Code) > 0 {
			entry["code"] = hexutil.Encode(a.Code)
		}
		if len(a.Storage) > 0 {
			st := make(map[string]string, len(a.Storage))
			for k, v := range a.Storage {
				st[k.Hex()] = v.Hex()
			}
			entry["storage"] = st
		}
		out[addr.Hex()] = entry
	}
	return out
}

func envJSON(e Env) map[string]any {
	bf := "0x1"
	if e.BaseFee != nil {
		bf = hexutil.EncodeBig(e.BaseFee)
	}
	return map[string]any{
		"currentCoinbase":  e.Coinbase.Hex(),
		"currentGasLimit":  hexutil.EncodeUint64(e.GasLimit),
		"currentNumber":    hexutil.EncodeUint64(e.Number),
		"currentTimestamp": hexutil.EncodeUint64(e.Timestamp),
		"currentBaseFee":   bf,
		"currentRandom":    e.Random.Hex(),
		"withdrawals":      []any{},
	}
}

func signedTxsJSON(calls []*Call) ([]json.RawMessage, error) {
	signer := types.LatestSignerForChainID(chainID)
	out := make([]json.RawMessage, 0, len(calls))
	for _, c := range calls {
		inner := &types.LegacyTx{
			Nonce:    c.Nonce,
			GasPrice: c.GasPrice,
			Gas:      c.Gas,
			To:       c.To,
			Value:    c.Value,
			Data:     c.Data,
		}
		tx, err := types.SignNewTx(c.From.key, signer, inner)
		if err != nil {
			return nil, err
		}
		b, err := tx.MarshalJSON()
		if err != nil {
			return nil, err
		}
		out = append(out, b)
	}
	return out, nil
}

func parseResult(dir string) (*Result, error) {
	var res struct {
		Receipts []Receipt  `json:"receipts"`
		Rejected []rejected `json:"rejected"`
	}
	rb, err := os.ReadFile(filepath.Join(dir, "out_result.json"))
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(rb, &res); err != nil {
		return nil, err
	}
	var rawAlloc map[string]struct {
		Balance string `json:"balance"`
	}
	ab, err := os.ReadFile(filepath.Join(dir, "out_alloc.json"))
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(ab, &rawAlloc); err != nil {
		return nil, err
	}
	post := make(map[common.Address]*big.Int, len(rawAlloc))
	for addr, v := range rawAlloc {
		bal, ok := new(big.Int).SetString(stripHex(v.Balance), 16)
		if !ok {
			bal = new(big.Int)
		}
		post[common.HexToAddress(addr)] = bal
	}
	return &Result{Receipts: res.Receipts, Rejected: res.Rejected, Post: post}, nil
}
