"""
Automatic member payout (per the client "into the user wallet" follow-up spec).

Pays every user's current withdrawable balance (MAIN + ACCOUNT wallets — the
same figure POST /distribution/wallet-map calls `profit.withdrawable`) out to
their own on-chain wallet, via the MultiSender contract, signed by
PLATFORM_FEE_WALLET. Runs automatically after every purchase — wired into
POST /distribution/pack/status, right after the auto-repurchase sweep — with
no admin approval step, the same "fully automatic" treatment already built for
auto-repurchase (see app/core/onchain.py).

This is a SEPARATE mechanism from the admin-triggered
POST /distribution/payout/create + /payout/status pair (app/api/distribution.py),
which stays available as a manual fallback / audit tool. Both ultimately drain
balances via debit_withdrawable, so whichever runs first for a given user simply
leaves nothing for the other to pay — they can't double-pay the same balance.

Disabled by default: leave PLATFORM_FEE_SIGNER_PRIVATE_KEY empty and this never
attempts a transaction — member earnings stay purely internal-ledger, exactly
today's behavior. Best-effort: any failure (bad RPC, no gas, no allowance,
network error) is logged and swallowed, never blocks the purchase request that
triggered it, and leaves every balance untouched for the next purchase's sweep
to retry.

Concurrency: two purchases can call POST /distribution/pack/status at the same
time, each triggering a sweep. To make sure two concurrent sweeps can never
read + pay the same balance twice before either commits, the candidate wallet
rows are locked (SELECT ... FOR UPDATE) up front and held for the rest of this
function — including across the on-chain send — so a second concurrent sweep
blocks on those specific rows until the first one's transaction commits.
"""
import logging
import re
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.core.wallet_ops import debit_withdrawable
from app.models.user import User
from app.models.wallet import Wallet, WalletType
from app.models.wallet_address import WalletAddress

logger = logging.getLogger(__name__)

_BEP20_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_FOUR = Decimal("0.0001")

# Cap recipients per on-chain call so one sweep never risks exceeding the block
# gas limit as the platform grows. Any remainder is left in the ledger exactly
# as-is and picked up by the very next purchase's sweep (same "defer, don't
# drop" pattern as the matrix backlog and the repurchase step cap).
_MAX_RECIPIENTS_PER_CALL = 25

_MAX_UINT256 = 2**256 - 1

_MULTISENDER_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "_token", "type": "address"},
            {"internalType": "address[]", "name": "_to", "type": "address[]"},
            {"internalType": "uint256[]", "name": "_value", "type": "uint256[]"},
        ],
        "name": "sendERC20DifferentValue",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

_ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


def _signer_account():
    key = (settings.PLATFORM_FEE_SIGNER_PRIVATE_KEY or "").strip()
    if not key:
        return None
    try:
        from eth_account import Account
        return Account.from_key(key)
    except Exception:
        logger.exception("member_payout: PLATFORM_FEE_SIGNER_PRIVATE_KEY is set but invalid.")
        return None


def _collect_and_lock_recipients(db: Session, limit: int) -> list[dict]:
    """
    Find up to `limit` users with a positive combined MAIN+ACCOUNT balance and
    a valid BEP-20 address, and row-lock their wallet rows for the rest of
    this sweep (see module docstring on concurrency).
    """
    candidate_ids = [
        uid for (uid,) in
        db.query(Wallet.user_id)
        .filter(Wallet.wallet_type.in_([WalletType.MAIN, WalletType.ACCOUNT]))
        .group_by(Wallet.user_id)
        .having(func.sum(Wallet.balance) > 0)
        .order_by(Wallet.user_id.asc())
        .limit(limit)
        .all()
    ]
    if not candidate_ids:
        return []

    locked = (
        db.query(Wallet)
        .filter(
            Wallet.user_id.in_(candidate_ids),
            Wallet.wallet_type.in_([WalletType.MAIN, WalletType.ACCOUNT]),
        )
        .with_for_update()
        .all()
    )
    totals: dict[int, Decimal] = {}
    for w in locked:
        totals[w.user_id] = totals.get(w.user_id, Decimal("0")) + Decimal(str(w.balance))
    owed = {uid: amt for uid, amt in totals.items() if amt > 0}
    if not owed:
        return []

    users = {u.id: u for u in db.query(User).filter(User.id.in_(owed)).all()}
    verified: dict[int, str] = {}
    for wa in (
        db.query(WalletAddress)
        .filter(WalletAddress.user_id.in_(owed), WalletAddress.is_verified.is_(True))
        .order_by(WalletAddress.user_id.asc(), WalletAddress.created_at.desc())
        .all()
    ):
        verified.setdefault(wa.user_id, wa.address)  # first per user = most recent (desc order)

    recipients = []
    for uid, amount in owed.items():
        user = users.get(uid)
        if user is None:
            continue
        addr = user.wallet_address or verified.get(uid)
        if not addr or not _BEP20_RE.match(addr):
            continue
        recipients.append({
            "user_id": uid,
            "wallet_address": addr,
            "amount": amount.quantize(_FOUR),
        })
    return recipients


def run_member_payout_sweep(db: Session) -> int:
    """
    Pay out up to _MAX_RECIPIENTS_PER_CALL members' current withdrawable
    balance to their own wallet in one MultiSender call, signed by
    PLATFORM_FEE_WALLET. Debits each paid user's balance so it isn't offered
    again. Returns the number of recipients paid (0 if disabled, nothing owed,
    or the attempt failed — all logged, never raised).
    """
    account = _signer_account()
    if account is None:
        return 0  # feature disabled — internal-ledger-only, as before.

    try:
        recipients = _collect_and_lock_recipients(db, _MAX_RECIPIENTS_PER_CALL)
        if not recipients:
            return 0

        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.BSC_RPC_URL))
        if not w3.is_connected():
            logger.error("member_payout: cannot reach BSC_RPC_URL=%s — skipping sweep.",
                         settings.BSC_RPC_URL)
            return 0

        usdt_addr = Web3.to_checksum_address(settings.USDT_CONTRACT)
        multisender_addr = Web3.to_checksum_address(settings.MULTISENDER_ADDRESS)
        usdt = w3.eth.contract(address=usdt_addr, abi=_ERC20_ABI)

        decimals = settings.USDT_DECIMALS
        values = [int((r["amount"] * (10 ** decimals)).to_integral_value()) for r in recipients]
        total_value = sum(values)

        nonce = w3.eth.get_transaction_count(account.address, "pending")
        chain_id = w3.eth.chain_id
        gas_price = w3.eth.gas_price

        current_allowance = usdt.functions.allowance(account.address, multisender_addr).call()
        if current_allowance < total_value:
            # build_transaction auto-fills "gas" via estimate_gas when omitted.
            approve_tx = usdt.functions.approve(multisender_addr, _MAX_UINT256).build_transaction({
                "from": account.address, "nonce": nonce, "gasPrice": gas_price, "chainId": chain_id,
            })
            signed_approve = account.sign_transaction(approve_tx)
            approve_hash = w3.eth.send_raw_transaction(signed_approve.rawTransaction)
            w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
            nonce += 1
            logger.info("member_payout: approved MultiSender allowance, tx=%s", approve_hash.hex())

        multisender = w3.eth.contract(address=multisender_addr, abi=_MULTISENDER_ABI)
        to_addresses = [Web3.to_checksum_address(r["wallet_address"]) for r in recipients]
        send_fn = multisender.functions.sendERC20DifferentValue(usdt_addr, to_addresses, values)
        # Estimate once ourselves (with a buffer) and pass "gas" in up front, so
        # build_transaction doesn't also auto-estimate a second time internally.
        estimated_gas = send_fn.estimate_gas({"from": account.address})
        send_tx = send_fn.build_transaction({
            "from": account.address, "nonce": nonce, "gasPrice": gas_price, "chainId": chain_id,
            "gas": int(estimated_gas * 1.2),
        })
        signed_send = account.sign_transaction(send_tx)
        tx_hash = w3.eth.send_raw_transaction(signed_send.rawTransaction)
        tx_hash_hex = tx_hash.hex()

        # Debit each paid recipient's withdrawable balance — mirrors what
        # POST /distribution/payout/status does on success, just triggered
        # automatically instead of by an admin confirming a batch. The rows
        # are already locked in this same transaction (see
        # _collect_and_lock_recipients), so this can't race a concurrent sweep.
        for r in recipients:
            debit_withdrawable(
                db, r["user_id"], r["amount"],
                reference_id=f"auto_payout_{tx_hash_hex[:16]}",
                notes=f"Automatic member payout — tx {tx_hash_hex[:12]}…",
            )

        logger.info(
            "member_payout: paid %d recipient(s) total=%s tx=%s",
            len(recipients), sum((r["amount"] for r in recipients), Decimal("0")), tx_hash_hex,
        )
        return len(recipients)
    except Exception:
        logger.exception(
            "member_payout: sweep FAILED — balances left untouched, will retry on the next purchase."
        )
        return 0
