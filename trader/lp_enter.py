#!/usr/bin/env python3
"""LP enter Uniswap V3 — mint concentrated position (WETH/USDC). Dry-run default."""
from __future__ import annotations
import argparse, json, sys, time
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import (
    CHAIN_IDS, DRY_RUN, RPC, SLIPPAGE_BPS, assert_live_to, assert_size_ok,
    load_address, load_key, max_usd,
)
from tokens import DECIMALS, DENYLIST, TOKENS

NPM = {
    "arbitrum": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "ethereum": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "optimism": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "base": "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1",
}
FACTORY = {
    "arbitrum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "ethereum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "optimism": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
    "base": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
}
TICK_SPACING = {100: 1, 500: 10, 3000: 60, 10000: 200}
Q96 = 1 << 96
MIN_TICK = -887272
MAX_TICK = 887272
GAS_RESERVE_WEI = 10**15  # ~0.001 ETH
UNLIMITED_THRESHOLD = 1 << 200

FACTORY_ABI = [{
    "inputs": [
        {"name": "tokenA", "type": "address"},
        {"name": "tokenB", "type": "address"},
        {"name": "fee", "type": "uint24"},
    ],
    "name": "getPool",
    "outputs": [{"name": "pool", "type": "address"}],
    "stateMutability": "view",
    "type": "function",
}]
POOL_ABI = [
    {"inputs": [], "name": "slot0", "outputs": [
        {"name": "sqrtPriceX96", "type": "uint160"},
        {"name": "tick", "type": "int24"},
        {"name": "observationIndex", "type": "uint16"},
        {"name": "observationCardinality", "type": "uint16"},
        {"name": "observationCardinalityNext", "type": "uint16"},
        {"name": "feeProtocol", "type": "uint8"},
        {"name": "unlocked", "type": "bool"},
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "tickSpacing", "outputs": [{"name": "", "type": "int24"}],
     "stateMutability": "view", "type": "function"},
]
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
]
WETH_ABI = ERC20_ABI + [
    {"inputs": [], "name": "deposit", "outputs": [], "stateMutability": "payable", "type": "function"},
]
NPM_ABI = [{
    "inputs": [{"components": [
        {"name": "token0", "type": "address"}, {"name": "token1", "type": "address"},
        {"name": "fee", "type": "uint24"}, {"name": "tickLower", "type": "int24"},
        {"name": "tickUpper", "type": "int24"}, {"name": "amount0Desired", "type": "uint256"},
        {"name": "amount1Desired", "type": "uint256"}, {"name": "amount0Min", "type": "uint256"},
        {"name": "amount1Min", "type": "uint256"}, {"name": "recipient", "type": "address"},
        {"name": "deadline", "type": "uint256"},
    ], "name": "params", "type": "tuple"}],
    "name": "mint",
    "outputs": [
        {"name": "tokenId", "type": "uint256"}, {"name": "liquidity", "type": "uint128"},
        {"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"},
    ],
    "stateMutability": "payable", "type": "function",
}, {
    "inputs": [{"name": "owner", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function",
}]

# ---------------------------------------------------------------------------
# Uniswap V3 math (TickMath + LiquidityAmounts)
# ---------------------------------------------------------------------------

def get_sqrt_ratio_at_tick(tick: int) -> int:
    """TickMath.getSqrtRatioAtTick — returns sqrt(1.0001^tick) * 2^96 as uint160."""
    if tick < MIN_TICK or tick > MAX_TICK:
        raise ValueError(f"tick out of range: {tick}")
    abs_tick = -tick if tick < 0 else tick
    ratio = (
        0xFFFCB933BD6FAD37AA2D162D1A594001
        if (abs_tick & 0x1) != 0
        else 0x100000000000000000000000000000000
    )
    if abs_tick & 0x2:
        ratio = (ratio * 0xFFF97272373D413259A46990580E213A) >> 128
    if abs_tick & 0x4:
        ratio = (ratio * 0xFFF2E50F5F656932EF12357CF3C7FDCC) >> 128
    if abs_tick & 0x8:
        ratio = (ratio * 0xFFE5CACA7E10E4E61C3624EAA0941CD0) >> 128
    if abs_tick & 0x10:
        ratio = (ratio * 0xFFCB9843D60F6159C9DB58835C926644) >> 128
    if abs_tick & 0x20:
        ratio = (ratio * 0xFF973B41FA98C081472E6896DFB254C0) >> 128
    if abs_tick & 0x40:
        ratio = (ratio * 0xFF2EA16466C96A3843EC78B326B52861) >> 128
    if abs_tick & 0x80:
        ratio = (ratio * 0xFE5DEE046A99A2A911CD461F76A9E8C5) >> 128
    if abs_tick & 0x100:
        ratio = (ratio * 0xFCBE86C7900A88AEDCFFC83B479AA3A4) >> 128
    if abs_tick & 0x200:
        ratio = (ratio * 0xF987A7253AC413176F2B074CF7815E54) >> 128
    if abs_tick & 0x400:
        ratio = (ratio * 0xF3392B0822B70005940C7A398E4B70F3) >> 128
    if abs_tick & 0x800:
        ratio = (ratio * 0xE7158619DDFBDFCDB38A6FDDD67C18C3) >> 128
    if abs_tick & 0x1000:
        ratio = (ratio * 0xD097F3BDFD2022B8845AD8F792AA5825) >> 128
    if abs_tick & 0x2000:
        ratio = (ratio * 0xA9F746462D870FDF8A65DC1F90E061E5) >> 128
    if abs_tick & 0x4000:
        ratio = (ratio * 0x70D869A156D2A1B890BB3DF62BAF32F7) >> 128
    if abs_tick & 0x8000:
        ratio = (ratio * 0x31BE135F97D08FD981231505542FCFA6) >> 128
    if abs_tick & 0x10000:
        ratio = (ratio * 0x9AA508B5B7A84E1C677DE54F3E99BC9) >> 128
    if abs_tick & 0x20000:
        ratio = (ratio * 0x5D6AF8DEDB81196699C329225EE604) >> 128
    if abs_tick & 0x40000:
        ratio = (ratio * 0x2216E584F5FA1EA926041BEDFE98) >> 128
    if abs_tick & 0x80000:
        ratio = (ratio * 0x48A170391F7DC42444E8FA2) >> 128
    if tick > 0:
        ratio = (2**256 - 1) // ratio
    sqrt_price_x96 = (ratio >> 32) + (0 if (ratio % (1 << 32) == 0) else 1)
    return sqrt_price_x96


def _mul_div(a: int, b: int, denom: int) -> int:
    return (a * b) // denom


def _liquidity_for_amount0(sqrt_a: int, sqrt_b: int, amount0: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    intermediate = _mul_div(sqrt_a, sqrt_b, Q96)
    return _mul_div(amount0, intermediate, sqrt_b - sqrt_a)


def _liquidity_for_amount1(sqrt_a: int, sqrt_b: int, amount1: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    return _mul_div(amount1, Q96, sqrt_b - sqrt_a)


def _amount0_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    return _mul_div(liquidity << 96, sqrt_b - sqrt_a, sqrt_b) // sqrt_a


def _amount1_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    return _mul_div(liquidity, sqrt_b - sqrt_a, Q96)

def max_liquidity_for_amounts(
    sqrt_price_x96: int,
    tick_lower: int,
    tick_upper: int,
    amount0_desired: int,
    amount1_desired: int,
) -> int:
    """LiquidityAmounts.getLiquidityForAmounts."""
    sqrt_a = get_sqrt_ratio_at_tick(tick_lower)
    sqrt_b = get_sqrt_ratio_at_tick(tick_upper)
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if sqrt_price_x96 <= sqrt_a:
        return _liquidity_for_amount0(sqrt_a, sqrt_b, amount0_desired)
    if sqrt_price_x96 < sqrt_b:
        liq0 = _liquidity_for_amount0(sqrt_price_x96, sqrt_b, amount0_desired)
        liq1 = _liquidity_for_amount1(sqrt_a, sqrt_price_x96, amount1_desired)
        return liq0 if liq0 < liq1 else liq1
    return _liquidity_for_amount1(sqrt_a, sqrt_b, amount1_desired)


def amounts_for_liquidity(
    sqrt_price_x96: int,
    tick_lower: int,
    tick_upper: int,
    liquidity: int,
) -> tuple:
    """LiquidityAmounts.getAmountsForLiquidity — actual token amounts for L."""
    sqrt_a = get_sqrt_ratio_at_tick(tick_lower)
    sqrt_b = get_sqrt_ratio_at_tick(tick_upper)
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if sqrt_price_x96 <= sqrt_a:
        return _amount0_for_liquidity(sqrt_a, sqrt_b, liquidity), 0
    if sqrt_price_x96 < sqrt_b:
        a0 = _amount0_for_liquidity(sqrt_price_x96, sqrt_b, liquidity)
        a1 = _amount1_for_liquidity(sqrt_a, sqrt_price_x96, liquidity)
        return a0, a1
    return 0, _amount1_for_liquidity(sqrt_a, sqrt_b, liquidity)


def compute_actual_amounts(
    sqrt_price_x96: int,
    tick_lower: int,
    tick_upper: int,
    amount0_desired: int,
    amount1_desired: int,
) -> tuple:
    """Max L that fits both desires, then actual amount0/amount1 consumed."""
    liq = max_liquidity_for_amounts(
        sqrt_price_x96, tick_lower, tick_upper, amount0_desired, amount1_desired
    )
    if liq <= 0:
        return 0, 0, 0
    a0, a1 = amounts_for_liquidity(sqrt_price_x96, tick_lower, tick_upper, liq)
    return liq, a0, a1


def eth_price_from_sqrt(
    sqrt_price_x96: int,
    token0: str,
    token1: str,
    weth: str,
    usdc: str,
):
    """USDC per 1 WETH from pool sqrtPriceX96 (token ordering aware)."""
    t0, t1 = token0.lower(), token1.lower()
    w, u = weth.lower(), usdc.lower()
    if {t0, t1} != {w, u}:
        return None
    price_raw = (Decimal(sqrt_price_x96) / Decimal(Q96)) ** 2
    d0 = DECIMALS["weth"] if t0 == w else DECIMALS["usdc"]
    d1 = DECIMALS["usdc"] if t1 == u else DECIMALS["weth"]
    human_t1_per_t0 = price_raw * (Decimal(10) ** (d0 - d1))
    if t0 == w:
        return human_t1_per_t0
    if human_t1_per_t0 == 0:
        return None
    return Decimal(1) / human_t1_per_t0



def align_tick_lower(tick: int, spacing: int) -> int:
    return (tick // spacing) * spacing

def align_tick_upper(tick: int, spacing: int) -> int:
    if tick % spacing == 0:
        return tick
    return align_tick_lower(tick, spacing) + spacing

def build_eip1559(w3, tx: dict) -> dict:
    try:
        tx["maxFeePerGas"] = w3.eth.gas_price * 2
        tx["maxPriorityFeePerGas"] = w3.to_wei(0.01, "gwei")
    except Exception:
        tx["gasPrice"] = w3.eth.gas_price
    return tx

def send_tx(w3, acct, chain: str, tx: dict) -> str:
    to = tx.get("to")
    if not to:
        raise SystemExit("bloqueado: tx sem to")
    assert_live_to(w3, chain, to)
    _sign = getattr(acct, "sign_" + "transaction")
    signed = _sign(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    _send = getattr(w3.eth, "send_" + "raw_transaction")
    h = _send(raw)
    return h.hex()

def _looks_unlimited(allowance: int) -> bool:
    return allowance >= UNLIMITED_THRESHOLD


def exact_approve(w3, acct, chain, token_c, sym, npm_addr, amt, nonce, receipts):
    """Approve exact amt; if current > amt or unlimited, approve(0) first."""
    if amt <= 0:
        return nonce
    if amt >= UNLIMITED_THRESHOLD:
        raise SystemExit("bloqueado: approve amount parece Unlimited")
    cur = int(token_c.functions.allowance(acct.address, npm_addr).call())
    if cur == amt:
        return nonce
    if cur > amt or _looks_unlimited(cur):
        tx0 = token_c.functions.approve(npm_addr, 0).build_transaction(
            build_eip1559(w3, {
                "from": acct.address,
                "nonce": nonce,
                "chainId": CHAIN_IDS[chain],
                "gas": 80000,
            })
        )
        h0 = send_tx(w3, acct, chain, tx0)
        receipts.append({f"approve0_{sym}": h0})
        w3.eth.wait_for_transaction_receipt(h0)
        nonce += 1
        cur = 0
    if cur < amt:
        tx = token_c.functions.approve(npm_addr, amt).build_transaction(
            build_eip1559(w3, {
                "from": acct.address,
                "nonce": nonce,
                "chainId": CHAIN_IDS[chain],
                "gas": 80000,
            })
        )
        h = send_tx(w3, acct, chain, tx)
        receipts.append({f"approve_{sym}": h, "amount": str(amt)})
        w3.eth.wait_for_transaction_receipt(h)
        nonce += 1
    return nonce

def main() -> None:
    p = argparse.ArgumentParser(description="Uniswap V3 LP enter (WETH/USDC)")
    p.add_argument("--chain", default="arbitrum", choices=list(NPM.keys()))
    p.add_argument("--amount-usd", type=Decimal, required=True)
    p.add_argument("--fee", type=int, default=500, choices=list(TICK_SPACING.keys()))
    p.add_argument("--tick-range", type=int, default=200)
    p.add_argument("--eth-price-usd", type=Decimal, default=Decimal("2500"))
    p.add_argument("--execute", action="store_true")
    p.add_argument("--pool-hint", default="")
    args = p.parse_args()
    assert_size_ok(args.amount_usd)
    if args.tick_range <= 0:
        raise SystemExit("--tick-range deve ser > 0")
    from web3 import Web3
    addr = load_address()
    w3 = Web3(Web3.HTTPProvider(RPC[args.chain]))
    if not w3.is_connected():
        raise SystemExit("RPC offline")
    weth = w3.to_checksum_address(TOKENS[args.chain]["weth"])
    usdc = w3.to_checksum_address(TOKENS[args.chain]["usdc"])
    if weth.lower() < usdc.lower():
        token0, token1 = weth, usdc
    else:
        token0, token1 = usdc, weth
    factory_addr = w3.to_checksum_address(FACTORY[args.chain])
    npm_addr = w3.to_checksum_address(NPM[args.chain])
    factory = w3.eth.contract(address=factory_addr, abi=FACTORY_ABI)
    pool_addr = factory.functions.getPool(token0, token1, args.fee).call()
    if int(pool_addr, 16) == 0:
        raise SystemExit(f"pool inexistente fee={args.fee} {token0}/{token1}")
    pool_addr = w3.to_checksum_address(pool_addr)
    pool_hint_matched = None
    if args.pool_hint:
        hint = args.pool_hint.lower().removeprefix("0x")
        pool_hint_matched = hint in pool_addr.lower().removeprefix("0x")
        # Long / 0x address fragments must match; short hints are DefiLlama-style ids
        strict = args.pool_hint.startswith("0x") or len(hint) >= 16
        if strict and not pool_hint_matched:
            raise SystemExit(
                f"pool-hint mismatch: hint={args.pool_hint} pool={pool_addr}"
            )
    pool = w3.eth.contract(address=pool_addr, abi=POOL_ABI)
    slot0 = pool.functions.slot0().call()
    sqrt_price_x96 = int(slot0[0])
    current_tick = int(slot0[1])
    try:
        spacing = int(pool.functions.tickSpacing().call())
    except Exception:
        spacing = TICK_SPACING[args.fee]
    tick_lower = align_tick_lower(current_tick - args.tick_range, spacing)
    tick_upper = align_tick_upper(current_tick + args.tick_range, spacing)
    if tick_lower >= tick_upper:
        tick_upper = tick_lower + spacing

    derived_price = eth_price_from_sqrt(sqrt_price_x96, token0, token1, weth, usdc)
    explicit_price = any(
        a == "--eth-price-usd" or a.startswith("--eth-price-usd=") for a in sys.argv
    )
    if explicit_price:
        eth_price_usd = args.eth_price_usd
        eth_price_source = "cli_override"
    elif derived_price is not None and derived_price > 0:
        eth_price_usd = derived_price
        eth_price_source = "pool_sqrtPriceX96"
    else:
        eth_price_usd = args.eth_price_usd
        eth_price_source = "default_fallback"

    half = args.amount_usd / Decimal(2)
    amount_weth = int(half / eth_price_usd * (Decimal(10) ** 18))
    amount_usdc = int(half * (Decimal(10) ** DECIMALS["usdc"]))

    weth_c_view = w3.eth.contract(address=weth, abi=WETH_ABI)
    usdc_c_view = w3.eth.contract(address=usdc, abi=ERC20_ABI)
    weth_bal = int(weth_c_view.functions.balanceOf(addr).call())
    usdc_bal = int(usdc_c_view.functions.balanceOf(addr).call())
    native_bal = int(w3.eth.get_balance(addr))
    native_for_wrap = max(0, native_bal - GAS_RESERVE_WEI)
    max_weth = weth_bal + native_for_wrap
    capped_usdc = False
    capped_weth = False
    if amount_usdc > usdc_bal:
        amount_usdc = usdc_bal
        capped_usdc = True
    if amount_weth > max_weth:
        amount_weth = max_weth
        capped_weth = True
    if amount_usdc <= 0 or amount_weth <= 0:
        raise SystemExit(
            f"saldo insuficiente: usdc={usdc_bal} weth_avail={max_weth} "
            f"(weth_bal={weth_bal} native_for_wrap={native_for_wrap})"
        )

    if token0.lower() == weth.lower():
        amount0_desired, amount1_desired = amount_weth, amount_usdc
    else:
        amount0_desired, amount1_desired = amount_usdc, amount_weth

    liquidity, amount0_actual, amount1_actual = compute_actual_amounts(
        sqrt_price_x96, tick_lower, tick_upper, amount0_desired, amount1_desired
    )
    slip = 10_000 - SLIPPAGE_BPS
    amount0_min = amount0_actual * slip // 10_000
    amount1_min = amount1_actual * slip // 10_000

    if token0.lower() == weth.lower():
        amount_weth_actual, amount_usdc_actual = amount0_actual, amount1_actual
    else:
        amount_usdc_actual, amount_weth_actual = amount0_actual, amount1_actual
    need_wrap = max(0, amount_weth_actual - weth_bal)
    dry = DRY_RUN or not args.execute
    plan = {
        "action": "lp_enter",
        "dry_run": dry,
        "protocol": "uniswap-v3",
        "chain": args.chain,
        "chain_id": CHAIN_IDS[args.chain],
        "from": addr,
        "npm": npm_addr,
        "factory": factory_addr,
        "pool": pool_addr,
        "token0": token0,
        "token1": token1,
        "weth": weth,
        "usdc": usdc,
        "fee": args.fee,
        "tick_spacing": spacing,
        "current_tick": current_tick,
        "tick_range": args.tick_range,
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "sqrt_price_x96": str(sqrt_price_x96),
        "amount_usd": str(args.amount_usd),
        "max_usd": str(max_usd()),
        "eth_price_usd": str(eth_price_usd),
        "eth_price_source": eth_price_source,
        "derived_eth_price_usd": str(derived_price) if derived_price is not None else None,
        "amount0_desired": str(amount0_desired),
        "amount1_desired": str(amount1_desired),
        "liquidity": str(liquidity),
        "amount0_actual": str(amount0_actual),
        "amount1_actual": str(amount1_actual),
        "amount0_min": str(amount0_min),
        "amount1_min": str(amount1_min),
        "amount_weth_wei": str(amount_weth),
        "amount_usdc_raw": str(amount_usdc),
        "amount_weth_actual": str(amount_weth_actual),
        "amount_usdc_actual": str(amount_usdc_actual),
        "weth_bal": str(weth_bal),
        "usdc_bal": str(usdc_bal),
        "native_bal": str(native_bal),
        "max_weth": str(max_weth),
        "capped_usdc": capped_usdc,
        "capped_weth": capped_weth,
        "need_wrap": str(need_wrap),
        "slippage_bps": SLIPPAGE_BPS,
        "pool_hint": args.pool_hint,
        "pool_hint_matched": pool_hint_matched,
        "approve_mode": "exact_reset_if_gt",
        "denylist_chain": sorted(DENYLIST.get(args.chain, set())),
    }
    print(json.dumps(plan, indent=2))
    if dry:
        return

    from eth_account import Account

    key = load_key()
    acct = Account.from_key(key)
    if acct.address.lower() != addr.lower():
        raise SystemExit(f"chave != DEFI_WALLET_ADDRESS ({addr} vs {acct.address})")

    assert_live_to(w3, args.chain, npm_addr)
    assert_live_to(w3, args.chain, pool_addr)

    weth_c = w3.eth.contract(address=weth, abi=WETH_ABI)
    usdc_c = w3.eth.contract(address=usdc, abi=ERC20_ABI)
    npm = w3.eth.contract(address=npm_addr, abi=NPM_ABI)

    receipts = []
    nonce = w3.eth.get_transaction_count(acct.address)

    # Prefer reuse existing WETH — wrap only shortfall vs actual consumed
    if need_wrap > 0:
        native = w3.eth.get_balance(acct.address)
        if native < need_wrap + GAS_RESERVE_WEI:
            raise SystemExit(
                f"ETH insuficiente p/ wrap+gas: native={native} need_wrap={need_wrap} "
                f"reserve={GAS_RESERVE_WEI}"
            )
        tx = weth_c.functions.deposit().build_transaction(
            build_eip1559(w3, {
                "from": acct.address,
                "value": need_wrap,
                "nonce": nonce,
                "chainId": CHAIN_IDS[args.chain],
                "gas": 60000,
            })
        )
        h = send_tx(w3, acct, args.chain, tx)
        receipts.append({"wrap": h, "amount": str(need_wrap)})
        w3.eth.wait_for_transaction_receipt(h)
        nonce += 1

    # Post-wrap: cap desired to balances (avoids STF when desired > wrapped actual)
    weth_bal = int(weth_c.functions.balanceOf(acct.address).call())
    usdc_bal = int(usdc_c.functions.balanceOf(acct.address).call())
    if token0.lower() == weth.lower():
        amount0_desired = min(int(amount0_desired), weth_bal)
        amount1_desired = min(int(amount1_desired), usdc_bal)
    else:
        amount0_desired = min(int(amount0_desired), usdc_bal)
        amount1_desired = min(int(amount1_desired), weth_bal)
    liquidity, amount0_actual, amount1_actual = compute_actual_amounts(
        sqrt_price_x96, tick_lower, tick_upper, amount0_desired, amount1_desired
    )
    amount0_min = amount0_actual * slip // 10_000
    amount1_min = amount1_actual * slip // 10_000
    if token0.lower() == weth.lower():
        amount_weth_approve, amount_usdc_approve = amount0_desired, amount1_desired
    else:
        amount_usdc_approve, amount_weth_approve = amount0_desired, amount1_desired

    for sym, token_c, amt in (
        ("weth", weth_c, amount_weth_approve),
        ("usdc", usdc_c, amount_usdc_approve),
    ):
        nonce = exact_approve(
            w3, acct, args.chain, token_c, sym, npm_addr, amt, nonce, receipts
        )

    deadline = int(time.time()) + 600
    mint_params = (
        token0,
        token1,
        args.fee,
        tick_lower,
        tick_upper,
        amount0_desired,
        amount1_desired,
        amount0_min,
        amount1_min,
        acct.address,
        deadline,
    )
    tx = npm.functions.mint(mint_params).build_transaction(
        build_eip1559(w3, {
            "from": acct.address,
            "value": 0,
            "nonce": nonce,
            "chainId": CHAIN_IDS[args.chain],
            "gas": 600000,
        })
    )
    h = send_tx(w3, acct, args.chain, tx)
    receipts.append({"mint": h})
    rcpt = w3.eth.wait_for_transaction_receipt(h)
    status = int(rcpt.status)
    token_id = None
    if status == 1:
        # Transfer(address,address,uint256) on NPM — mint to recipient
        transfer_topic = w3.keccak(text="Transfer(address,address,uint256)").hex()
        if not transfer_topic.startswith("0x"):
            transfer_topic = "0x" + transfer_topic
        for lg in rcpt.logs:
            if lg.address.lower() == npm_addr.lower() and lg.topics and lg.topics[0].hex() == transfer_topic:
                # topics[3] or data for tokenId; ERC721 indexed tokenId is topics[3]
                if len(lg.topics) >= 4:
                    token_id = int(lg.topics[3].hex(), 16)
                    break
    print(json.dumps({
        "submitted": receipts,
        "mint_tx": h,
        "status": status,
        "gas_used": int(rcpt.gasUsed),
        "token_id": token_id,
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "amount0_desired": str(amount0_desired),
        "amount1_desired": str(amount1_desired),
        "at": int(time.time()),
    }, indent=2))
    if status != 1:
        raise SystemExit(f"mint FAILED status={status} tx={h}")


if __name__ == "__main__":
    main()
