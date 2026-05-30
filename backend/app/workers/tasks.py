"""
Celery task chain:

  activate_purchase
    ├─ route_core_income        (sync inside same task)
    ├─ place_in_stream          (sync inside same task)
    │    └─ process_matrix_payout  (queued per triggered level)
    │         └─ place_reentry → STREAM  (queued per re-entry, DUMMY, same tier)
    └─ place_in_boost           (sync inside same task)
         └─ process_matrix_payout  (queued per triggered level)
               └─ place_reentry → BOOST  (queued per re-entry, real / not dummy)

Sponsor milestone payouts (process_sponsor_payout) are queued separately
whenever a specific fill-count position is hit inside the matrix.

NOTE: Each queue self-cycles its own re-entries (per the client matrix diagram).
      Stream re-entries are DUMMY positions placed back into the SAME tier's
        Stream queue — they fill slots to advance the queue but earn nothing and
        spawn no further re-entries. Only one real Stream entry per user.
      Boost re-entries are REAL positions placed back into the single Boost queue.
      Stream does NOT feed Boost.
"""
import logging
from datetime import datetime
from decimal import Decimal

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="tasks.activate_purchase")
def activate_purchase(self, purchase_id: int) -> None:
    """Entry point: called after payment confirmation. Runs the full revenue engine."""
    from app.core.revenue_split import split_purchase
    from app.core.proactive import route_core
    from app.core.matrix_engine import place_in_matrix
    from app.models.agent import AgentPurchase
    from app.models.matrix import SystemType
    from app.models.user import User
    from app.models.wallet_address import WalletAddress  # noqa: F401 — must be imported before User mapper resolves relationships
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        purchase = db.query(AgentPurchase).filter_by(id=purchase_id).with_for_update().first()
        if not purchase or purchase.status != "pending":
            logger.warning("activate_purchase: purchase %s not found or already active", purchase_id)
            return

        buyer = db.query(User).filter_by(id=purchase.user_id).first()
        price = Decimal(str(purchase.price))

        split = split_purchase(price)

        # Core Agent: 30% to sponsor + 30% to supreme sponsor (odd/even routing)
        route_core(db, buyer, purchase.agent_tier, split.core)

        # Stream Agent: separate queue per tier
        _, stream_payouts, stream_sponsor_payouts = place_in_matrix(
            db, buyer.id, purchase.agent_tier, SystemType.STREAM
        )

        # Boost Agent: single global queue, always agent_tier=1
        _, boost_payouts, boost_sponsor_payouts = place_in_matrix(
            db, buyer.id, 1, SystemType.BOOST
        )

        purchase.status = "active"
        purchase.activated_at = datetime.utcnow()

        db.commit()

        # Notify user by email
        try:
            from app.services.email_service import send_agent_activated_email
            from app.models.agent import AGENT_TIER_PRICES
            send_agent_activated_email(
                email=buyer.email,
                username=buyer.username,
                agent_tier=purchase.agent_tier,
                price=float(AGENT_TIER_PRICES[purchase.agent_tier]),
            )
        except Exception:
            logger.exception(
                "activate_purchase: failed to send activation email for purchase_id=%s", purchase_id
            )

        # Queue level-completion payouts
        for payout in stream_payouts + boost_payouts:
            process_matrix_payout.delay(
                matrix_position_id=payout.matrix_position_id,
                user_id=payout.user_id,
                agent_tier=payout.agent_tier,
                system_type=payout.system_type.value,
                level=payout.level,
                wallet_amount=str(payout.wallet_amount),
                reentry_amount=str(payout.reentry_amount),
                reentry_count=payout.reentry_count,
            )

        # Queue sponsor milestone payouts
        for sp in stream_sponsor_payouts + boost_sponsor_payouts:
            process_sponsor_payout.delay(
                matrix_position_id=sp.matrix_position_id,
                owner_user_id=sp.owner_user_id,
                agent_tier=sp.agent_tier,
                system_type=sp.system_type.value,
                level=sp.level,
                amount=str(sp.amount),
            )

        total_payouts = (
            len(stream_payouts) + len(boost_payouts) +
            len(stream_sponsor_payouts) + len(boost_sponsor_payouts)
        )
        logger.info(
            "activate_purchase: purchase %s activated. %d payouts queued.",
            purchase_id,
            total_payouts,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("activate_purchase failed for purchase_id=%s", purchase_id)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="tasks.process_matrix_payout")
def process_matrix_payout(
    self,
    matrix_position_id: int,
    user_id: int,
    agent_tier: int,
    system_type: str,
    level: int,
    wallet_amount: str,
    reentry_amount: str,
    reentry_count: int,
) -> None:
    """
    Credit wallet for a completed matrix level, then queue re-entries.

    Re-entry destination:
      Stream → re-enters BOOST (not back into Stream)
      Boost  → re-enters BOOST
    """
    from app.core.wallet_ops import credit_wallet
    from app.models.matrix import SystemType
    from app.models.transaction import TransactionType
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        sys_type = SystemType(system_type)
        tx_type = (
            TransactionType.STREAM_PAYOUT
            if sys_type == SystemType.STREAM
            else TransactionType.BOOST_PAYOUT
        )

        credit_wallet(
            db=db,
            user_id=user_id,
            agent_tier=agent_tier,
            gross_amount=Decimal(wallet_amount),
            tx_type=tx_type,
            reference_id=f"matrix_pos_{matrix_position_id}_L{level}",
            notes=f"{sys_type.value} L{level} payout",
        )
        db.commit()

        # Re-entry routing (each queue self-cycles — per client diagram):
        #   Stream completion → DUMMY re-entry back into the SAME tier's Stream queue
        #   Boost  completion → REAL  re-entry back into the single Boost queue
        for i in range(reentry_count):
            place_reentry.delay(
                user_id=user_id,
                agent_tier=agent_tier,
                reentry_index=i + 1,
                source_position_id=matrix_position_id,
                system_type=system_type,
            )

        dest = "STREAM dummy" if sys_type == SystemType.STREAM else "BOOST real"
        logger.info(
            "process_matrix_payout: user=%s tier=%s %s L%s → $%s credited, %s re-entries queued (→ %s)",
            user_id, agent_tier, system_type, level, wallet_amount, reentry_count, dest,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("process_matrix_payout failed: position=%s level=%s", matrix_position_id, level)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="tasks.process_sponsor_payout")
def process_sponsor_payout(
    self,
    matrix_position_id: int,
    owner_user_id: int,
    agent_tier: int,
    system_type: str,
    level: int,
    amount: str,
) -> None:
    """
    Credit the sponsor of matrix_position's owner when a sponsor milestone fill
    count is reached (e.g. 5th member in L2, 20th member in L3).

    If the owner has no sponsor, the amount goes to the company (platform profit)
    and is NOT credited to any user.
    """
    from app.core.wallet_ops import credit_wallet
    from app.models.user import User
    from app.models.wallet_address import WalletAddress  # noqa: F401
    from app.models.transaction import TransactionType
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        owner = db.query(User).filter_by(id=owner_user_id).first()
        if not owner:
            logger.error("process_sponsor_payout: owner user_id=%s not found", owner_user_id)
            return

        if owner.sponsor_id:
            beneficiary_id = owner.sponsor_id
            notes = f"{system_type} L{level} sponsor milestone from pos #{matrix_position_id}"
            credit_wallet(
                db=db,
                user_id=beneficiary_id,
                agent_tier=agent_tier,
                gross_amount=Decimal(amount),
                tx_type=TransactionType.SPONSOR_MILESTONE_INCOME,
                reference_id=f"sponsor_milestone_pos_{matrix_position_id}_L{level}",
                notes=notes,
            )
        else:
            # Q10 principle: no sponsor → amount retained by platform, not credited to owner
            logger.info(
                "process_sponsor_payout: owner=%s has no sponsor — milestone amount retained by platform",
                owner_user_id,
            )

        db.commit()

        logger.info(
            "process_sponsor_payout: matrix_pos=%s owner=%s tier=%s %s L%s → $%s processed",
            matrix_position_id, owner_user_id, agent_tier, system_type, level, amount,
        )

    except Exception as exc:
        db.rollback()
        logger.exception(
            "process_sponsor_payout failed: matrix_pos=%s owner=%s", matrix_position_id, owner_user_id
        )
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="tasks.place_reentry")
def place_reentry(
    self,
    user_id: int,
    agent_tier: int,
    reentry_index: int,
    source_position_id: int,
    system_type: str = "boost",
) -> None:
    """
    Place a re-entry generated by a completed matrix level. Each queue self-cycles
    (per the client's matrix diagram):

      Stream → DUMMY position back into the SAME tier's Stream queue. It fills slots
               to advance the queue and earns nothing (dummies get no payout and
               spawn no further re-entries); it only pushes the real members above
               it toward their next level completion.
      Boost  → REAL position back into the single global Boost queue (tier 1); these
               earn full payouts when their own level fills.
    """
    from app.core.matrix_engine import place_in_matrix
    from app.models.matrix import MatrixPosition, SystemType
    from app.models.wallet_address import WalletAddress  # noqa: F401
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        sys_type = SystemType(system_type)
        if sys_type == SystemType.STREAM:
            # Stream re-entry: dummy, back into the same tier's Stream queue.
            new_slot, triggered_payouts, sponsor_payouts = place_in_matrix(
                db, user_id, agent_tier, SystemType.STREAM, is_dummy=True
            )
        else:
            # Boost re-entry: real, into the single Boost queue (always tier 1).
            new_slot, triggered_payouts, sponsor_payouts = place_in_matrix(
                db, user_id, 1, SystemType.BOOST, is_dummy=False
            )

        source = db.query(MatrixPosition).filter_by(id=source_position_id).first()
        if source:
            source.reentry_count += 1

        db.commit()

        for payout in triggered_payouts:
            process_matrix_payout.delay(
                matrix_position_id=payout.matrix_position_id,
                user_id=payout.user_id,
                agent_tier=payout.agent_tier,
                system_type=payout.system_type.value,
                level=payout.level,
                wallet_amount=str(payout.wallet_amount),
                reentry_amount=str(payout.reentry_amount),
                reentry_count=payout.reentry_count,
            )

        for sp in sponsor_payouts:
            process_sponsor_payout.delay(
                matrix_position_id=sp.matrix_position_id,
                owner_user_id=sp.owner_user_id,
                agent_tier=sp.agent_tier,
                system_type=sp.system_type.value,
                level=sp.level,
                amount=str(sp.amount),
            )

        logger.info(
            "place_reentry: user=%s tier=%s → %s re-entry #%s at position %s",
            user_id, agent_tier, sys_type.value, reentry_index, new_slot.position_number,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("place_reentry failed: user=%s tier=%s", user_id, agent_tier)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300, name="tasks.process_withdrawal")
def process_withdrawal(self, withdrawal_id: int) -> None:
    """
    Fires 24h after a withdrawal request.
    Calls the NOWPayments Payouts API and marks the record sent or failed.
    On failure the deducted amount is refunded back to the MAIN wallet.
    """
    import asyncio
    from datetime import datetime
    from decimal import Decimal

    from app.core.wallet_ops import credit_wallet
    from app.models.transaction import TransactionType
    from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
    from app.services.nowpayments import send_payout
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        withdrawal = (
            db.query(WithdrawalRequest)
            .filter_by(id=withdrawal_id)
            .with_for_update()
            .first()
        )

        if not withdrawal:
            logger.error("process_withdrawal: withdrawal_id=%s not found", withdrawal_id)
            return

        if withdrawal.status != WithdrawalStatus.PENDING:
            logger.info(
                "process_withdrawal: withdrawal_id=%s already in status '%s', skipping",
                withdrawal_id, withdrawal.status,
            )
            return

        withdrawal.status = WithdrawalStatus.PROCESSING
        db.commit()

        amount_float = float(withdrawal.amount)

        try:
            result = asyncio.run(
                send_payout(
                    withdrawal_id=withdrawal.id,
                    amount_usd=amount_float,
                    wallet_address=withdrawal.wallet_address,
                )
            )
            withdrawal.status = WithdrawalStatus.SENT
            withdrawal.nowpayments_payout_id = str(result.get("id", ""))
            withdrawal.processed_at = datetime.utcnow()
            db.commit()

            logger.info(
                "process_withdrawal: withdrawal_id=%d SENT via NOWPayments payout_id=%s",
                withdrawal_id, withdrawal.nowpayments_payout_id,
            )

            try:
                from app.models.user import User
                from app.services.email_service import send_withdrawal_sent_email
                user = db.query(User).filter_by(id=withdrawal.user_id).first()
                if user:
                    send_withdrawal_sent_email(
                        email=user.email,
                        username=user.username,
                        amount=float(withdrawal.amount),
                        wallet_address=withdrawal.wallet_address,
                        payout_id=withdrawal.nowpayments_payout_id,
                    )
            except Exception:
                logger.exception(
                    "process_withdrawal: failed to send sent-email for withdrawal_id=%d", withdrawal_id
                )

        except Exception as payout_exc:
            logger.error(
                "process_withdrawal: payout failed for withdrawal_id=%d — refunding. Error: %s",
                withdrawal_id, payout_exc,
            )
            withdrawal.status = WithdrawalStatus.FAILED
            withdrawal.failure_reason = str(payout_exc)[:500]
            withdrawal.processed_at = datetime.utcnow()

            # Refund the deducted amount directly to MAIN wallet (no repurchase split —
            # the 10% was already held at earn time, so the full withdrawn amount is restored).
            from app.core.wallet_ops import credit_main_wallet_direct
            credit_main_wallet_direct(
                db=db,
                user_id=withdrawal.user_id,
                agent_tier=withdrawal.agent_tier,
                amount=Decimal(str(withdrawal.amount)),
                tx_type=TransactionType.TRANSFER_IN,
                reference_id=f"withdrawal_{withdrawal_id}_refund",
                notes=f"Refund: withdrawal #{withdrawal_id} failed — balance restored",
            )
            db.commit()

            try:
                from app.models.user import User
                from app.services.email_service import send_withdrawal_failed_email
                user = db.query(User).filter_by(id=withdrawal.user_id).first()
                if user:
                    send_withdrawal_failed_email(
                        email=user.email,
                        username=user.username,
                        amount=float(withdrawal.amount),
                        reason=withdrawal.failure_reason or "Unknown error",
                    )
            except Exception:
                logger.exception(
                    "process_withdrawal: failed to send failure-email for withdrawal_id=%d", withdrawal_id
                )

            raise self.retry(exc=payout_exc)

    except Exception as exc:
        # Don't re-catch a Retry that was already raised by the inner payout handler —
        # doing so would double-schedule the task and waste the retry counter.
        from celery.exceptions import Retry as CeleryRetry
        if isinstance(exc, CeleryRetry):
            raise
        db.rollback()
        logger.exception("process_withdrawal task error for withdrawal_id=%s", withdrawal_id)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="tasks.auto_repurchase")
def auto_repurchase(self, user_id: int, agent_tier: int) -> None:
    """
    Triggered automatically when a user's repurchase wallet reaches the tier price.
    Creates a new AgentPurchase funded by the repurchase wallet (already deducted)
    and runs the full revenue engine via activate_purchase.
    """
    from app.models.agent import AgentPurchase, AGENT_TIER_PRICES
    from app.database import SessionLocal
    from datetime import datetime

    db = SessionLocal()
    try:
        purchase = AgentPurchase(
            user_id=user_id,
            agent_tier=agent_tier,
            price=AGENT_TIER_PRICES[agent_tier],
            status="pending",
            payment_id="auto_repurchase",
        )
        db.add(purchase)
        db.commit()
        db.refresh(purchase)

        activate_purchase.delay(purchase.id)

        logger.info(
            "auto_repurchase: queued purchase_id=%s for user=%s tier=%s",
            purchase.id, user_id, agent_tier,
        )

    except Exception as exc:
        db.rollback()
        logger.exception("auto_repurchase failed: user=%s tier=%s", user_id, agent_tier)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(name="tasks.confirm_payment_placeholder")
def confirm_payment_placeholder(purchase_id: int) -> None:
    """Dev-only: simulate payment confirmation without NOWPayments."""
    activate_purchase.delay(purchase_id)
