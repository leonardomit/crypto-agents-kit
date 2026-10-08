#!/usr/bin/env python3
"""Watcher de LP Uniswap v3 fora da faixa (out-of-range) -> saída automática opcional.

Lê slot0 do pool + positions(tokenId) a cada --interval s. Se o tick ficar fora de [tickLower, tickUpper)
por --streak leituras seguidas, chama lp_exit.py 100% com amount mins = --min-pct% do esperado
(sem swap: você fica com os dois tokens). Escreve o resultado em $DEFI_STATE_DIR/reports/lp-oor-watch-<id>.json e sai.

Gate: sem --execute é só alerta (status WOULD_EXIT, nada assinado). Com --execute, roda lp_exit.py com
DRY_RUN=0 --execute — use só se a sua regra permitir saída OOR automática (ver RULES.md).
Expira em --days dias (status EXPIRED).

Uso:
  python lp_oor_watch.py --token-id 123456                 # alerta
  python lp_oor_watch.py --token-id 123456 --execute       # saída automática (live)
"""
import argparse, json, math, os, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from web3 import Web3

HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("DEFI_STATE_DIR") or HERE / "state")
RPCS = [u for u in (os.environ.get("RPC_ARBITRUM"), "https://arb1.arbitrum.io/rpc", "https://arbitrum-one-rpc.publicnode.com") if u]
NPM = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"  # Uniswap v3 NonfungiblePositionManager (Arbitrum, público)
POOL = os.environ.get("LP_POOL_ADDRESS", "0xC6962004f452bE9203591991D15f6b388e09E8D0")  # WETH/USDC 0.05% Arb
npm_abi = [{"name": "positions", "type": "function", "stateMutability": "view", "inputs": [{"name": "t", "type": "uint256"}],
            "outputs": [{"type": "uint96"}, {"type": "address"}, {"type": "address"}, {"type": "address"}, {"type": "uint24"},
                        {"type": "int24"}, {"type": "int24"}, {"type": "uint128"}, {"type": "uint256"}, {"type": "uint256"},
                        {"type": "uint128"}, {"type": "uint128"}]}]
pool_abi = [{"name": "slot0", "type": "function", "stateMutability": "view", "inputs": [],
             "outputs": [{"type": "uint160"}, {"type": "int24"}, {"type": "uint16"}, {"type": "uint16"}, {"type": "uint16"},
                         {"type": "uint8"}, {"type": "bool"}]}]
Q96 = 2 ** 96

def w3c():
    for r in RPCS:
        try:
            w = Web3(Web3.HTTPProvider(r, request_kwargs={"timeout": 15}))
            if w.is_connected():
                return w
        except Exception:
            pass
    return None

def read(tid):
    w = w3c()
    if not w:
        return None
    p = w.eth.contract(address=NPM, abi=npm_abi).functions.positions(tid).call()
    s = w.eth.contract(address=Web3.to_checksum_address(POOL), abi=pool_abi).functions.slot0().call()
    return dict(tl=p[5], tu=p[6], L=p[7], sp=s[0], tick=s[1])

def amounts(d):
    sa = math.sqrt(1.0001 ** d["tl"]) * Q96; sb = math.sqrt(1.0001 ** d["tu"]) * Q96; sp = d["sp"]; L = d["L"]
    if sp <= sa:
        return int(L * (sb - sa) * Q96 / (sa * sb)), 0
    if sp >= sb:
        return 0, int(L * (sb - sa) / Q96)
    return int(L * (sb - sp) * Q96 / (sp * sb)), int(L * (sp - sa) / Q96)

def oor(d):
    return d["tick"] < d["tl"] or d["tick"] >= d["tu"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-id", type=int, required=True)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--streak", type=int, default=2, help="leituras seguidas fora da faixa antes de agir")
    ap.add_argument("--min-pct", type=float, default=98.0, help="amount mins = X%% do esperado")
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--execute", action="store_true", help="executa lp_exit.py live (senão só alerta)")
    a = ap.parse_args()
    out = STATE_DIR / "reports" / f"lp-oor-watch-{a.token_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write = lambda o: out.write_text(json.dumps(o, indent=2, default=str))
    deadline = datetime.now() + timedelta(days=a.days)
    streak, last = 0, None
    while datetime.now() < deadline:
        try:
            d = read(a.token_id)
        except Exception as e:
            d, last = None, str(e)
        if d:
            if d["L"] == 0:
                write({"status": "ALREADY_EMPTY", "at": datetime.now()}); print("liq=0, sai"); return 0
            streak = streak + 1 if oor(d) else 0
            if streak >= a.streak:
                a0, a1 = amounts(d); m0, m1 = int(a0 * a.min_pct / 100), int(a1 * a.min_pct / 100)
                base = {"at": datetime.now(), "tick": d["tick"], "tl": d["tl"], "tu": d["tu"],
                        "expected_amount0_raw": a0, "expected_amount1_raw": a1, "min0": m0, "min1": m1}
                if not a.execute:
                    write({"status": "WOULD_EXIT", **base}); print("fora da faixa (alerta; nada assinado)"); return 0
                env = dict(os.environ, DRY_RUN="0")
                r = subprocess.run([sys.executable, "lp_exit.py", "--chain", "arbitrum", "--token-id", str(a.token_id),
                                    "--amount0-min", str(m0), "--amount1-min", str(m1), "--execute"],
                                   cwd=str(HERE), env=env, capture_output=True, text=True, timeout=300)
                write({"status": "EXIT_EXECUTED" if r.returncode == 0 else "EXIT_FAILED", **base, "rc": r.returncode,
                       "stdout": r.stdout[-3000:], "stderr": r.stderr[-2000:]})
                print("done rc", r.returncode); return r.returncode
        time.sleep(a.interval)
    write({"status": "EXPIRED", "at": datetime.now(), "last_err": last}); print("expirou"); return 0

if __name__ == "__main__":
    sys.exit(main())
