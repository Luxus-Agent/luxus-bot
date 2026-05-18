# PresZ Agent Revenue Sharing Platform

## Project Overview

A multi-tier passive income platform. Users make a one-time purchase of an AI agent tier ($10 / $20 / $50 / $100). Each purchase automatically activates three revenue mechanisms that run in parallel.

**Payment model:** Deposit-first. Users top up their account balance via NOWPayments (USDT BEP-20), then spend that balance to purchase agent tiers instantly. Users can also transfer balance to other users.

## Directory Structure

```
agent-revenue-sharing-platform/
├── backend/
│   ├── migrate_v3.py            # Schema migration (sponsor_milestone_income enum value)
│   ├── app/
│   │   ├── main.py              # FastAPI app + CORS
│   │   ├── config.py            # Settings (reads ../.env)
│   │   ├── database.py          # SQLAlchemy engine + session
│   │   ├── models/
│   │   │   ├── user.py          # User + OTP fields (email verify, password reset)
│   │   │   ├── agent.py         # AgentPurchase
│   │   │   ├── matrix.py        # MatrixPosition, MatrixCounter
│   │   │   ├── wallet.py        # Wallet (MAIN + REPURCHASE + ACCOUNT types)
│   │   │   ├── transaction.py   # Transaction ledger (expanded TransactionType enum)
│   │   │   ├── deposit.py       # Deposit (account balance top-up via NOWPayments)
│   │   │   └── withdrawal.py    # WithdrawalRequest (24h hold + BEP-20 payout)
│   │   ├── core/
│   │   │   ├── matrix_engine.py # 3x3 forced matrix + sponsor milestones
│   │   │   ├── proactive.py     # 30% to sponsor + 30% to supreme sponsor, odd/even
│   │   │   ├── revenue_split.py # 60/30/10 split
│   │   │   ├── wallet_ops.py    # credit/debit_wallet() + credit/debit_account()
│   │   │   └── security.py      # JWT + password hashing
│   │   ├── services/
│   │   │   ├── nowpayments.py   # Deposit + agent invoices, IPN verify, payout API
│   │   │   └── email_service.py # SMTP email — OTP, activation, withdrawal notifications
│   │   ├── workers/
│   │   │   ├── celery_app.py    # Celery + Redis setup
│   │   │   └── tasks.py         # activate → payout → re-entry(SPECULATION) → withdrawal
│   │   ├── schemas/
│   │   │   ├── user.py          # Register (referral_code required), Login, OTP, reset
│   │   │   └── agent.py         # Purchase, Deposit, Transfer, Wallet, Withdrawal schemas
│   │   └── api/
│   │       ├── auth.py          # register / verify-email / resend / login / forgot & reset
│   │       ├── agents.py        # purchase (from balance, multiple per tier allowed) / matrix view
│   │       ├── wallet.py        # balances / transactions / withdraw (instant) / withdrawals list
│   │       ├── deposit.py       # account balance / create deposit / transfer / refund
│   │       ├── admin.py         # admin-only: users, wallets, transactions, freeze/unfreeze, credit/debit
│   │       └── payments.py      # NOWPayments IPN webhook
│   ├── create_tables.py         # One-time DB table creation (run once after setup)
│   └── migrate_v2.py            # Schema migration (new enums + deposits table)
├── .env                         # Local secrets (never commit)
├── .env.example                 # Template — copy to .env and fill in
├── requirements.txt
├── setup_db.sql                 # SQL to recreate DB user/database from scratch
├── .gitignore
└── CLAUDE.md
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python) |
| Database | PostgreSQL 18 |
| Task Queue | Celery + Redis |
| Auth | JWT (python-jose + passlib/bcrypt) |
| Payments | NOWPayments (USDT on BEP-20) |
| Email | SMTP (Gmail / any provider) |

## Database

- **Host**: localhost:5432
- **Database**: `luxus`
- **User**: `luxus`
- **Password**: `dhanush`
- **Connection string**: `postgresql://luxus:dhanush@localhost/luxus`

Tables: `users`, `agent_purchases`, `matrix_positions`, `matrix_counters`, `wallets`, `transactions`, `withdrawal_requests`, `deposits`

## Auth Flow

```
1. POST /auth/register          → creates user (sponsor referral_code REQUIRED), sends OTP
2. POST /auth/verify-email      → verifies OTP, marks email as verified
3. POST /auth/login             → returns JWT (blocked until email is verified)

Password reset:
4. POST /auth/forgot-password   → sends reset OTP (1h expiry)
5. POST /auth/reset-password    → validates OTP, sets new password

Resend:
   POST /auth/resend-verification → sends a fresh OTP
```

**Note:** Every user must register under a sponsor. The `referral_code` field is mandatory.
Only the platform root/admin user can exist without a sponsor — create it directly in the DB.

## Deposit & Purchase Flow

```
Deposit (top up account balance):
1. POST /deposit                  → creates Deposit record + NOWPayments invoice
2. User pays invoice_url (USDT BEP-20)
3. NOWPayments → POST /webhooks/nowpayments/ipn  (HMAC-SHA512 verified)
4. IPN credits user's ACCOUNT balance

Purchase (spend account balance):
5. POST /agents/purchase          → checks ACCOUNT balance >= price, deducts, queues Celery
6. Celery: activate_purchase → revenue split → matrix placement → payouts → email

Transfer (user-to-user):
   POST /deposit/transfer         → moves ACCOUNT balance from sender to recipient (by username)

Balance query:
   GET  /deposit/balance          → current spendable account balance
   GET  /deposit                  → deposit history
```

## Revenue Mechanics

### Split (on every confirmed purchase)
- **60%** → ProActive system
- **30%** → Proportion system (3x3 forced matrix)
- **10%** → Speculation system (3x3 forced matrix)

### ProActive — Updated Logic
The 60% is split into two equal halves (30% each):
- **First 30%** → Buyer's direct Sponsor
- **Second 30%** → Buyer's Supreme Sponsor (sponsor's sponsor)

**Odd / Even rule at each recipient:**
- Count how many `PROACTIVE_INCOME` transactions the recipient has already received.
- If next count is **odd** → amount goes to recipient's wallet
- If next count is **even** → amount passes to recipient's sponsor's wallet instead
- If no sponsor exists at pass-up → stays with current recipient

### Proportion & Speculation (3x3 matrix with queue)
Both use the same breadth-first ternary tree, locked via `MatrixCounter` (SELECT FOR UPDATE).

| Level | Threshold | Proportion (base $10 tier) | Speculation (base $10 tier) |
|-------|-----------|----------------------------|------------------------------|
| L1 | 3 members | $2.00 wallet + $1.00 re-entry x1 | $0.60 wallet + $0.30 re-entry x1 |
| L2 | 9 members | $7.00 wallet + $2.00 re-entries x2 | $2.10 wallet + $0.60 re-entries x2 |
| L3 | 27 members | $26.00 wallet + $3.00 re-entries x3 | $7.20 wallet + $0.90 re-entries x3 |

Higher tiers scale: Agent 2 ($20) = x2, Agent 3 ($50) = x5, Agent 4 ($100) = x10.

**Re-entry rule:** ALL re-entries (from both Proportion and Speculation) go into **SPECULATION**.

**Sponsor milestone payouts** (triggered when the Nth member fills under an ancestor):

| System | Level | Fill position | Sponsor amount (base $10) |
|--------|-------|---------------|--------------------------|
| Proportion | L2 | 5th member | $1.00 |
| Proportion | L3 | 20th member | $1.00 |
| Speculation | L2 | 5th member | $0.30 |
| Speculation | L3 | 4th member | $0.30 |
| Speculation | L3 | 20th member | $0.30 |

### Wallet rule
Every income credit → **90% main wallet** (withdrawable) + **10% repurchase reserve** (auto-hold per tier).
ACCOUNT balance (deposits/transfers) is credited at 100% — no repurchase split.

## Withdrawal Flow

```
1. POST /wallet/withdraw          → min $10, deducts from MAIN wallet, creates request
                                    sends confirmation email with 24h scheduled time
2. Celery process_withdrawal      → fires after 24h countdown
3. NOWPayments /v1/payout         → sends USDT on BEP-20 to user's BEP-20 address
4. On success → status=sent, sends "withdrawal dispatched" email
5. On failure → status=failed, refunds to MAIN wallet, sends "refund" email, retries 3x
```

`GET /wallet/withdrawals` — lists all withdrawal history for the current user.

## Email Notifications

| Event | Endpoint / Task |
|-------|----------------|
| OTP verification on register | `POST /auth/register` |
| Resend OTP | `POST /auth/resend-verification` |
| Password reset OTP | `POST /auth/forgot-password` |
| Agent purchase activated | Celery `activate_purchase` |
| Withdrawal scheduled | `POST /wallet/withdraw` |
| Withdrawal sent | Celery `process_withdrawal` (success) |
| Withdrawal failed + refunded | Celery `process_withdrawal` (failure) |

SMTP config keys: `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SENDER_EMAIL`

For Gmail use an **App Password**: `myaccount.google.com/apppasswords`

## How to Run

### Prerequisites
- Python 3.11+ in conda env `luxus`
- PostgreSQL 18 running locally
- Redis running locally on port 6379

### Setup (first time)

```bash
# 1. Fill in your .env
cp .env.example .env
# edit .env — add NOWPAYMENTS keys, SMTP credentials, etc.

# 2. Install dependencies (in luxus env)
conda activate luxus
pip install -r requirements.txt

# 3. Create DB tables (run once)
cd backend
python create_tables.py
```

### Applying v2 schema changes (existing install)

```bash
cd backend
python migrate_v2.py
```

### Applying v3 schema changes (sponsor milestone transaction type fix)

```bash
cd backend
python migrate_v3.py
```

### Applying v4 schema changes (is_admin column on users)

```bash
cd backend
python migrate_v4.py
```

### Running

```bash
# Terminal 1 — API server (from backend/)
conda activate luxus
cd backend
uvicorn app.main:app --reload

# Terminal 2 — Celery worker (from backend/)
conda activate luxus
cd backend
celery -A app.workers.celery_app worker --loglevel=info
```

API docs: http://localhost:8000/docs

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/core/matrix_engine.py` | 3x3 matrix + sponsor milestone payouts |
| `backend/app/core/proactive.py` | 30%/30% sponsor chain routing with odd/even logic |
| `backend/app/core/revenue_split.py` | 60/30/10 split calculation |
| `backend/app/core/wallet_ops.py` | credit/debit wallet + account balance functions |
| `backend/app/models/deposit.py` | Deposit model for account balance top-ups |
| `backend/app/api/deposit.py` | Deposit creation, transfer, balance query |
| `backend/app/services/nowpayments.py` | Deposit + agent invoices, IPN routing, payout API |
| `backend/app/services/email_service.py` | All transactional email templates + SMTP send |
| `backend/app/workers/tasks.py` | Celery chain: activate → payout → re-entry → withdrawal |
| `backend/app/api/auth.py` | Register (sponsor required), email verify, password reset |
| `backend/app/api/payments.py` | NOWPayments IPN webhook (deposit + agent IPNs) |
| `backend/app/api/wallet.py` | Per-tier balances, transactions, withdrawal request + history |
| `backend/migrate_v2.py` | DB migration: new enum values + deposits table |

## Dev Notes

- All financial amounts use Python `Decimal` to avoid float precision errors.
- Matrix concurrency uses PostgreSQL `SELECT FOR UPDATE` on `MatrixCounter` + ancestor rows.
- Celery tasks retry up to 3x (60s delay) on failure — safe to requeue.
- `process_withdrawal` retries up to 3x with 300s delay on payout failure.
- `POST /agents/purchase/{id}/confirm` is a dev-only endpoint (no payment needed). Remove in production.
- `APP_ENV=development` always hits the NOWPayments sandbox — no real funds used.
- Login requires email verification — unverified users get HTTP 403.
- **Sponsor is mandatory at registration.** Create the platform root/admin user directly in the DB.
- **Withdrawal minimum is $10.** Minimum transfer is $1. No maximum on withdrawals.
- **Withdrawals are instant** — no 24h hold. Payout dispatched immediately via NOWPayments.
- **Multiple agents per tier allowed** — users can purchase the same tier multiple times.
- **Inactive sponsors are skipped** in ProActive routing — income passes to supreme sponsor or buyer.
- **Re-entries always use Tier 1 ($10)** regardless of the source position's tier.
- **Auto-repurchase:** when a user's REPURCHASE wallet for a given tier accumulates >= tier price, a new agent purchase is automatically created and activated via Celery (`auto_repurchase` task).
- **Admin access:** set `is_admin=true` in DB for the root user. Admin endpoints are at `/admin/*`. Run `migrate_v4.py` first.
- Order ID prefixes: `presz_deposit_*` = account top-up, `presz_agent_*` = legacy direct purchase.
- `ACCOUNT_TIER = 0` is the sentinel agent_tier used for the account balance wallet.
