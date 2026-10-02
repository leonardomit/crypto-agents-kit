#!/usr/bin/env python3
"""Valida a chave EVM: deriva o endereço e checa saldo nativo. NUNCA imprime a chave.

Lê DEFI_WALLET_PRIVATE_KEY do env (ou SECRETS_FILE opcional, ver lib_caps.py).
Grava o endereço derivado em $DEFI_STATE_DIR/wallet.address (gitignored).
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_caps import ADDR_FILE, RPC, STATE_DIR, load_key  # noqa: E402


def main() -> int:
    chain = os.environ.get("DEFAULT_CHAIN", "arbitrum")
    status = {"secret_set": False, "address": None, "rpc_ok": False, "chain": chain, "native_balance_wei": None}
    try:
        key = load_key()
    except SystemExit:
        print("secret_set=false")
        return 1
    status["secret_set"] = True
    from eth_account import Account
    from web3 import Web3
    acct = Account.from_key(key)
    status["address"] = acct.address
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ADDR_FILE.write_text(acct.address + "\n")
    expected = os.environ.get("DEFI_WALLET_ADDRESS", "").strip()
    if expected:
        status["matches_env_address"] = expected.lower() == acct.address.lower()
    try:
        w3 = Web3(Web3.HTTPProvider(RPC.get(chain, RPC["arbitrum"])))
        status["rpc_ok"] = bool(w3.is_connected())
        if status["rpc_ok"]:
            status["native_balance_wei"] = str(w3.eth.get_balance(acct.address))
    except Exception as e:  # noqa: BLE001
        status["rpc_error"] = type(e).__name__
    (STATE_DIR / "wallet.status.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
