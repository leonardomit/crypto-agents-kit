"""Tokens e routers por chain."""
TOKENS = {
    "base": {
        "weth": "0x4200000000000000000000000000000000000006",
        "eth": "0x4200000000000000000000000000000000000006",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "ethereum": {
        "weth": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "eth": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "usdc": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    },
    "arbitrum": {
        "weth": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "eth": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        # ARB governance token — doc: https://docs.arbitrum.foundation/deployment-addresses ; eth_getCode len 2593,
        # symbol ARB, decimals 18, verified 2026-10-08. Pools WETH/ARB 0.05% (0xC6F780497A95e246EB9449f5e4770916DCd6396A, deepest) / 0.3%.
        "arb": "0x912CE59144191C1204E64559FE8253a0e49E6548",
    },
}
QUOTER_V2 = {
    "base": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
    "ethereum": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
    "arbitrum": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
}
ROUTER = {
    "base": "0x2626664c2603336E57B271c5C0b26F421741e481",
    "ethereum": "0x68b3465833fb72A710882e39C25BaAabfD80e577",
    "arbitrum": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
}
ROUTER_KIND = {"base": "sr02", "ethereum": "sr02", "arbitrum": "sr01"}
DENYLIST = {"arbitrum": {
    "0x68b3465833fb72a710882e39c25baaabfd80e577",  # SwapRouter02 docs empty
    "0x794a61358d6845594f94dc1db446a818166be8e4",  # Aave Pool typo/empty — use getPool()
}}
DECIMALS = {"usdc": 6, "weth": 18, "eth": 18, "arb": 18}
FEE_TIERS = (500, 3000, 10000)
