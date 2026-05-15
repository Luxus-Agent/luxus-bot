from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.transaction import Transaction, TransactionType
from app.core.wallet_ops import credit_wallet


def route_proactive(
    db: Session,
    buyer: User,
    agent_tier: int,
    amount: Decimal,
) -> None:
    """
    Route the ProActive portion of a purchase.

    Odd position  → income goes to the sponsor's wallet
    Even position → income stays in the buyer's wallet
    No sponsor    → income stays in the buyer's wallet

    All credits go through credit_wallet() so the 10% repurchase hold is applied.
    """
    position = buyer.sponsor_position or 1

    if buyer.sponsor_id and position % 2 == 1:
        beneficiary_id = buyer.sponsor_id
        beneficiary_tx_type = TransactionType.PROACTIVE_INCOME
        # Record the outgoing side on the buyer
        db.add(Transaction(
            user_id=buyer.id,
            agent_tier=agent_tier,
            transaction_type=TransactionType.PROACTIVE_SENT,
            amount=amount,
            reference_id=f"proactive_{buyer.id}",
            notes=f"Routed to sponsor (position {position})",
        ))
    else:
        beneficiary_id = buyer.id
        beneficiary_tx_type = TransactionType.PROACTIVE_INCOME

    credit_wallet(
        db=db,
        user_id=beneficiary_id,
        agent_tier=agent_tier,
        gross_amount=amount,
        tx_type=beneficiary_tx_type,
        reference_id=f"proactive_{buyer.id}",
    )
