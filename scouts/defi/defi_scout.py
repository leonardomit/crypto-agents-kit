#!/usr/bin/env python3
"""DeFi Scout — HTTP only. Zero wallet, zero trade.

Emite stdout (o runtime entrega no Telegram/chat) só se houver 2–3 setups A/B acionáveis ≤ US$25
e o fingerprint mudou vs o último alerta. Sempre grava $DEFI_SCOUT_OUT_DIR/latest.md
(default: scouts/defi/out/).

Script COMPARTILHADO (desde 2026-10-02):
- job de agente "DeFi Scout" (ex.: Hermes cron `1,46 9-18 * * 1-5`, no_agent=true) roda este arquivo
  normalmente (alerta via stdout).
- crontab run-scout.sh (`0,45 9-17` + `0 18`, todo dia) roda com --no-alert:
  grava latest.md/history igual, mas NÃO toca state.json nem imprime o alerta (não "come" o alerta do job).
- Redes: Arbitrum, Base, OP Mainnet e BNB Chain (BSC) como redes de setup; Ethereum só benchmark
  (gás não compensa ≤US$25). Candidatos Base + BNB Chain (Aave v3 Base, Venus, Aerodrome, PancakeSwap)
  com TVL ≥ US$5M listados com a rede explícita.
"""
from __future__ import annotations

import hashlib
import json
import sys
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UA = "crypto-agents-kit-defi-scout/1.0"
CTX = ssl.create_default_context()
TZ = ZoneInfo("America/Sao_Paulo")
OUT_DIR = Path(__import__("os").environ.get("DEFI_SCOUT_OUT_DIR") or __import__("os").environ.get("SCOUT_OUT_DIR")
               or (Path(__file__).resolve().parent / "out"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
LATEST = OUT_DIR / "latest.md"
STATE = OUT_DIR / "state.json"
SIZE_USD = 25.0

NO_ALERT = "--no-alert" in sys.argv

CHAINS = {"Ethereum", "Base", "Arbitrum", "OP Mainnet", "BSC"}
# redes de setup (gás barato p/ ticket ≤US$25). BSC entrou em 2026-10-02. Ethereum = só benchmark.
L2 = {"Base", "Arbitrum", "OP Mainnet", "BSC"}
NET_LABEL = {"BSC": "BNB Chain", "OP Mainnet": "OP Mainnet", "Base": "Base", "Arbitrum": "Arbitrum", "Ethereum": "Ethereum"}

# Universo extra Base + BNB Chain (lending/LP blue-chip e estáveis), TVL >= US$5M
EXTRA_MIN_TVL = 5_000_000
EXTRA_PROJECTS = {
    "Base": {"aave-v3", "aerodrome-slipstream", "aerodrome-v1"},
    "BSC": {"venus-core-pool", "aave-v3", "pancakeswap-amm", "pancakeswap-amm-v3"},
}
STABLES = {"USDC", "USDT", "DAI", "USDE", "FDUSD", "USD1", "USDBC", "EURC", "GHO", "LUSD", "SUSDS", "USDS", "U"}
BLUECHIPS = {"WETH", "ETH", "CBETH", "WSTETH", "WEETH", "RETH", "WBTC", "CBBTC", "BTCB", "WBNB", "BNB", "SOLVBTC"}
BENCH_PROJECTS = {"aave-v3", "compound-v3", "spark-savings", "sky-lending", "morpho-blue", "fluid-lending", "uniswap-v3"}


def rede(chain: str | None) -> str:
    return NET_LABEL.get(chain or "", chain or "?")

A_PROJECTS = {
    "aave-v3",
    "compound-v3",
    "morpho-blue",
    "fluid-lending",
    "spark-savings",
    "sky-lending",
    "spark",
    "venus-core-pool",
}
B_PROJECTS = {
    "uniswap-v3",
    "aerodrome-slipstream",
    "aerodrome",
    "velodrome-v3",
    "velodrome-v2",
    "fluid-dex",
    "aerodrome-v1",
    "pancakeswap-amm",
    "pancakeswap-amm-v3",
}

# Morpho vault prefixes conhecidos (evitar SIRLOIN/BBQ/meme)
MORPHO_OK = (
    "USDC",
    "USDT",
    "EURC",
    "WETH",
    "ETH",
    "GHO",
    "STEAK",
    "GTUSDC",
    "SPARK",
    "GAUNTLET",
    "MOONWELL",
    "WELL",
)

UNI_V3 = {
    # chain -> (rpc, pool, label, fee_ppm)
    "Base": (
        "https://mainnet.base.org",
        "0xd0b53D9277642d899DF5C87A3966A349A798F224",
        "WETH/USDC 0.05%",
        500,
    ),
    "Arbitrum": (
        "https://arb1.arbitrum.io/rpc",
        "0xC6962004f452bE9203591991D15f6b388e09E8D0",
        "WETH/USDC 0.05%",
        500,
    ),
}

RPC_FALLBACK = {
    "Base": ["https://base.llamarpc.com", "https://mainnet.base.org"],
    "Arbitrum": ["https://arb1.arbitrum.io/rpc", "https://arbitrum.llamarpc.com"],
    "Ethereum": ["https://rpc.ankr.com/eth", "https://ethereum.publicnode.com"],
    "BSC": ["https://bsc-dataseed.bnbchain.org", "https://bsc.publicnode.com"],
}


def now_sp() -> datetime:
    return datetime.now(TZ)


def http_json(url: str, timeout: int = 45, data: bytes | None = None, headers: dict | None = None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode())


def safe_get(url: str, timeout: int = 45, default=None):
    try:
        return http_json(url, timeout=timeout)
    except Exception:
        return default


def rpc_call(urls: list[str], to: str, data: str) -> str | None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        }
    ).encode()
    for url in urls:
        try:
            out = http_json(
                url,
                timeout=12,
                data=body,
                headers={"Content-Type": "application/json"},
            )
            res = (out or {}).get("result")
            if res and res != "0x":
                return res
        except Exception:
            continue
    return None


def decode_int24_from_slot0(hexdata: str) -> tuple[int, int] | None:
    raw = hexdata[2:] if hexdata.startswith("0x") else hexdata
    b = bytes.fromhex(raw)
    if len(b) < 64:
        return None
    sqrt = int.from_bytes(b[0:32], "big")
    tick = int.from_bytes(b[32:64], "big")
    if tick >= 2**255:
        tick -= 2**256
    return sqrt, tick


def eth_price_from_weth_usdc_tick(tick: int, dec0: int = 18, dec1: int = 6) -> float:
    # token0=WETH, token1=USDC → USDC per WETH
    return (1.0001**tick) * (10 ** (dec0 - dec1))


def llama_link(pool_id: str) -> str:
    return f"https://defillama.com/yields/pool/{pool_id}"


def project_link(project: str, chain: str, symbol: str) -> str:
    c = chain.lower().replace("op mainnet", "optimism")
    if project == "aave-v3":
        market = {
            "ethereum": "proto_mainnet_v3",
            "base": "proto_base_v3",
            "arbitrum": "proto_arbitrum_v3",
            "optimism": "proto_optimism_v3",
            "bsc": "proto_bnb_v3",
        }.get(c, "")
        return f"https://app.aave.com/?marketName={market}" if market else "https://app.aave.com"
    if project == "morpho-blue":
        return "https://app.morpho.org"
    if project.startswith("fluid"):
        return "https://fluid.instadapp.io"
    if project.startswith("spark") or project == "sky-lending":
        return "https://app.spark.fi"
    if project == "compound-v3":
        return "https://app.compound.finance"
    if project == "uniswap-v3":
        return "https://app.uniswap.org/positions"
    if "aerodrome" in project:
        return "https://aerodrome.finance"
    if project.startswith("venus"):
        return "https://app.venus.io/#/core-pool"
    if project.startswith("pancakeswap"):
        return "https://pancakeswap.finance/liquidity/pools?chain=bsc"
    if "velodrome" in project:
        return "https://velodrome.finance"
    return llama_link("")


def morpho_ok(symbol: str) -> bool:
    s = (symbol or "").upper().replace("-", "").replace("_", "")
    if any(bad in s for bad in ("SIRLOIN", "BBQ", "CSCB", "PUSDC")):
        # pUSDC is a named vault — keep if Gauntlet-like; skip meme-ish
        if "SIRLOIN" in s or "BBQ" in s or "CSCB" in s:
            return False
    return any(tok in s for tok in MORPHO_OK)


def pred_down(p: dict, min_prob: int = 55) -> bool:
    pr = p.get("predictions") or {}
    cls = str(pr.get("predictedClass") or "").lower()
    prob = pr.get("predictedProbability") or 0
    if "down" not in cls:
        return False
    return True if min_prob <= 0 else prob >= min_prob


def chain_tvl_delta() -> dict[str, dict]:
    out = {}
    names = {"Ethereum": "Ethereum", "Base": "Base", "Arbitrum": "Arbitrum", "OP Mainnet": "Optimism", "BSC": "BSC"}
    for label, api_name in names.items():
        h = safe_get(f"https://api.llama.fi/v2/historicalChainTvl/{urllib.parse.quote(api_name)}", timeout=30)
        if not isinstance(h, list) or len(h) < 2:
            continue
        a, b = h[-2], h[-1]
        t0, t1 = a.get("tvl") or 0, b.get("tvl") or 0
        pct = ((t1 - t0) / t0 * 100) if t0 else 0
        out[label] = {"tvl": t1, "d1_pct": pct}
    return out


def coin_trend() -> dict:
    cg = safe_get(
        "https://api.coingecko.com/api/v3/simple/price?ids=ethereum,solana&vs_currencies=usd&include_24hr_change=true",
        timeout=20,
        default={},
    ) or {}
    def chart(coin: str):
        d = safe_get(f"https://coins.llama.fi/chart/coingecko:{coin}?span=8&period=1d", timeout=20) or {}
        prices = ((d.get("coins") or {}).get(f"coingecko:{coin}") or {}).get("prices") or []
        if len(prices) >= 2:
            p0 = prices[0]["price"]
            p1 = prices[-1]["price"]
            return p1, ((p1 - p0) / p0 * 100) if p0 else 0
        return None, None

    eth_px, eth_7d = chart("ethereum")
    sol_px, sol_7d = chart("solana")
    eth = cg.get("ethereum") or {}
    sol = cg.get("solana") or {}
    return {
        "eth": {
            "usd": eth.get("usd") or eth_px,
            "d1": eth.get("usd_24h_change"),
            "d7": eth_7d,
        },
        "sol": {
            "usd": sol.get("usd") or sol_px,
            "d1": sol.get("usd_24h_change"),
            "d7": sol_7d,
        },
    }


def uni_onchain() -> dict[str, dict]:
    out = {}
    for chain, (rpc, pool, label, _fee) in UNI_V3.items():
        urls = [rpc] + [u for u in RPC_FALLBACK.get(chain, []) if u != rpc]
        raw = rpc_call(urls, pool, "0x3850c7bd")
        if not raw:
            continue
        decoded = decode_int24_from_slot0(raw)
        if not decoded:
            continue
        sqrt, tick = decoded
        try:
            px = eth_price_from_weth_usdc_tick(tick)
        except Exception:
            px = None
        # ±1% in ticks ≈ ln(1.01)/ln(1.0001) ≈ 99.5 ticks
        out[chain] = {
            "pool": pool,
            "label": label,
            "tick": tick,
            "sqrtPriceX96": sqrt,
            "eth_usdc": round(px, 2) if px else None,
            "near_oor_note": (
                f"tick={tick}; LP ±1% (~100 ticks) fica near-OOR se ETH andar ~1%. "
                f"$25 concentrado é frágil — preferir full-range ou não LP."
            ),
            "url": f"https://app.uniswap.org/explore/pools/{chain.lower()}/{pool}",
        }
    return out


def pool_delta(pool_id: str) -> dict | None:
    d = safe_get(f"https://yields.llama.fi/chart/{pool_id}", timeout=20)
    rows = (d or {}).get("data") if isinstance(d, dict) else None
    if not rows or len(rows) < 2:
        return None
    a, b = rows[-2], rows[-1]
    t0, t1 = a.get("tvlUsd") or 0, b.get("tvlUsd") or 0
    return {
        "tvl_d1_pct": ((t1 - t0) / t0 * 100) if t0 else None,
        "apy_prev": a.get("apy"),
        "il7d": b.get("il7d"),
    }


def fmt_usd(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    if abs(n) >= 1e9:
        return f"${n/1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.1f}M"
    if abs(n) >= 1e3:
        return f"${n/1e3:.1f}k"
    return f"${n:.2f}"


def fmt_pct(n, digits=2) -> str:
    if n is None:
        return "—"
    return f"{float(n):+.{digits}f}%" if float(n) < 0 or True else f"{float(n):.{digits}f}%"


def monthly_usd(apy: float, size: float = SIZE_USD) -> float:
    return size * (apy / 100.0) / 12.0


def classify_a(p: dict) -> bool:
    if p.get("chain") not in L2:
        return False
    if p.get("project") not in A_PROJECTS:
        return False
    if p.get("outlier"):
        return False
    if pred_down(p):
        return False
    tvl = p.get("tvlUsd") or 0
    apy = p.get("apy") or 0
    if tvl < 10_000_000:
        return False
    if apy < 3.4 or apy > 12:
        return False
    if p.get("ilRisk") not in (None, "no"):
        return False
    if p.get("exposure") and p.get("exposure") != "single":
        return False
    if not p.get("stablecoin"):
        return False
    if p.get("project") == "morpho-blue" and not morpho_ok(p.get("symbol") or ""):
        return False
    # unlock / dated PT
    meta = (p.get("poolMeta") or "").lower()
    if any(x in meta for x in ("unlock", "pt-", "maturity", "clo")):
        return False
    return True


def classify_b(p: dict) -> bool:
    if p.get("chain") not in L2:
        return False
    if p.get("project") not in B_PROJECTS:
        return False
    if p.get("outlier"):
        return False
    if pred_down(p, min_prob=0):
        return False
    tvl = p.get("tvlUsd") or 0
    apy = p.get("apy") or 0
    vol = p.get("volumeUsd1d") or 0
    if tvl < 20_000_000:
        return False
    if apy < 8 or apy > 32:
        return False
    if vol < 5_000_000:
        return False
    sym = (p.get("symbol") or "").upper()
    # $25: só par com lado estável USDC/USDT — WBTC-WETH não
    if "USDC" not in sym and "USDT" not in sym:
        return False
    if any(x in sym for x in ("KBTC", "WEETH", "RSETH", "MEME", "WBTC")):
        return False
    return True


def score_a(p: dict) -> float:
    tvl = p.get("tvlUsd") or 1
    apy = p.get("apy") or 0
    known = 2.0 if p.get("project") in ("aave-v3", "fluid-lending", "compound-v3") else 1.0
    return known * apy * math.log10(tvl)


def score_b(p: dict) -> float:
    tvl = p.get("tvlUsd") or 1
    apy = p.get("apy") or 0
    vol = p.get("volumeUsd1d") or 1
    return apy * math.log10(tvl) * math.log10(max(vol, 10))


def setup_block(kind: str, p: dict, extra: dict | None, uni: dict, trend: dict) -> str:
    chain = p.get("chain")
    proj = p.get("project")
    sym = p.get("symbol")
    apy = p.get("apy") or 0
    tvl = p.get("tvlUsd") or 0
    vol = p.get("volumeUsd1d")
    dlt = extra or {}
    tvl_d1 = dlt.get("tvl_d1_pct")
    m = monthly_usd(apy)
    link = llama_link(p.get("pool") or "")
    app = project_link(proj, chain, sym)
    pred = (p.get("predictions") or {}).get("predictedClass") or "—"
    onch = ""
    if kind == "B" and chain in uni:
        u = uni[chain]
        onch = (
            f"\n- On-chain Uni v3 {u['label']}: tick {u['tick']}, ETH≈{u['eth_usdc']} USDC. "
            f"{u['near_oor_note']}\n- Pool: {u['url']}"
        )
    if kind == "A":
        tese = (
            f"Parking estável em {rede(chain)} para sobra de caixa de assinatura. "
            f"Yield mensal em US$25 ≈ US${m:.2f} — não cobre assinatura; só não deixar o pó parado."
        )
        size = f"US$15–25 na rede {rede(chain)} (Base/Arb/OP/BNB Chain; não usar mainnet — gas come o size)"
        tp = "Não há TP de preço. Sair se precisar do caixa ou se APY 30d < 2,5%."
        sl = "Sair se TVL do pool −15% em 1d, APY spot < 2%, ou pred Llama Down≥70%."
    else:
        tese = (
            f"LP fee-driven {sym} em {rede(chain)}. Volume 1d {fmt_usd(vol)} / TVL {fmt_usd(tvl)}. "
            f"$25 concentrado near-OOR fácil; se entrar, range largo. Mensal teorico US${m:.2f} antes de IL/gas."
        )
        size = f"US$20–25 máx na rede {rede(chain)} (só Base/Arb/OP/BNB Chain), range largo (não tick apertado)"
        tp = "Colher fees se cobrirem gas + 10%; não perseguir APY de 1d."
        sl = "Sair se IL7d < −2%, volume 1d < 20% da média, ou ETH −5% no dia com LP apertado."
        eth_d1 = (trend.get("eth") or {}).get("d1")
        if eth_d1 is not None and eth_d1 < -3:
            tese += " ETH 24h negativo — B fica ainda mais frágil."
    ind = (
        f"APY {apy:.2f}% (base {p.get('apyBase')}, reward {p.get('apyReward')}, mean30d {p.get('apyMean30d')}); "
        f"TVL {fmt_usd(tvl)} Δ1d {fmt_pct(tvl_d1) if tvl_d1 is not None else '—'}; "
        f"vol1d {fmt_usd(vol)}; IL risk {p.get('ilRisk')}; pred {pred}"
    )
    return (
        f"### Setup {kind} — {chain} / {proj} / {sym}\n"
        f"- Rede: {rede(chain)}\n"
        f"- Tese: {tese}\n"
        f"- Indicadores: {ind}\n"
        f"- Size sugerido: {size}\n"
        f"- TP: {tp}\n"
        f"- SL: {sl}\n"
        f"- Links: {app} | {link}"
        f"{onch}\n"
    )


def fingerprint(setups: list[dict]) -> str:
    parts = []
    for p in setups:
        apy = round(float(p.get("apy") or 0), 1)
        parts.append(f"{p.get('pool')}:{apy}")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE.write_text(json.dumps(st, indent=2))


def trend_line(trend: dict, chain_d: dict) -> str:
    eth, sol = trend.get("eth") or {}, trend.get("sol") or {}
    def g(x, k):
        v = x.get(k)
        return fmt_pct(v, 2) if v is not None else "—"
    bits = [
        f"ETH {fmt_usd(eth.get('usd'))} d1 {g(eth,'d1')} d7 {g(eth,'d7')}",
        f"SOL {fmt_usd(sol.get('usd'))} d1 {g(sol,'d1')} d7 {g(sol,'d7')}",
    ]
    for name in ("Ethereum", "Base", "Arbitrum", "OP Mainnet", "BSC"):
        if name in chain_d:
            bits.append(f"{rede(name)} TVL {fmt_usd(chain_d[name]['tvl'])} Δ1d {fmt_pct(chain_d[name]['d1_pct'])}")
    return "; ".join(bits)


def gross_bias(trend: dict) -> str:
    eth = trend.get("eth") or {}
    d1, d7 = eth.get("d1"), eth.get("d7")
    if d1 is None and d7 is None:
        return "indefinido"
    if (d7 or 0) >= 3 and (d1 or 0) >= -1:
        return "alta leve"
    if (d7 or 0) <= -5 or (d1 or 0) <= -4:
        return "baixa"
    return "lateral"


def _tokens(sym: str) -> list[str]:
    return [t for t in (sym or "").upper().replace("/", "-").split("-") if t]


def extra_ok(p: dict) -> bool:
    """Base/BNB Chain: lending single-asset ou LP só com blue-chips/estáveis, TVL ≥ US$5M."""
    chain = p.get("chain")
    if p.get("project") not in EXTRA_PROJECTS.get(chain, set()):
        return False
    if (p.get("tvlUsd") or 0) < EXTRA_MIN_TVL:
        return False
    toks = _tokens(p.get("symbol"))
    return bool(toks) and all(t in STABLES or t in BLUECHIPS for t in toks)


def extra_section(pools: list[dict], setup_ids: set) -> tuple[str, dict]:
    cands = [p for p in pools if extra_ok(p)]
    counts: dict = {}
    for p in cands:
        counts[(rede(p.get("chain")), p.get("project"))] = counts.get((rede(p.get("chain")), p.get("project")), 0) + 1
    cands.sort(key=lambda p: (p.get("chain"), -(p.get("tvlUsd") or 0)))
    lines = ["\n## Candidatos Base + BNB Chain (lending/LP blue-chip e estáveis, TVL ≥ US$5M)\n",
             "_Só vira setup A/B se passar os filtros acima (TVL ≥ US$10M A / ≥ US$20M B, APY útil, sem outlier/IL alto)._", "",
             "| Rede | Protocolo | Pool | Tipo | APY | APY base | TVL | Vol 1d | Obs |",
             "|---|---|---|---|---:|---:|---:|---:|---|"]
    for chain in ("Base", "BSC"):
        sub = [p for p in cands if p.get("chain") == chain][:10]
        if not sub:
            lines.append(f"| {rede(chain)} | — | nenhum pool ≥ US$5M nos protocolos-alvo | | | | | | |")
        for p in sub:
            tipo = "lending" if p.get("exposure") == "single" else "LP"
            obs = []
            if p.get("pool") in setup_ids: obs.append("**setup**")
            if p.get("outlier"): obs.append("APY outlier")
            if p.get("ilRisk") == "yes": obs.append("IL")
            if pred_down(p): obs.append("pred Down")
            if p.get("stablecoin"): obs.append("estável")
            lines.append(
                f"| {rede(chain)} | {p.get('project')} | {p.get('symbol')} | {tipo} | {float(p.get('apy') or 0):.2f}% | "
                f"{float(p.get('apyBase') or 0):.2f}% | {fmt_usd(p.get('tvlUsd'))} | {fmt_usd(p.get('volumeUsd1d'))} | "
                f"{', '.join(obs)} |")
    lines.append("")
    return "\n".join(lines), counts


def benchmark_section(pools: list[dict]) -> str:
    eth = [p for p in pools if p.get("chain") == "Ethereum" and p.get("project") in BENCH_PROJECTS
           and p.get("stablecoin") and p.get("exposure") == "single" and not p.get("outlier")
           and (p.get("tvlUsd") or 0) >= 100_000_000 and 0 < (p.get("apy") or 0) < 20]
    eth.sort(key=lambda p: -(p.get("tvlUsd") or 0))
    lines = ["\n## Benchmark Ethereum (gás não compensa ≤US$25)\n",
             "_Referência de taxa em mainnet — nunca é setup (gás de entrada/saída > yield de meses em US$25)._", "",
             "| Rede | Protocolo | Pool | APY | TVL |", "|---|---|---|---:|---:|"]
    for p in eth[:4]:
        lines.append(f"| Ethereum | {p.get('project')} | {p.get('symbol')} | {float(p.get('apy') or 0):.2f}% | {fmt_usd(p.get('tvlUsd'))} |")
    if not eth:
        lines.append("| Ethereum | — | sem dado | — | — |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = now_sp().strftime("%Y-%m-%d %H:%M %Z")
    pools_raw = safe_get("https://yields.llama.fi/pools", timeout=60)
    pools = (pools_raw or {}).get("data") if isinstance(pools_raw, dict) else None
    if not pools:
        LATEST.write_text(f"# DeFi Scout\n\n{ts}\n\nFalha ao puxar DefiLlama yields. Sem sinal.\n")
        return 0

    trend = coin_trend()
    chain_d = chain_tvl_delta()
    uni = uni_onchain()
    bias = gross_bias(trend)

    a_cands = [p for p in pools if classify_a(p)]
    b_cands = [p for p in pools if classify_b(p)]
    a_cands.sort(key=score_a, reverse=True)
    b_cands.sort(key=score_b, reverse=True)

    extras: dict = {}

    def reject_tvl_dump(p: dict) -> bool:
        pid = p.get("pool")
        if not pid:
            return False
        if pid not in extras:
            extras[pid] = pool_delta(pid)
        d = extras.get(pid) or {}
        pct = d.get("tvl_d1_pct")
        return pct is not None and pct <= -12

    a_cands = [p for p in a_cands[:12] if not reject_tvl_dump(p)]
    b_cands = [p for p in b_cands[:8] if not reject_tvl_dump(p)]

    def pick(cands, n):
        out = []
        for prefer_new_chain in (True, False):
            for p in cands:
                if p in out:
                    continue
                if p.get("project") in {x.get("project") for x in out}:
                    continue
                if prefer_new_chain and p.get("chain") in {x.get("chain") for x in out}:
                    continue
                out.append(p)
                if len(out) >= n:
                    return out
        return out

    # Se ETH em baixa, não oferecer B
    b_pick = [] if bias == "baixa" else pick(b_cands, 1)
    a_need = 2 if not b_pick else 1
    if not b_pick:
        a_need = 2
    a_pick = pick(a_cands, a_need)

    setups = a_pick + b_pick
    # 2–3 bons, senão silêncio
    if len(setups) < 2:
        setups = []

    kinds = (["A"] * len(a_pick)) + (["B"] * len(b_pick))
    body_setups = []
    for kind, p in zip(kinds, setups):
        body_setups.append(setup_block(kind, p, extras.get(p.get("pool")), uni, trend))

    hist_dir = OUT_DIR / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist_path = hist_dir / (now_sp().strftime("%Y-%m-%d-%H%M") + ".md")

    def persist(text: str) -> None:
        LATEST.write_text(text)
        hist_path.write_text(text)

    header = (
        f"# DeFi Scout\n\n"
        f"- Quando: {ts}\n"
        f"- Modo: HTTP/script, zero wallet/trade, size teto US${SIZE_USD:.0f}\n"
        f"- Tendência grossa: ETH {bias}. {trend_line(trend, chain_d)}\n"
    )
    if uni:
        ticks = "; ".join(
            f"{k} {v['label']} tick {v['tick']} ETH≈{v['eth_usdc']}" for k, v in uni.items()
        )
        header += f"- Uni v3 slot0: {ticks}\n"
    if setups:
        nomes = ", ".join(
            f"{k} {rede(p.get('chain'))} {p.get('project')} {p.get('symbol')} {float(p.get('apy') or 0):.2f}%"
            for k, p in zip(kinds, setups)
        )
        header += (
            f"\nResumo: {len(setups)} setup(s) ≤US$25 — {nomes}. "
            f"ETH {bias}; OP TVL Δ1d fraco. Mensal em US$25 é centavos — só pó de assinatura.\n"
        )

    setup_ids = {p.get("pool") for p in setups}
    extra_md, extra_counts = extra_section(pools, setup_ids)
    bench_md = benchmark_section(pools)
    header += (
        "- Redes de setup: Arbitrum, Base, OP Mainnet, BNB Chain | Ethereum só benchmark | "
        f"candidatos Base+BNB ≥US$5M: "
        + (", ".join(f"{k[0]} {k[1]} {v}" for k, v in sorted(extra_counts.items())) or "0")
        + "\n"
    )
    if not setups:
        md = (
            header
            + "\n**sem sinal** — nenhum setup A/B ≤US$25 passou o filtro "
            "(TVL alto, APY útil, L2, protocolo conhecido, ΔTVL 1d > −12%).\n"
            f"Checado: DefiLlama yields {len(pools)} pools; redes Base/Arbitrum/OP Mainnet/BNB Chain (+ Ethereum benchmark); "
            f"A {len(a_cands)} / B {len(b_cands)} após filtro.\n"
            + extra_md + bench_md +
            "Próximo check: :00/:45 (todo dia, 9–18h) e :01/:46 (seg–sex) BRT.\n"
        )
        persist(md)
        return 0

    md = header + "\n" + "\n".join(body_setups)
    md += extra_md + bench_md
    md += (
        "\nFontes: https://yields.llama.fi/pools | https://api.llama.fi/v2/historicalChainTvl "
        "| coins.llama.fi | Uni v3 slot0 Base/Arb\n"
        "Próximo check: :00/:45 (todo dia, 9–18h) e :01/:46 (seg–sex) BRT.\n"
        "\n---\nNão é ordem de trade. Gas L2 deve ser << size. "
        "Yield em US$25 não cobre assinatura (caixa assinatura = só pó sobrando).\n"
    )
    persist(md)

    if NO_ALERT:
        return 0
    fp = fingerprint(setups)
    st = load_state()
    if st.get("fp") == fp:
        return 0
    save_state({"fp": fp, "ts": ts, "ids": [p.get("pool") for p in setups]})

    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
