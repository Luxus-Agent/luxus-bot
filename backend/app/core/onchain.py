"""
On-chain settlement for auto-repurchase (per the client "fully automatic" spec —
see app/core/repurchase.py).

Every other piece of the repurchase cascade (Core routing, Stream/Boost matrix
credits) is already handled purely internally: uplines and matrix winners get
credited to their own internal wallet balance (app/core/wallet_ops.credit_wallet),
to be paid out for real later via the admin-triggered member-payout rail
(POST /distribution/payout/create + /payout/status). Because of that, the ONLY
on-chain action a repurchase needs is simpler than replaying a full multi-
recipient split: move the settled amount (price + platform fee) from the
REPURCHASE_RESERVE_WALLET to PLATFORM_FEE_WALLET — a single ERC20 `transfer`,
consolidating it into the wallet that eventually funds that payout rail.

Disabled by default: with settings.REPURCHASE_SIGNER_PRIVATE_KEY unset, this
module never attempts a transaction, and auto-repurchase stays exactly the
internal-ledger-only operation it was before this module existed. Every
function here is best-effort — on ANY failure (bad RPC, insufficient BNB for
gas, insufficient USDT balance, network error) it logs and returns None rather
than raising, so a broadcast failure never breaks the surrounding purchase
request or rolls back the internal accounting that already happened.
"""
import logging
from decimal import Decimal

from app.config import settings

logger = logging.getLogger(__name__)

# Minimal ERC20 ABI — only the one function this module calls.
_ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]

_BEP20_ADDR_RE_SOURCE = r"^0x[0-9a-fA-F]{40}$"


def _signer_account():
    """Return the eth_account Account for REPURCHASE_SIGNER_PRIVATE_KEY, or None
    if unset/invalid. Never raises."""
    key = (settings.REPURCHASE_SIGNER_PRIVATE_KEY or "").strip()
    if not key:
        return None
    try:
        from eth_account import Account
        return Account.from_key(key)
    except Exception:
        logger.exception("onchain: REPURCHASE_SIGNER_PRIVATE_KEY is set but invalid.")
        return None


def send_repurchase_settlement(amount: Decimal, tier: int, reference: str) -> str | None:
    """
    Broadcast the on-chain settlement for one auto-repurchase: transfer `amount`
    USDT from the reserve signer wallet to PLATFORM_FEE_WALLET.

    Returns the tx hash (0x...) on success, or None if disabled/failed — callers
    must treat None as "not broadcast, internal accounting already applied" and
    continue rather than fail the request.
    """
    account = _signer_account()
    if account is None:
        return None  # feature disabled — internal-ledger-only, as before.

    dest = (settings.PLATFORM_FEE_WALLET or "").strip()
    import re
    if not re.match(_BEP20_ADDR_RE_SOURCE, dest):
        logger.error(
            "onchain: PLATFORM_FEE_WALLET is not a valid BEP-20 address (%r) — "
            "skipping repurchase settlement for %s.", dest, reference,
        )
        return None

    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.BSC_RPC_URL))
        if not w3.is_connected():
            logger.error("onchain: cannot reach BSC_RPC_URL=%s — skipping settlement for %s.",
                         settings.BSC_RPC_URL, reference)
            return None

        token = w3.eth.contract(
            address=Web3.to_checksum_address(settings.USDT_CONTRACT),
            abi=_ERC20_TRANSFER_ABI,
        )
        value = int((amount * (10 ** settings.USDT_DECIMALS)).to_integral_value())

        nonce = w3.eth.get_transaction_count(account.address, "pending")
        tx = token.functions.transfer(Web3.to_checksum_address(dest), value).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": w3.eth.chain_id,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        tx_hash_hex = tx_hash.hex()
        logger.info(
            "onchain: repurchase settlement sent tier=%s amount=%s from=%s to=%s tx=%s ref=%s",
            tier, amount, account.address, dest, tx_hash_hex, reference,
        )
        return tx_hash_hex
    except Exception:
        logger.exception(
            "onchain: repurchase settlement FAILED tier=%s amount=%s ref=%s — "
            "internal accounting already applied, on-chain transfer did not happen.",
            tier, amount, reference,
        )
        return None
