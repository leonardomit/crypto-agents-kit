"""Caps e helpers — bankroll e teto por posição via env (default bankroll US$50, teto ~US$25)."""
from __future__ import annotations
import json
import os
from decimal import Decimal
from pathlib import Path

BANKROLL_USD = Decimal(os.environ.get("BANKROLL_USD", "50"))
MAX_POSITION_PCT = Decimal(os.environ.get("MAX_POSITION_PCT", "50"))
MAX_POSITION_USD = Decimal(os.environ.get("MAX_POSITION_USD", "25"))
SLIPPAGE_BPS = int(os.environ.get("SLIPPAGE_BPS", "100"))
DRY_RUN = os.environ.get("DRY_RUN", "1") not in ("0", "false", "False", "no")

CHAIN_IDS = {"ethereum": 1, "base": 8453, "arbitrum": 42161, "optimism": 10}
RPC = {
    "base": os.environ.get("RPC_BASE", "https://mainnet.base.org"),
    "ethereum": os.environ.get("RPC_ETHEREUM", "https://ethereum.publicnode.com"),
    "arbitrum": os.environ.get("RPC_ARBITRUM", "https://arb1.arbitrum.io/rpc"),
    "optimism": os.environ.get("RPC_OPTIMISM", "https://mainnet.optimism.io"),
}
STATE_DIR = Path((os.environ.get("DEFI_STATE_DIR") or Path(__file__).resolve().parent / "state"))
ADDR_FILE = STATE_DIR / "wallet.address"
# Opcional: arquivo JSON local de secrets (fora do git). Preferir env vars.
SECRETS = Path((os.environ.get("SECRETS_FILE") or str(STATE_DIR / "secrets.json")))

def max_usd() -> Decimal:
    by_pct = BANKROLL_USD * MAX_POSITION_PCT / Decimal(100)
    return min(by_pct, MAX_POSITION_USD)

def assert_size_ok(usd: Decimal) -> None:
    lim = max_usd()
    if usd <= 0:
        raise SystemExit("size deve ser > 0")
    if usd > lim:
        raise SystemExit(f"bloqueado: size US${usd} > teto US${lim}")

def _entry_from_store(data, name="DEFI_WALLET_PRIVATE_KEY"):
    """Secrets JSON: aceita {"<NAME>": "..."} ou {"secrets"|"card": {"<NAME>": ...}}."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get(name), str) and data[name].strip():
        return data[name].strip()
    for ns in ("card", "secrets"):
        entry = (data.get(ns) or {}).get(name)
        if entry is None:
            continue
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
        if isinstance(entry, dict):
            for cand in ("value", "secret", "data"):
                v = entry.get(cand)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None

def load_key() -> str:
    key = os.environ.get("DEFI_WALLET_PRIVATE_KEY", "").strip()
    if not key and SECRETS.exists():
        data = json.loads(SECRETS.read_text())
        key = (_entry_from_store(data) or "").strip()
    if not key:
        raise SystemExit("DEFI_WALLET_PRIVATE_KEY ausente")
    if not key.startswith("0x"):
        key = "0x" + key
    return key

def load_address() -> str:
    addr = os.environ.get("DEFI_WALLET_ADDRESS", "").strip()
    if not addr and ADDR_FILE.exists():
        addr = ADDR_FILE.read_text().strip()
    if not addr:
        raise SystemExit("DEFI_WALLET_ADDRESS ausente (rode validate-wallet.py)")
    return addr

def assert_live_to(w3, chain: str, to: str) -> None:
    """Hard rule: never send live tx to empty bytecode or denylisted targets."""
    from tokens import DENYLIST
    to_l = to.lower()
    denied = {a.lower() for a in DENYLIST.get(chain, set())}
    if to_l in denied:
        raise SystemExit(f"bloqueado: endereço denylist em {chain}: {to}")
    code = w3.eth.get_code(w3.to_checksum_address(to))
    if not code:
        raise SystemExit(f"bloqueado: eth_getCode vazio em {chain}: {to}")

