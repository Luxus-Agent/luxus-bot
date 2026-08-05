"""
On-chain settlement for (1) auto-repurchase (per the client "fully automatic"
spec — see app/core/repurchase.py) and (2) Stream/Boost matrix payouts + their
sponsor-share bonus (see app/core/matrix_runtime.py).

(1) Repurchase: the ONLY on-chain action needed is simpler than replaying a
full multi-recipient split — move the settled amount (price + platform fee)
from the REPURCHASE_RESERVE_WALLET to PLATFORM_FEE_WALLET, a single ERC20
`transfer` consolidating it into the wallet that eventually funds the member-
payout rail. Disabled by default: with settings.REPURCHASE_SIGNER_PRIVATE_KEY
unset, `send_repurchase_settlement` never attempts a transaction, and auto-
repurchase stays exactly the internal-ledger-only operation it was before this
module existed.

(2) Matrix payouts: unlike Core (paid directly by the buyer's own on-chain
transaction at purchase time, since the recipient is known upfront), a Stream/
Boost recipient is only decided later, by the matrix engine — so
`send_matrix_payout_settlement` broadcasts a SEPARATE transfer straight to
that recipient's own wallet the instant their payout is credited, from the
PLATFORM_FEE_WALLET signer (that's already where Stream/Boost's on-chain share
of every purchase lands). Disabled the same way: with
settings.PLATFORM_FEE_SIGNER_PRIVATE_KEY unset, matrix payouts stay exactly
the internal-ledger-only operation they were before this function existed
(credited via wallet_ops.credit_wallet / credit_main_wallet_direct).

Every function here is best-effort — on ANY failure (bad RPC, insufficient BNB
for gas, insufficient USDT balance, network error) it logs and returns None
rather than raising, so a broadcast failure never breaks the surrounding
purchase request or rolls back the internal accounting that already happened
(repurchase) or blocks falling back to internal crediting (matrix payouts).
"""
import logging
from decimal import Decimal

from app.config import settings

logger = logging.getLogger(__name__)

# Minimal ERC20 ABI — only the functions this module calls.
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
_ERC20_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
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


def _platform_fee_signer_account():
    """Return the eth_account Account for PLATFORM_FEE_SIGNER_PRIVATE_KEY, or
    None if unset/invalid. Never raises."""
    key = (settings.PLATFORM_FEE_SIGNER_PRIVATE_KEY or "").strip()
    if not key:
        return None
    try:
        from eth_account import Account
        return Account.from_key(key)
    except Exception:
        logger.exception("onchain: PLATFORM_FEE_SIGNER_PRIVATE_KEY is set but invalid.")
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


def send_matrix_payout_settlement(amount: Decimal, dest_address: str, reference: str) -> str | None:
    """
    Broadcast the on-chain settlement for one Stream/Boost matrix payout (or its
    sponsor-share bonus): transfer `amount` USDT from the PLATFORM_FEE_WALLET
    signer wallet directly to the recipient's own wallet — the same instant-
    settlement treatment Core commissions already get, just via a separate
    broadcast here since (unlike Core) the recipient isn't known until the
    matrix engine decides the payout, well after the buyer's own on-chain
    purchase transaction already happened.

    `amount` is the caller's responsibility: Stream sends only the 70% share
    (20%/10% stay internal, mirrored via wallet_ops.mirror_onchain_earning_split);
    Boost sends the full 100% (it has no internal split at all). This function
    just moves whatever amount it's given.

    Returns the tx hash (0x...) on success, or None if disabled/failed —
    callers must treat None as "not broadcast" and fall back to crediting the
    recipient's internal wallet exactly as before this feature existed.
    """
    account = _platform_fee_signer_account()
    if account is None:
        return None  # feature disabled — internal-ledger-only, as before.

    import re
    if not re.match(_BEP20_ADDR_RE_SOURCE, (dest_address or "").strip()):
        logger.error(
            "onchain: matrix payout settlement skipped for %s — invalid destination address %r.",
            reference, dest_address,
        )
        return None

    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.BSC_RPC_URL))
        if not w3.is_connected():
            logger.error("onchain: cannot reach BSC_RPC_URL=%s — skipping matrix payout settlement for %s.",
                         settings.BSC_RPC_URL, reference)
            return None

        token = w3.eth.contract(
            address=Web3.to_checksum_address(settings.USDT_CONTRACT),
            abi=_ERC20_TRANSFER_ABI,
        )
        value = int((amount * (10 ** settings.USDT_DECIMALS)).to_integral_value())

        nonce = w3.eth.get_transaction_count(account.address, "pending")
        tx = token.functions.transfer(Web3.to_checksum_address(dest_address), value).build_transaction({
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
            "onchain: matrix payout settlement sent amount=%s from=%s to=%s tx=%s ref=%s",
            amount, account.address, dest_address, tx_hash_hex, reference,
        )
        return tx_hash_hex
    except Exception:
        logger.exception(
            "onchain: matrix payout settlement FAILED amount=%s dest=%s ref=%s — "
            "falling back to internal wallet crediting, on-chain transfer did not happen.",
            amount, dest_address, reference,
        )
        return None


def get_wallet_onchain_balances(address: str) -> dict:
    """
    Read-only lookup of a wallet's live on-chain USDT balance and native BNB
    (gas) balance — used by the admin treasury view to show what's actually
    sitting in PLATFORM_FEE_WALLET / ADMIN_INCOME_WALLET / REPURCHASE_RESERVE_WALLET,
    since those are on-chain addresses with no internal DB row to read.

    Never raises: on a bad address, unreachable RPC, or any other failure this
    returns usdt/bnb as None with `error` set, so a single unreachable wallet
    can't break the admin dashboard.
    """
    import re

    address = (address or "").strip()
    if not address:
        return {"address": None, "usdt": None, "bnb": None, "error": "not configured"}
    if not re.match(_BEP20_ADDR_RE_SOURCE, address):
        return {"address": address, "usdt": None, "bnb": None, "error": "invalid address"}

    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.BSC_RPC_URL))
        if not w3.is_connected():
            return {"address": address, "usdt": None, "bnb": None, "error": "RPC unreachable"}

        checksum = Web3.to_checksum_address(address)

        token = w3.eth.contract(
            address=Web3.to_checksum_address(settings.USDT_CONTRACT),
            abi=_ERC20_BALANCE_ABI,
        )
        raw_usdt = token.functions.balanceOf(checksum).call()
        usdt = Decimal(raw_usdt) / (Decimal(10) ** settings.USDT_DECIMALS)

        raw_bnb = w3.eth.get_balance(checksum)
        bnb = Decimal(raw_bnb) / (Decimal(10) ** 18)

        return {"address": address, "usdt": usdt, "bnb": bnb, "error": None}
    except Exception as exc:
        logger.exception("onchain: balance lookup failed for %s", address)
        return {"address": address, "usdt": None, "bnb": None, "error": str(exc)}
