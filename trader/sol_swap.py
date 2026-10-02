#!/usr/bin/env python3
"""Solana swap via Jupiter (quote + optional swap tx).

Hard rules:
- Default DRY_RUN=1; live only with DRY_RUN=0 --execute
- Caps: lib_caps.max_usd (teto MAX_POSITION_USD); never spend available SOL minus rent reserve
- Private key ONLY from SOLANA_PRIVATE_KEY / DEFI_SOLANA_PRIVATE_KEY / SECRETS_FILE (opcional)
  — never print the key
- Before send: refuse unknown program IDs (Jupiter / Token / ATA / System / ComputeBudget)

Endpoints (public, no key required at keyless rate):
  Prefer https://lite-api.jup.ag/swap/v1  (fallback api.jup.ag)
  Legacy quote-api.jup.ag/v6 is tried if JUPITER_BASE is set.

Uso dry-run:
  python trader/sol_swap.py \\
    --input-mint SOL --output-mint USDC --amount-usd 1

Live (not run by default): DRY_RUN=0 ... --execute
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import DRY_RUN, SECRETS, SLIPPAGE_BPS, assert_size_ok, max_usd  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DEFAULT_PUBKEY = os.environ.get("SOLANA_WALLET_ADDRESS", "")  # pubkey pública (env)
RENT_RESERVE_LAMPORTS = 5_000_000  # ~0.005 SOL leave for fees/rent
LAMPORTS_PER_SOL = 1_000_000_000
SOL_DECIMALS = 9
USDC_DECIMALS = 6

# Known program allowlist (top-level ix program IDs only)
PROGRAM_ALLOWLIST = frozenset({
    "11111111111111111111111111111111",  # System
    "ComputeBudget111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",  # Token-2022
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # ATA
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # Jupiter v6
    "jupoNjAxXgZ4rjzxzPMP4oxduvQsQtZzyknqvzYLrGM",  # Jupiter (alt / related)
})

MINT_ALIASES = {
    "sol": SOL_MINT,
    "wsol": SOL_MINT,
    "usdc": USDC_MINT,
}

DEFAULT_RPC = os.environ.get(
    "SOLANA_RPC_URL",
    os.environ.get("RPC_SOLANA", "https://api.mainnet-beta.solana.com"),
)

# Prefer working public hosts; quote-api.jup.ag often fails DNS from some nets
_JUPITER_BASES = [
    b.strip().rstrip("/")
    for b in os.environ.get(
        "JUPITER_BASE",
        "https://lite-api.jup.ag/swap/v1,https://api.jup.ag/swap/v1,"
        "https://quote-api.jup.ag/v6",
    ).split(",")
    if b.strip()
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_json(method: str, url: str, body: dict | None = None, timeout: int = 30) -> Any:
    data = None
    headers = {"Accept": "application/json", "User-Agent": "crypto-agents-kit/sol_swap"}
    api_key = os.environ.get("JUPITER_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")[:500]
        raise SystemExit(f"HTTP {e.code} {url}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"URL error {url}: {e}") from e


def _jupiter_get(path_qs: str) -> Any:
    """GET path on first reachable Jupiter base (path like /quote?... or quote?...)."""
    path = path_qs if path_qs.startswith("/") else "/" + path_qs
    errors: list[str] = []
    for base in _JUPITER_BASES:
        url = base + path
        try:
            return _http_json("GET", url)
        except SystemExit as e:
            errors.append(str(e))
            if "HTTP 4" in str(e) or "HTTP 5" in str(e):
                # try next base on client/server errors that might be path mismatch
                continue
            raise
        except RuntimeError as e:
            errors.append(str(e))
            continue
    raise SystemExit("Jupiter quote failed on all bases:\n  " + "\n  ".join(errors))


def _jupiter_post(path: str, body: dict) -> Any:
    path = path if path.startswith("/") else "/" + path
    errors: list[str] = []
    for base in _JUPITER_BASES:
        url = base + path
        try:
            return _http_json("POST", url, body=body)
        except SystemExit as e:
            errors.append(str(e))
            continue
        except RuntimeError as e:
            errors.append(str(e))
            continue
    raise SystemExit("Jupiter swap-build failed on all bases:\n  " + "\n  ".join(errors))


# ---------------------------------------------------------------------------
# Wallet / secrets (never print key material)
# ---------------------------------------------------------------------------

def resolve_mint(s: str) -> str:
    raw = s.strip()
    low = raw.lower()
    if low in MINT_ALIASES:
        return MINT_ALIASES[low]
    if len(raw) >= 32 and raw.isalnum():
        return raw
    raise SystemExit(f"mint desconhecido: {s}")


def load_solana_pubkey() -> str:
    pk = (
        os.environ.get("SOLANA_PUBKEY", "").strip()
        or os.environ.get("DEFI_SOLANA_PUBKEY", "").strip()
        or DEFAULT_PUBKEY
    )
    return pk


def _secret_from_box(names: tuple[str, ...]) -> str:
    """Secrets JSON local opcional (SECRETS_FILE)."""
    if not SECRETS.exists():
        return ""
    try:
        data = json.loads(SECRETS.read_text())
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    for n in names:
        if isinstance(data.get(n), str) and data[n].strip():
            return data[n].strip()
    for ns in ("card", "secrets"):
        store = data.get(ns)
        if not isinstance(store, dict):
            continue
        for name in names:
            entry = store.get(name)
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
            if isinstance(entry, dict):
                for cand in ("value", "secret", "data"):
                    v = entry.get(cand)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    return ""


def load_solana_private_key() -> str:
    """Return secret key string; NEVER log/print it."""
    names = ("SOLANA_PRIVATE_KEY", "DEFI_SOLANA_PRIVATE_KEY")
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return _secret_from_box(names)


def keypair_from_secret(secret: str):
    """Build solders Keypair from base58 secret or JSON byte array. Never echo secret."""
    from solders.keypair import Keypair

    s = secret.strip()
    if s.startswith("["):
        arr = json.loads(s)
        return Keypair.from_bytes(bytes(arr))
    # base58 64-byte secret key
    try:
        import base58
        raw = base58.b58decode(s)
    except Exception as e:
        raise SystemExit(f"chave Solana inválida (formato): {type(e).__name__}") from e
    if len(raw) == 64:
        return Keypair.from_bytes(raw)
    if len(raw) == 32:
        return Keypair.from_seed(raw)
    raise SystemExit(f"chave Solana: tamanho inesperado ({len(raw)} bytes)")


# ---------------------------------------------------------------------------
# Amount / price / balance
# ---------------------------------------------------------------------------

def fetch_sol_usd() -> Decimal:
    """USD price for native SOL via Jupiter price API."""
    urls = [
        f"https://api.jup.ag/price/v3?ids={SOL_MINT}",
        f"https://lite-api.jup.ag/price/v3?ids={SOL_MINT}",
    ]
    for url in urls:
        try:
            data = _http_json("GET", url)
            entry = (data or {}).get(SOL_MINT) or {}
            price = entry.get("usdPrice") or entry.get("price")
            if price is not None:
                return Decimal(str(price))
        except Exception:
            continue
    # last resort env override
    env_p = os.environ.get("SOL_USD", "").strip()
    if env_p:
        return Decimal(env_p)
    raise SystemExit("não consegui preço SOL/USD (Jupiter price + SOL_USD ausente)")


def usd_to_lamports(amount_usd: Decimal, sol_usd: Decimal) -> int:
    if sol_usd <= 0:
        raise SystemExit("preço SOL inválido")
    sol = amount_usd / sol_usd
    return int(sol * Decimal(LAMPORTS_PER_SOL))


def rpc_get_balance_lamports(pubkey: str) -> int | None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [pubkey],
    }
    try:
        data = _http_json("POST", DEFAULT_RPC, body=body, timeout=20)
        val = ((data or {}).get("result") or {}).get("value")
        return int(val) if val is not None else None
    except Exception:
        return None


def assert_sol_spend_ok(amount_lamports: int, balance: int | None) -> None:
    if amount_lamports <= 0:
        raise SystemExit("amount deve ser > 0 lamports")
    if balance is None:
        return  # soft skip if RPC down (still cap by USD)
    spendable = balance - RENT_RESERVE_LAMPORTS
    if spendable < 0:
        spendable = 0
    if amount_lamports > spendable:
        raise SystemExit(
            f"bloqueado: amount {amount_lamports} lamports > disponível "
            f"{spendable} (saldo {balance} − reserve {RENT_RESERVE_LAMPORTS})"
        )


# ---------------------------------------------------------------------------
# Jupiter quote / swap + program allowlist
# ---------------------------------------------------------------------------

def get_quote(
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int,
) -> dict:
    qs = urllib.parse.urlencode({
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount),
        "slippageBps": str(slippage_bps),
    })
    return _jupiter_get(f"/quote?{qs}")


def build_swap_tx(quote: dict, user_pubkey: str) -> dict:
    payload = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }
    return _jupiter_post("/swap", payload)


def extract_top_level_programs(swap_tx_b64: str) -> list[str]:
    from solders.transaction import VersionedTransaction

    raw = base64.b64decode(swap_tx_b64)
    vt = VersionedTransaction.from_bytes(raw)
    msg = vt.message
    keys = [str(k) for k in msg.account_keys]
    progs: list[str] = []
    seen: set[str] = set()
    for ix in msg.instructions:
        pid = keys[ix.program_id_index]
        if pid not in seen:
            seen.add(pid)
            progs.append(pid)
    return progs


def assert_programs_allowed(programs: list[str]) -> None:
    bad = [p for p in programs if p not in PROGRAM_ALLOWLIST]
    if bad:
        raise SystemExit(
            "bloqueado: program IDs fora da allowlist: " + ", ".join(bad)
        )


def route_summary(quote: dict) -> list[dict]:
    out = []
    for hop in quote.get("routePlan") or []:
        info = hop.get("swapInfo") or {}
        out.append({
            "label": info.get("label"),
            "ammKey": info.get("ammKey"),
            "inAmount": info.get("inAmount"),
            "outAmount": info.get("outAmount"),
            "percent": hop.get("percent"),
            "bps": hop.get("bps"),
        })
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Solana Jupiter swap (DRY_RUN default, teto lib_caps MAX_POSITION_USD)"
    )
    p.add_argument("--input-mint", default="SOL", help="mint ou alias SOL/USDC")
    p.add_argument("--output-mint", default="USDC", help="mint ou alias SOL/USDC")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--amount-usd", type=Decimal, help="tamanho em US$ (cap via lib_caps)")
    g.add_argument("--amount-lamports", type=int, help="tamanho em lamports do input mint")
    p.add_argument(
        "--slippage-bps",
        type=int,
        default=SLIPPAGE_BPS,
        help=f"slippage bps (default {SLIPPAGE_BPS})",
    )
    p.add_argument("--execute", action="store_true", help="enviar tx (exige DRY_RUN=0)")
    p.add_argument(
        "--pubkey",
        default="",
        help="wallet pubkey (default: env SOLANA_WALLET_ADDRESS)",
    )
    p.add_argument(
        "--skip-swap-build",
        action="store_true",
        help="só quote (não chama POST /swap) — útil se solders ausente",
    )
    args = p.parse_args()

    input_mint = resolve_mint(args.input_mint)
    output_mint = resolve_mint(args.output_mint)
    if input_mint == output_mint:
        raise SystemExit("input-mint == output-mint")

    pubkey = (args.pubkey or load_solana_pubkey()).strip()
    dry = DRY_RUN or not args.execute

    sol_usd = fetch_sol_usd()
    amount_usd: Decimal | None = None
    if args.amount_usd is not None:
        amount_usd = Decimal(args.amount_usd)
        assert_size_ok(amount_usd)
        if input_mint == SOL_MINT:
            amount_in = usd_to_lamports(amount_usd, sol_usd)
        elif input_mint == USDC_MINT:
            # USDC 6 decimals ≈ 1:1 USD
            amount_in = int(amount_usd * Decimal(10**USDC_DECIMALS))
        else:
            raise SystemExit(
                "para mints não-SOL/USDC use --amount-lamports (raw atomic units)"
            )
    else:
        amount_in = int(args.amount_lamports)
        if input_mint == SOL_MINT:
            amount_usd = (Decimal(amount_in) / Decimal(LAMPORTS_PER_SOL)) * sol_usd
        elif input_mint == USDC_MINT:
            amount_usd = Decimal(amount_in) / Decimal(10**USDC_DECIMALS)
        else:
            amount_usd = None
        if amount_usd is not None:
            assert_size_ok(amount_usd)

    balance = None
    if input_mint == SOL_MINT:
        balance = rpc_get_balance_lamports(pubkey)
        assert_sol_spend_ok(amount_in, balance)

    quote = get_quote(input_mint, output_mint, amount_in, args.slippage_bps)
    out_amount = quote.get("outAmount")
    price_impact = quote.get("priceImpactPct")

    plan: dict[str, Any] = {
        "dry_run": dry,
        "aggregator": "jupiter",
        "jupiter_bases": _JUPITER_BASES,
        "wallet": pubkey,
        "input_mint": input_mint,
        "output_mint": output_mint,
        "amount_in": str(amount_in),
        "amount_usd": str(amount_usd) if amount_usd is not None else None,
        "max_usd": str(max_usd()),
        "sol_usd": str(sol_usd),
        "slippage_bps": args.slippage_bps,
        "out_amount": str(out_amount) if out_amount is not None else None,
        "other_amount_threshold": quote.get("otherAmountThreshold"),
        "price_impact_pct": str(price_impact) if price_impact is not None else None,
        "route": route_summary(quote),
        "rent_reserve_lamports": RENT_RESERVE_LAMPORTS,
        "sol_balance_lamports": str(balance) if balance is not None else None,
        "program_allowlist": sorted(PROGRAM_ALLOWLIST),
        "programs": [],
        "programs_ok": None,
    }

    swap_resp = None
    if not args.skip_swap_build:
        try:
            swap_resp = build_swap_tx(quote, pubkey)
            tx_b64 = swap_resp.get("swapTransaction")
            if not tx_b64:
                raise SystemExit(f"swap sem swapTransaction: keys={list(swap_resp)}")
            programs = extract_top_level_programs(tx_b64)
            plan["programs"] = programs
            try:
                assert_programs_allowed(programs)
                plan["programs_ok"] = True
            except SystemExit as e:
                plan["programs_ok"] = False
                plan["programs_block"] = str(e)
                print(json.dumps(plan, indent=2))
                raise
            plan["last_valid_block_height"] = swap_resp.get("lastValidBlockHeight")
            plan["prioritization_fee_lamports"] = swap_resp.get("prioritizationFeeLamports")
            if swap_resp.get("simulationError"):
                plan["simulation_error"] = swap_resp.get("simulationError")
        except SystemExit:
            raise
        except Exception as e:
            plan["swap_build_error"] = f"{type(e).__name__}: {e}"
            # still print quote plan
            print(json.dumps(plan, indent=2))
            raise SystemExit(f"falha ao montar/inspecionar swap tx: {e}") from e

    print(json.dumps(plan, indent=2), flush=True)

    if dry:
        print("# dry-run: nenhuma tx enviada", file=sys.stderr, flush=True)
        return

    # Live path — requires key + allowlist already passed
    if plan.get("programs_ok") is not True:
        raise SystemExit("bloqueado: programs_ok != True")
    if swap_resp is None or not swap_resp.get("swapTransaction"):
        raise SystemExit("bloqueado: sem swapTransaction para live")

    secret = load_solana_private_key()
    if not secret:
        raise SystemExit(
            "SOLANA_PRIVATE_KEY / DEFI_SOLANA_PRIVATE_KEY ausente "
            "(env ou SECRETS_FILE) — necessário para --execute"
        )
    kp = keypair_from_secret(secret)
    if str(kp.pubkey()) != pubkey:
        raise SystemExit(
            f"chave ≠ pubkey esperada ({pubkey} vs {kp.pubkey()})"
        )

    # Re-check programs immediately before sign/send
    programs = extract_top_level_programs(swap_resp["swapTransaction"])
    assert_programs_allowed(programs)
    if input_mint == SOL_MINT:
        bal2 = rpc_get_balance_lamports(pubkey)
        assert_sol_spend_ok(amount_in, bal2)

    from solders.transaction import VersionedTransaction

    raw = base64.b64decode(swap_resp["swapTransaction"])
    vt = VersionedTransaction.from_bytes(raw)
    # solders: sign in place via Keypair
    signed = VersionedTransaction(vt.message, [kp])
    # solana 0.40+ venv may lack sync rpc.api; send via JSON-RPC
    signed_b64 = base64.b64encode(bytes(signed)).decode()
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [
            signed_b64,
            {
                "encoding": "base64",
                "skipPreflight": False,
                "preflightCommitment": "confirmed",
            },
        ],
    }
    data = _http_json("POST", DEFAULT_RPC, body=body, timeout=60)
    if not isinstance(data, dict):
        raise SystemExit(f"RPC sendTransaction resposta inválida: {data!r}")
    if data.get("error"):
        raise SystemExit(f"RPC sendTransaction error: {data['error']}")
    sig = data.get("result")
    print(json.dumps({"submitted": str(sig), "at": int(time.time())}, indent=2))


if __name__ == "__main__":
    main()
