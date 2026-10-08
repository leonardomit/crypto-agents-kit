#!/usr/bin/env python3
"""Builds + verifies chains.json (read-only). Each address: eth_getCode non-empty;
tokens: symbol/decimals on-chain; protocol cross-checks (getPool, factory(), WETH9(), aToken)."""
import json, sys, time
from pathlib import Path
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
sys.path.insert(0, str(Path(__file__).resolve().parent))

U_BASE = "https://docs.uniswap.org/contracts/v3/reference/deployments/base-deployments"
CIRCLE = "https://developers.circle.com/stablecoins/usdc-contract-addresses"
BASEDOCS = "https://docs.base.org/base-chain/network-information/base-contracts"
AERO = "https://github.com/aerodrome-finance/contracts (README deployment table)"
AAVE_BASE = "https://github.com/bgd-labs/aave-address-book/blob/main/src/AaveV3Base.sol"
AAVE_BNB = "https://github.com/bgd-labs/aave-address-book/blob/main/src/AaveV3BNB.sol"
AAVE_ARB = "https://github.com/bgd-labs/aave-address-book/blob/main/src/AaveV3Arbitrum.sol"
PCS3 = "https://developer.pancakeswap.finance/contracts/v3/addresses"
PCS2 = "https://developer.pancakeswap.finance/contracts/v2/addresses"
VENUS = "https://docs-v4.venus.io/deployed-contracts/markets (BNB Chain Mainnet > Core Pool)"

REG = {
 "base": {"chain_id": 8453, "native": "ETH",
  "rpc": ["https://mainnet.base.org", "https://base-rpc.publicnode.com"],
  "tokens": {
   "usdc": {"address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "expect_decimals": 6, "doc": CIRCLE, "note": "Circle native USDC (NOT USDbC)"},
   "weth": {"address": "0x4200000000000000000000000000000000000006", "expect_decimals": 18, "doc": BASEDOCS + " ; " + U_BASE},
   "ausdc_aave": {"address": "0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB", "expect_decimals": 6, "doc": AAVE_BASE, "note": "aBasUSDC"},
  },
  "contracts": {
   "uniswap_v3_factory": {"address": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD", "doc": U_BASE},
   "uniswap_v3_swaprouter02": {"address": "0x2626664c2603336E57B271c5C0b26F421741e481", "doc": U_BASE, "kind": "sr02"},
   "uniswap_universal_router": {"address": "0x6fF5693b99212Da76ad316178A184AB56D299b43", "doc": U_BASE},
   "uniswap_v3_quoterv2": {"address": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a", "doc": U_BASE},
   "permit2": {"address": "0x000000000022D473030F116dDEE9F6B43aC78BA3", "doc": U_BASE},
   "aerodrome_router": {"address": "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43", "doc": AERO},
   "aerodrome_pool_factory": {"address": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da", "doc": AERO},
   "aave_v3_pool_addresses_provider": {"address": "0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D", "doc": AAVE_BASE},
   "aave_v3_pool": {"address": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5", "doc": AAVE_BASE},
   "op_gas_price_oracle": {"address": "0x420000000000000000000000000000000000000F", "doc": BASEDOCS},
  }},
 "bnb": {"chain_id": 56, "native": "BNB",
  "rpc": ["https://bsc-dataseed.bnbchain.org", "https://bsc-rpc.publicnode.com"],
  "tokens": {
   "usdt": {"address": "0x55d398326f99059fF775485246999027B3197955", "expect_decimals": 18, "doc": VENUS + " ; " + AAVE_BNB, "note": "Binance-Peg BSC-USD, 18 decimals"},
   "usdc": {"address": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", "expect_decimals": 18, "doc": VENUS + " ; " + AAVE_BNB, "note": "Binance-Peg USDC, 18 decimals (not Circle-native; not on Circle list)"},
   "wbnb": {"address": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", "expect_decimals": 18, "doc": VENUS + " ; " + AAVE_BNB},
   "vusdt_venus": {"address": "0xfD5840Cd36d94D7229439859C0112a4185BC0255", "expect_decimals": 8, "doc": VENUS},
   "ausdt_aave": {"address": "0xa9251ca9DE909CB71783723713B21E4233fbf1B1", "expect_decimals": 18, "doc": AAVE_BNB},
  },
  "contracts": {
   "pancake_v3_factory": {"address": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", "doc": PCS3},
   "pancake_v3_swaprouter": {"address": "0x1b81D678ffb9C0263b24A97847620C99d213eB14", "doc": PCS3, "kind": "sr01"},
   "pancake_smart_router": {"address": "0x13f4EA83D0bd40E75C8222255bc855a974568Dd4", "doc": PCS3, "kind": "sr02"},
   "pancake_v3_quoterv2": {"address": "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997", "doc": PCS3},
   "pancake_v2_router": {"address": "0x10ED43C718714eb63d5aA57B78B54704E256024E", "doc": PCS2},
   "pancake_v2_factory": {"address": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73", "doc": PCS2},
   "venus_core_comptroller": {"address": "0xfD36E2c2a6789Db23113685031d7F16329158384", "doc": VENUS},
   "aave_v3_pool_addresses_provider": {"address": "0xff75B6da14FfbbfD355Daf7a2731456b3562Ba6D", "doc": AAVE_BNB},
   "aave_v3_pool": {"address": "0x6807dc923806fE8Fd134338EABCA509979a7e0cB", "doc": AAVE_BNB},
  }},
}
ERC20 = [{"name": n, "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": t}]}
         for n, t in (("symbol", "string"), ("decimals", "uint8"), ("name", "string"))]
def fn(name, out="address", ins=()):
    return [{"name": name, "type": "function", "stateMutability": "view",
             "inputs": [{"name": f"a{i}", "type": x} for i, x in enumerate(ins)], "outputs": [{"type": out}]}]

def w3for(chain):
    from lib_chains import make_w3; return make_w3(chain, REG[chain]["rpc"])
def _unused(chain):
    for u in REG[chain]["rpc"]:
        w = Web3(Web3.HTTPProvider(u, request_kwargs={"timeout": 15}))
        w.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        try:
            if w.eth.chain_id == REG[chain]["chain_id"]:
                return w
        except Exception:
            pass
    raise SystemExit(f"no RPC for {chain}")

def main():
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "verified": True, "chains": {}}
    ok_all = True
    for chain, cfg in REG.items():
        w = w3for(chain); C = Web3.to_checksum_address
        res = {k: v for k, v in cfg.items() if k not in ("tokens", "contracts")}
        res["tokens"], res["contracts"] = {}, {}
        for sec in ("tokens", "contracts"):
            for k, e in cfg[sec].items():
                a = C(e["address"]); code = w.eth.get_code(a)
                r = dict(e, address=a, code_len=len(code), code_ok=len(code) > 0)
                if sec == "tokens":
                    c = w.eth.contract(address=a, abi=ERC20)
                    r["symbol"] = c.functions.symbol().call(); r["decimals"] = c.functions.decimals().call()
                    r["decimals_ok"] = r["decimals"] == e["expect_decimals"]
                r["ok"] = r["code_ok"] and r.get("decimals_ok", True)
                res[sec][k] = r
        # cross checks
        x = {}
        ct, tk = res["contracts"], res["tokens"]
        def call(addr, name, out="address", ins=(), args=()):
            return w.eth.contract(address=addr, abi=fn(name, out, ins)).functions[name](*args).call()
        if chain == "base":
            x["aave_provider.getPool==pool"] = call(ct["aave_v3_pool_addresses_provider"]["address"], "getPool").lower() == ct["aave_v3_pool"]["address"].lower()
            x["aUSDC.UNDERLYING_ASSET_ADDRESS==usdc"] = call(tk["ausdc_aave"]["address"], "UNDERLYING_ASSET_ADDRESS").lower() == tk["usdc"]["address"].lower()
            x["sr02.factory==uni_factory"] = call(ct["uniswap_v3_swaprouter02"]["address"], "factory").lower() == ct["uniswap_v3_factory"]["address"].lower()
            x["sr02.WETH9==weth"] = call(ct["uniswap_v3_swaprouter02"]["address"], "WETH9").lower() == tk["weth"]["address"].lower()
            x["quoter.factory==uni_factory"] = call(ct["uniswap_v3_quoterv2"]["address"], "factory").lower() == ct["uniswap_v3_factory"]["address"].lower()
            x["aero_router.defaultFactory==aero_factory"] = call(ct["aerodrome_router"]["address"], "defaultFactory").lower() == ct["aerodrome_pool_factory"]["address"].lower()
            x["aero_router.weth==weth"] = call(ct["aerodrome_router"]["address"], "weth").lower() == tk["weth"]["address"].lower()
        else:
            x["aave_provider.getPool==pool"] = call(ct["aave_v3_pool_addresses_provider"]["address"], "getPool").lower() == ct["aave_v3_pool"]["address"].lower()
            x["aUSDT.UNDERLYING_ASSET_ADDRESS==usdt"] = call(tk["ausdt_aave"]["address"], "UNDERLYING_ASSET_ADDRESS").lower() == tk["usdt"]["address"].lower()
            x["vUSDT.underlying==usdt"] = call(tk["vusdt_venus"]["address"], "underlying").lower() == tk["usdt"]["address"].lower()
            x["vUSDT.comptroller==core"] = call(tk["vusdt_venus"]["address"], "comptroller").lower() == ct["venus_core_comptroller"]["address"].lower()
            x["pcs_v3_router.factory==pcs_v3_factory"] = call(ct["pancake_v3_swaprouter"]["address"], "factory").lower() == ct["pancake_v3_factory"]["address"].lower()
            x["pcs_v3_router.WETH9==wbnb"] = call(ct["pancake_v3_swaprouter"]["address"], "WETH9").lower() == tk["wbnb"]["address"].lower()
            x["smart_router.factory==pcs_v3_factory"] = call(ct["pancake_smart_router"]["address"], "factory").lower() == ct["pancake_v3_factory"]["address"].lower()
            x["quoter.factory==pcs_v3_factory"] = call(ct["pancake_v3_quoterv2"]["address"], "factory").lower() == ct["pancake_v3_factory"]["address"].lower()
            x["v2_router.factory==v2_factory"] = call(ct["pancake_v2_router"]["address"], "factory").lower() == ct["pancake_v2_factory"]["address"].lower()
            x["v2_router.WETH==wbnb"] = call(ct["pancake_v2_router"]["address"], "WETH").lower() == tk["wbnb"]["address"].lower()
        res["cross_checks"] = x
        bad = [k for s in ("tokens", "contracts") for k, v in res[s].items() if not v["ok"]] + [k for k, v in x.items() if not v]
        res["failures"] = bad; ok_all &= not bad
        out["chains"][chain] = res
    out["verified"] = ok_all
    p = Path(__file__).with_name("chains.json"); p.write_text(json.dumps(out, indent=1))
    print(json.dumps({c: {"failures": v["failures"], "tokens": {k: (t["symbol"], t["decimals"]) for k, t in v["tokens"].items()}, "cross": v["cross_checks"]} for c, v in out["chains"].items()}, indent=1))
    print("verified:", ok_all, "->", p)
main()
