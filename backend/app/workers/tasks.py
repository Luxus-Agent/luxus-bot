"""
Celery task chain:

  activate_purchase
    ├─ route_proactive_income   (sync inside same task)
    ├─ place_in_proportion      (sync inside same task)
    │    └─ process_matrix_payout  (queued per triggered level)
    │         └─ place_reentry → SPECULATION  (queued per re-entry)
    └─ place_in_speculation     (sync inside same task)
         └─ process_matrix_payout  (queued per triggered level)
               └─ place_reentry → SPECULATION  (queued per re-entry)

Sponsor milestone payouts (process_sponsor_payout) are queued separately
whenever a specific fill-count position is hit inside the matrix.

NOTE: Proportion re-entries go into SPECULATION (not back into Proportion).
      Speculation re-entries also go back into SPECULATION.
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
    from app.core.proactive import route_proactive
    from app.core.matrix_engine import place_in_matrix
    from app.models.agent import AgentPurchase
    from app.models.matrix import SystemType
    from app.models.user import User
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

        # ProActive: 30% to sponsor + 30% to supreme sponsor (odd/even routing)
        route_proactive(db, buyer, purchase.agent_tier, split.proactive)

        # Proportion matrix placement
        _, proportion_payouts, proportion_sponsor_payouts = place_in_matrix(
            db, buyer.id, purchase.agent_tier, SystemType.PROPORTION
        )

        # Speculation matrix placement
        _, speculation_payouts, speculation_sponsor_payouts = place_in_matrix(
            db, buyer.id, purchase.agent_tier, SystemType.SPECULATION
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
        for payout in proportion_payouts + speculation_payouts:
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
        for sp in proportion_sponsor_payouts + speculation_sponsor_payouts:
            process_sponsor_payout.delay(
                matrix_position_id=sp.matrix_position_id,
                owner_user_id=sp.owner_user_id,
                agent_tier=sp.agent_tier,
                system_type=sp.system_type.value,
                level=sp.level,
                amount=str(sp.amount),
            )

        total_payouts = (
            len(proportion_payouts) + len(speculation_payouts) +
            len(proportion_sponsor_payouts) + len(speculation_sponsor_payouts)
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
      Proportion  → re-enters SPECULATION
      Speculation → re-enters SPECULATION
    """
    from app.core.wallet_ops import credit_wallet
    from app.models.matrix import SystemType
    from app.models.transaction import TransactionType
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        sys_type = SystemType(system_type)
        tx_type = (
            TransactionType.PROPORTION_PAYOUT
            if sys_type == SystemType.PROPORTION
            else TransactionType.SPECULATION_PAYOUT
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

        # Re-entries always go into SPECULATION (per Luxus.docx spec)
        for i in range(reentry_count):
            place_reentry.delay(
                user_id=user_id,
                agent_tier=agent_tier,
                reentry_index=i + 1,
                source_position_id=matrix_position_id,
            )

        logger.info(
            "process_matrix_payout: user=%s tier=%s %s L%s → $%s credited, %s re-entries queued (→ SPECULATION)",
            user_id, agent_tier, system_type, level, wallet_amount, reentry_count,
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

    If the owner has no sponsor, the amount is credited to the owner themselves
    so no funds are lost.
    """
    from app.core.wallet_ops import credit_wallet
    from app.models.user import User
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
        else:
            beneficiary_id = owner.id
            notes = f"{system_type} L{level} sponsor milestone — no sponsor, credited to owner"
            logger.info(
                "process_sponsor_payout: owner=%s has no sponsor, self-crediting", owner_user_id
            )

        credit_wallet(
            db=db,
            user_id=beneficiary_id,
            agent_tier=agent_tier,
            gross_amount=Decimal(amount),
            tx_type=TransactionType.SPONSOR_MILESTONE_INCOME,
            reference_id=f"sponsor_milestone_pos_{matrix_position_id}_L{level}",
            notes=notes,
        )
        db.commit()

        logger.info(
            "process_sponsor_payout: matrix_pos=%s owner=%s tier=%s %s L%s → $%s to user=%s",
            matrix_position_id, owner_user_id, agent_tier, system_type, level, amount, beneficiary_id,
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
) -> None:
    """
    Place a re-entry into the SPECULATION matrix.
    All re-entries (from both Proportion and Speculation) go into Speculation.
    """
    from app.core.matrix_engine import place_in_matrix
    from app.models.matrix import MatrixPosition, SystemType
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        # Always re-enter into SPECULATION
        new_slot, triggered_payouts, sponsor_payouts = place_in_matrix(
            db, user_id, agent_tier, SystemType.SPECULATION
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
            "place_reentry: user=%s tier=%s → SPECULATION re-entry #%s at position %s",
            user_id, agent_tier, reentry_index, new_slot.position_number,
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
                tx_type=TransactionType.WITHDRAWAL,
                reference_id=f"withdrawal_{withdrawal_id}_refund",
                notes=f"Refund: withdrawal #{withdrawal_id} failed",
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
        db.rollback()
        logger.exception("process_withdrawal task error for withdrawal_id=%s", withdrawal_id)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(name="tasks.confirm_payment_placeholder")
def confirm_payment_placeholder(purchase_id: int) -> None:
    """Dev-only: simulate payment confirmation without NOWPayments."""
    activate_purchase.delay(purchase_id)
