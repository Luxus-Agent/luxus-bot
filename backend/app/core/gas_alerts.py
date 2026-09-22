"""
Low-gas email alerts for the platform-controlled wallets that pay their own
BNB gas — PLATFORM_FEE_WALLET (instant Stream/Boost settlement broadcasts,
core/onchain.send_matrix_payout_settlement) and REPURCHASE_RESERVE_WALLET
(auto-repurchase settlement broadcasts, core/onchain.send_repurchase_settlement).
ADMIN_INCOME_WALLET stays receive-only and is never alerted — this mirrors
NEEDS_GAS_KEYS in frontend/src/pages/admin/AdminDashboard.jsx exactly; keep
both lists in sync if a third wallet ever gets its own signer key.

There's no background scheduler in this app (fully synchronous, no
Celery/Redis) — the check instead piggybacks on GET /admin/treasury/onchain-
wallets, the same on-chain balance read the admin dashboard already polls
every 20s while open. One WalletGasAlert row per watched wallet records
whether it's CURRENTLY known to be low, so the email only fires once on the
ok -> low edge; it re-arms (and can fire again) only after the balance
recovers above threshold and later drops again — never once per poll while
it stays low. The DB state is updated synchronously (cheap, no I/O); only the
actual SMTP send is deferred via BackgroundTasks, same fire-and-forget
convention as every OTP email in this app.

Each fired alert also carries a recommended top-up amount
(onchain.get_recommended_gas_topup_bnb) computed from BSC_RPC_URL's live gas
price at the moment the edge is crossed — switching that URL from testnet to
mainnet (or a mainnet price spike) changes the recommendation automatically.
"""
from datetime import datetime
from decimal import Decimal

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.config import settings
from app.core.onchain import get_recommended_gas_topup_bnb
from app.models.wallet_gas_alert import WalletGasAlert
from app.services.email_service import send_low_gas_alert_email

# Keep in sync with GAS_WARN_BELOW in frontend/src/pages/admin/AdminDashboard.jsx.
GAS_ALERT_THRESHOLD_BNB = Decimal("0.01")

# Keep in sync with NEEDS_GAS_KEYS in the same file — only wallets that
# broadcast their own transactions (and so need their own gas) are watched.
GAS_ALERT_WALLET_KEYS = {"platform_fee", "repurchase_reserve"}


def sync_gas_alert_state(
    db: Session,
    wallet_key: str,
    wallet_label: str,
    wallet_address: str | None,
    bnb_balance: Decimal | None,
    background_tasks: BackgroundTasks,
) -> None:
    """
    Update this wallet's known low-gas state and fire an email on the ok -> low
    edge. No-op for unwatched wallets (admin_income) or when the balance
    couldn't be read (RPC error / unconfigured) — nothing reliable to alert on.
    """
    if wallet_key not in GAS_ALERT_WALLET_KEYS or bnb_balance is None:
        return

    state = db.query(WalletGasAlert).filter(WalletGasAlert.wallet_key == wallet_key).first()
    if state is None:
        state = WalletGasAlert(wallet_key=wallet_key, is_low=False)
        db.add(state)
        db.flush()

    is_currently_low = bnb_balance < GAS_ALERT_THRESHOLD_BNB
    if is_currently_low and not state.is_low:
        state.is_low = True
        state.last_alert_sent_at = datetime.utcnow()
        db.commit()
        recommended_topup_bnb = get_recommended_gas_topup_bnb()
        background_tasks.add_task(
            send_low_gas_alert_email,
            settings.ADMIN_EMAIL,
            wallet_label,
            wallet_address or "(not configured)",
            bnb_balance,
            recommended_topup_bnb,
        )
    elif not is_currently_low and state.is_low:
        state.is_low = False
        db.commit()
