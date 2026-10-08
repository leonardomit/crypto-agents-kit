"""Multi-chain helpers (Base/BNB/Arbitrum): registry, failover RPC, safety guards.

Hard rules:
- every live 'to' must pass assert_live_to_reg: on per-chain allowlist (chains.json, verified) AND eth_getCode non-empty
- approvals: exact amount only (assert_exact_approve)
- dry-run default; live only with DRY_RUN=0 AND --execute AND --i-understand-live
"""
from __future__ import annotations
import json, os, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG_PATH = HERE / "chains.json"
UNLIMITED_THRESHOLD = 1 << 200
CHAIN_IDS = {"base": 8453, "bnb": 56, "arbitrum": 42161}
ARB = {"chain_id": 42161, "native": "ETH", "rpc": ["https://arb1.arbitrum.io/rpc", "https://arbitrum-one-rpc.publicnode.com"]}

def registry() -> dict:
    d = json.loads(REG_PATH.read_text())
    if not d.get("verified"):
        raise SystemExit("chains.json não verificado — rode build_chains_registry.py")
    return d["chains"]

def make_w3(chain: str, rpcs: list[str] | None = None):
    from web3 import Web3
    from web3.providers.rpc import HTTPProvider
    from web3.middleware import ExtraDataToPOAMiddleware
    cfg = ARB if chain == "arbitrum" else ({"chain_id": CHAIN_IDS[chain], "rpc": rpcs} if rpcs else registry()[chain])
    env = os.environ.get(f"RPC_{chain.upper()}")
    urls = ([env] if env else []) + list(rpcs or cfg["rpc"])

    class Failover(HTTPProvider):
        def __init__(self):
            super().__init__(urls[0], request_kwargs={"timeout": 15})
            self._urls = urls
        def make_request(self, method, params):
            last = None
            for attempt in range(6):
                u = self._urls[attempt % len(self._urls)]
                self.endpoint_uri = u
                try:
                    r = super().make_request(method, params)
                    if isinstance(r, dict) and "error" in r and isinstance(r["error"], dict) and r["error"].get("code") in (-32005, -32001, 429):
                        last = r; time.sleep(0.4 * (attempt + 1)); continue
                    return r
                except Exception as e:  # 429/timeout -> next RPC
                    last = e; time.sleep(0.3 * (attempt + 1))
            if isinstance(last, Exception):
                raise last
            return last
    w3 = Web3(Failover())
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if w3.eth.chain_id != cfg["chain_id"]:
        raise SystemExit(f"chainId errado para {chain}")
    return w3

def allowlist(chain: str) -> set[str]:
    c = registry()[chain]
    return {v["address"].lower() for s in ("tokens", "contracts") for v in c[s].values() if v.get("ok")}

def addr(chain: str, key: str) -> str:
    c = registry()[chain]
    e = c["tokens"].get(key) or c["contracts"].get(key)
    if not e or not e.get("ok"):
        raise SystemExit(f"{key} não está no registro verificado de {chain}")
    return e["address"]

def token(chain: str, sym: str) -> tuple[str, int]:
    e = registry()[chain]["tokens"].get(sym.lower())
    if not e or not e.get("ok"):
        raise SystemExit(f"token {sym} fora do allowlist de {chain}")
    return e["address"], e["decimals"]

def assert_live_to_reg(w3, chain: str, to: str) -> None:
    if to.lower() not in allowlist(chain):
        raise SystemExit(f"bloqueado: {to} fora do allowlist verificado de {chain}")
    code = w3.eth.get_code(w3.to_checksum_address(to))
    if not code:
        raise SystemExit(f"bloqueado: eth_getCode vazio em {chain}: {to}")

def assert_exact_approve(amount: int, needed: int) -> None:
    if amount != needed or amount >= UNLIMITED_THRESHOLD:
        raise SystemExit(f"bloqueado: approve deve ser exato ({amount} != {needed})")

def live_allowed(execute: bool, ack: bool) -> bool:
    return os.environ.get("DRY_RUN", "1") in ("0", "false", "False", "no") and execute and ack

def erc20_slots(w3, tok: str, owner: str, spender: str):
    """Find balance & allowance mapping slots (simulation only) by probing with state overrides."""
    from eth_abi import encode
    abi = [{"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
           {"name": "allowance", "type": "function", "stateMutability": "view", "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "outputs": [{"type": "uint256"}]}]
    c = w3.eth.contract(address=tok, abi=abi); probe = 987654321123
    bal_slot = allow_slot = None
    hx = lambda b: "0x" + bytes(b).hex()
    pv = "0x" + probe.to_bytes(32, "big").hex()
    for k in range(0, 60):
        if bal_slot is None:
            for enc in (lambda: encode(["address", "uint256"], [owner, k]), lambda: encode(["uint256", "address"], [k, owner])):
                s = w3.keccak(enc())
                try:
                    if c.functions.balanceOf(owner).call(state_override={tok: {"stateDiff": {hx(s): pv}}}) == probe:
                        bal_slot = hx(s); break
                except Exception:
                    pass
        if allow_slot is None:
            inner = w3.keccak(encode(["address", "uint256"], [owner, k]))
            s = w3.keccak(encode(["address"], [spender]) + inner)
            try:
                if c.functions.allowance(owner, spender).call(state_override={tok: {"stateDiff": {hx(s): pv}}}) == probe:
                    allow_slot = hx(s)
            except Exception:
                pass
        if bal_slot and allow_slot:
            break
    return bal_slot, allow_slot

def gas_cost(w3, chain: str, gas_units: int, tx_data: bytes | None = None, to: str | None = None) -> dict:
    gp = w3.eth.gas_price
    out = {"gas_price_wei": gp, "gas_units": gas_units, "l2_exec_wei": gp * gas_units, "l1_fee_wei": 0}
    if chain == "base" and tx_data is not None:
        # OP-Stack GasPriceOracle.getL1Fee(bytes) on an unsigned RLP-ish payload (+68 bytes sig overhead approx)
        abi = [{"name": "getL1Fee", "type": "function", "stateMutability": "view", "inputs": [{"name": "d", "type": "bytes"}], "outputs": [{"type": "uint256"}]},
               {"name": "getL1FeeUpperBound", "type": "function", "stateMutability": "view", "inputs": [{"name": "s", "type": "uint256"}], "outputs": [{"type": "uint256"}]}]
        o = w3.eth.contract(address="0x420000000000000000000000000000000000000F", abi=abi)
        import rlp  # noqa
        payload = rlp.encode([8453, 1, 1000000, gp * 2, gas_units, bytes.fromhex(to[2:]), 0, tx_data, [], 0, b"\x11" * 32, b"\x22" * 32])
        raw = b"\x02" + payload
        out["l1_fee_wei"] = o.functions.getL1Fee(raw).call()
        try:
            out["l1_fee_upper_bound_wei"] = o.functions.getL1FeeUpperBound(len(raw)).call()
        except Exception:
            pass
    out["total_wei"] = out["l2_exec_wei"] + out["l1_fee_wei"]
    return out
