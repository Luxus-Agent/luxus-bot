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
from datetime import datetime
from decimal import ROUND_CEILING, Decimal

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


def _locked_broadcast(conn, account, dest: str, amount: Decimal, kind: str, key: str | None) -> str | None:
    """Body of _broadcast_transfer — runs while holding the signer's advisory lock."""
    from sqlalchemy import insert, select, update
    from web3 import Web3
    from web3.exceptions import TimeExhausted

    from app.models.onchain_settlement import OnchainSettlement as S

    t = S.__table__
    now = datetime.utcnow

    def _set(**vals):
        conn.execute(update(t).where(t.c.idempotency_key == key).values(updated_at=now(), **vals))
        conn.commit()

    # ── Idempotency: has this exact payout already been broadcast? ────────────
    if key:
        row = conn.execute(select(t.c.tx_hash, t.c.status).where(t.c.idempotency_key == key)).first()
        conn.rollback()
        if row is None:
            conn.execute(insert(t).values(
                idempotency_key=key, kind=kind, dest_address=dest, amount=amount,
                status="sending", created_at=now(), updated_at=now(),
            ))
            conn.commit()
        elif row.tx_hash and row.status in ("sent", "confirmed", "pending"):
            logger.warning(
                "onchain: %s already broadcast as %s — reusing it, NOT sending again.", key, row.tx_hash,
            )
            return row.tx_hash
        elif row.status == "sending":
            logger.critical(
                "onchain: AMBIGUOUS settlement %s (dest=%s amount=%s) — a previous attempt died "
                "mid-broadcast, so it is unknown whether the USDT was sent. NOT retrying. Check the "
                "signer wallet on the explorer; the caller falls back to internal crediting.",
                key, dest, amount,
            )
            return None
        else:  # failed / reverted earlier — nothing moved, safe to try again
            _set(status="sending", tx_hash=None)

    # ── Broadcast ────────────────────────────────────────────────────────────
    try:
        w3 = Web3(Web3.HTTPProvider(settings.BSC_RPC_URL, request_kwargs={"timeout": 20}))
        if not w3.is_connected():
            logger.error("onchain: cannot reach BSC_RPC_URL=%s — skipping settlement %s.",
                         settings.BSC_RPC_URL, key)
            if key:
                _set(status="failed")
            return None
        token = w3.eth.contract(
            address=Web3.to_checksum_address(settings.USDT_CONTRACT), abi=_ERC20_TRANSFER_ABI,
        )
        value = int((amount * (10 ** settings.USDT_DECIMALS)).to_integral_value())
        # Nonce read + send happen under the signer lock, so concurrent purchases
        # (other threads or other workers) can never pick the same nonce.
        nonce = w3.eth.get_transaction_count(account.address, "pending")
        tx = token.functions.transfer(Web3.to_checksum_address(dest), value).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": w3.eth.chain_id,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction).hex()
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash
    except Exception:
        logger.exception("onchain: broadcast FAILED kind=%s amount=%s dest=%s key=%s", kind, amount, dest, key)
        if key:
            try:
                _set(status="failed")
            except Exception:
                logger.exception("onchain: could not mark %s failed", key)
        return None

    # Record the hash IMMEDIATELY (own commit) — from here a retry reuses it.
    if key:
        try:
            _set(tx_hash=tx_hash, status="sent")
        except Exception:
            logger.critical("onchain: broadcast %s (key=%s) succeeded but recording it failed!", tx_hash, key)

    # ── Confirm: wait (bounded) for the receipt so a revert is never reported as paid ──
    try:
        receipt = w3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=settings.SETTLEMENT_RECEIPT_TIMEOUT_SECONDS, poll_latency=1,
        )
    except TimeExhausted:
        logger.warning("onchain: %s not mined within %ss — treating as pending/paid (key=%s).",
                       tx_hash, settings.SETTLEMENT_RECEIPT_TIMEOUT_SECONDS, key)
        if key:
            _set(status="pending")
        return tx_hash
    except Exception:
        logger.exception("onchain: could not fetch receipt for %s (key=%s) — treating as pending/paid.", tx_hash, key)
        return tx_hash

    if receipt["status"] != 1:
        logger.error("onchain: %s REVERTED (key=%s, kind=%s, amount=%s, dest=%s) — no funds moved.",
                     tx_hash, key, kind, amount, dest)
        if key:
            _set(status="reverted")
        return None
    if key:
        _set(status="confirmed")
    logger.info("onchain: %s confirmed kind=%s amount=%s dest=%s key=%s", tx_hash, kind, amount, dest, key)
    return tx_hash


def _broadcast_transfer(account, dest: str, amount: Decimal, kind: str, key: str | None) -> str | None:
    """
    Send `amount` USDT from `account` to `dest`, safely:

      • SERIALISED per signer — a Postgres advisory lock (held on one dedicated
        connection) makes the nonce read + broadcast atomic across threads AND
        uvicorn workers, so two concurrent purchases can't reuse a nonce.
      • IDEMPOTENT per `key` — see models/onchain_settlement.py. A retried
        request reuses the original tx hash instead of paying a second time.
      • CONFIRMED — waits (bounded) for the receipt; a reverted tx returns None,
        never a hash that would be recorded as "Completed".

    Returns the tx hash, or None if nothing was (reliably) sent. Never raises.
    """
    from sqlalchemy import text

    from app.database import engine

    lock_key = f"onchain-signer:{account.address.lower()}"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"), {"k": lock_key})
            conn.commit()
            try:
                return _locked_broadcast(conn, account, dest, amount, kind, key)
            finally:
                try:
                    conn.rollback()
                    conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": lock_key})
                    conn.commit()
                except Exception:
                    # Never hand a connection that may still hold the lock back to the pool.
                    logger.exception("onchain: could not release signer lock — discarding connection.")
                    conn.invalidate()
    except Exception:
        logger.exception("onchain: settlement machinery failed kind=%s key=%s dest=%s", kind, key, dest)
        return None


def send_repurchase_settlement(
    amount: Decimal, tier: int, reference: str, idempotency_key: str | None = None,
) -> str | None:
    """
    Broadcast the on-chain settlement for one auto-repurchase: transfer `amount`
    USDT from the reserve signer wallet to PLATFORM_FEE_WALLET.

    Returns the tx hash (0x...) on success, or None if disabled/failed — callers
    must treat None as "not broadcast" and carry on with the internal
    accounting, which always applies regardless. Pass `idempotency_key` (unique
    per repurchase) so a retry can never broadcast the same one twice.
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
    logger.info("onchain: repurchase settlement tier=%s amount=%s ref=%s", tier, amount, reference)
    return _broadcast_transfer(account, dest, amount, "repurchase", idempotency_key)


def send_matrix_payout_settlement(
    amount: Decimal, dest_address: str, reference: str, idempotency_key: str | None = None,
) -> str | None:
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
    Boost sends 90% (own payout) or the full 100% (sponsor share). This function
    just moves whatever amount it's given.

    Returns the tx hash (0x...) on success, or None if disabled/failed —
    callers must treat None as "not broadcast" and fall back to crediting the
    recipient's internal wallet. Pass `idempotency_key` (unique per payout) so a
    retried request can never pay the same payout twice.
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
    return _broadcast_transfer(account, dest_address.strip(), amount, "matrix_payout", idempotency_key)


# Floor for the low-gas alert's recommended top-up — no point suggesting less
# than this even when the live gas price alone computes to a smaller number
# (BSC gas has historically been well under 1 Gwei).
_MIN_RECOMMENDED_TOPUP_BNB = Decimal("0.05")
# How many future settlement broadcasts (each capped at this module's fixed
# 100_000 gas limit) the recommendation should comfortably outlast, priced at
# today's gas price.
_RECOMMENDED_TX_RUNWAY = 500


def get_recommended_gas_topup_bnb() -> Decimal | None:
    """
    Best-effort "top up to at least this much" BNB figure for the low-gas
    alert email (core/gas_alerts.py), computed from BSC_RPC_URL's LIVE gas
    price — so switching BSC_RPC_URL from testnet to mainnet (or a mainnet
    price spike) is reflected automatically, with no separate mainnet/testnet
    branch anywhere in this codebase.

    = max(_MIN_RECOMMENDED_TOPUP_BNB, current_gas_price * 100_000 gas *
    _RECOMMENDED_TX_RUNWAY), rounded up to a clean 2-decimal figure so the
    recommendation never understates what it computed. Returns None on any
    RPC failure — callers should omit the recommendation rather than show a
    stale or wrong number.
    """
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.BSC_RPC_URL))
        if not w3.is_connected():
            return None

        gas_price_wei = Decimal(w3.eth.gas_price)
        scaled = gas_price_wei * Decimal(100_000) * Decimal(_RECOMMENDED_TX_RUNWAY) / Decimal(10**18)
        recommended = max(_MIN_RECOMMENDED_TOPUP_BNB, scaled)
        return recommended.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    except Exception:
        logger.exception("onchain: failed to compute recommended gas top-up.")
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


# ── Buyer payment verification (pack/status) ─────────────────────────────────
# keccak256("Transfer(address,address,uint256)")
_TRANSFER_TOPIC = "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def verify_pack_payment(tx_hash: str, expected: dict[str, Decimal]) -> tuple[str, str]:
    """
    Verify that `tx_hash` really paid a pack purchase: the transaction was mined
    and SUCCEEDED, and the USDT token contract (settings.USDT_CONTRACT) emitted a
    `Transfer` to EVERY expected recipient for at least the expected amount.

    `expected` maps lower-cased recipient address -> USDT amount (the net,
    on-chain amounts recorded in PackPurchase.recipients_json). Matching on the
    token's own Transfer logs (not on tx.to / calldata) means it works however
    the MultiSender routes the funds, and a fabricated hash or a tx that paid
    someone else can't satisfy it. Overpayment is accepted; underpayment isn't.

    Returns (status, reason): status is "ok", "invalid" (the payment does not
    check out — reject) or "unavailable" (RPC unreachable / tx not visible yet —
    the caller should leave the order PENDING so it can be retried).
    Never raises.
    """
    try:
        from web3 import Web3
        from web3.exceptions import TimeExhausted, TransactionNotFound

        w3 = Web3(Web3.HTTPProvider(settings.BSC_RPC_URL, request_kwargs={"timeout": 20}))
        if not w3.is_connected():
            return "unavailable", "BSC RPC unreachable."
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=12, poll_latency=2)
        except (TransactionNotFound, TimeExhausted):
            return "unavailable", "Transaction not found on-chain yet."

        if receipt["status"] != 1:
            return "invalid", "Transaction reverted on-chain."

        token = settings.USDT_CONTRACT.lower()
        received: dict[str, int] = {}
        for log in receipt["logs"]:
            topics = log["topics"]
            if str(log["address"]).lower() != token or len(topics) != 3:
                continue
            if bytes(topics[0]).hex() != _TRANSFER_TOPIC:
                continue
            to_addr = "0x" + bytes(topics[2]).hex()[-40:]
            data = log["data"]
            value = int.from_bytes(bytes(data), "big") if not isinstance(data, str) else int(data, 16)
            received[to_addr] = received.get(to_addr, 0) + value

        scale = Decimal(10) ** settings.USDT_DECIMALS
        for addr, amount in expected.items():
            need = int((amount * scale).to_integral_value())
            got = received.get(addr.lower(), 0)
            if got < need:
                return "invalid", (
                    f"Recipient {addr} received {Decimal(got) / scale} USDT, expected {amount}."
                )
        return "ok", ""
    except Exception:
        logger.exception("onchain: verify_pack_payment failed for tx %s", tx_hash)
        return "unavailable", "Could not verify the transaction right now."
