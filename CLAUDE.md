# PresZ Agent Revenue Sharing Platform

## Project Overview

A multi-tier passive income platform. Users make a one-time purchase of an AI agent tier ($10 / $20 / $50 / $100). Each purchase automatically activates three revenue mechanisms that run in parallel.

## Directory Structure

```
agent-revenue-sharing-platform/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + CORS
│   │   ├── config.py            # Settings (reads ../.env)
│   │   ├── database.py          # SQLAlchemy engine + session
│   │   ├── models/
│   │   │   ├── user.py          # User + OTP fields (email verify, password reset)
│   │   │   ├── agent.py         # AgentPurchase
│   │   │   ├── matrix.py        # MatrixPosition, MatrixCounter
│   │   │   ├── wallet.py        # Wallet (MAIN + REPURCHASE types)
│   │   │   ├── transaction.py   # Transaction ledger
│   │   │   └── withdrawal.py    # WithdrawalRequest (24h hold + BEP-20 payout)
│   │   ├── core/
│   │   │   ├── matrix_engine.py # 3×3 forced matrix + fill-count logic
│   │   │   ├── proactive.py     # Odd/even sponsor-tree routing
│   │   │   ├── revenue_split.py # 60/30/10 split
│   │   │   ├── wallet_ops.py    # credit_wallet() + debit_wallet()
│   │   │   └── security.py      # JWT + password hashing
│   │   ├── services/
│   │   │   ├── nowpayments.py   # Invoice creation, IPN verify, payout API
│   │   │   └── email_service.py # SMTP email — OTP, activation, withdrawal notifications
│   │   ├── workers/
│   │   │   ├── celery_app.py    # Celery + Redis setup
│   │   │   └── tasks.py         # activate_purchase → payout → re-entry → process_withdrawal
│   │   ├── schemas/
│   │   │   ├── user.py          # Register, Login, OTP verify, password reset schemas
│   │   │   └── agent.py         # Purchase, Wallet, Transaction, Withdrawal schemas
│   │   └── api/
│   │       ├── auth.py          # register / verify-email / resend / login / forgot & reset password
│   │       ├── agents.py        # purchase / matrix view
│   │       ├── wallet.py        # balances / transactions / withdraw / withdrawals list
│   │       └── payments.py      # checkout + NOWPayments IPN webhook
│   └── create_tables.py         # One-time DB table creation (run once after setup)
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

Tables: `users`, `agent_purchases`, `matrix_positions`, `matrix_counters`, `wallets`, `transactions`, `withdrawal_requests`

## Auth Flow

```
1. POST /auth/register          → creates user, sends OTP to email (24h expiry)
2. POST /auth/verify-email      → verifies OTP, marks email as verified
3. POST /auth/login             → returns JWT (blocked until email is verified)

Password reset:
4. POST /auth/forgot-password   → sends reset OTP (1h expiry)
5. POST /auth/reset-password    → validates OTP, sets new password

Resend:
   POST /auth/resend-verification → sends a fresh OTP
```

## Revenue Mechanics

### Split (on every confirmed purchase)
- **60%** → ProActive system
- **30%** → Proportion system (3×3 forced matrix)
- **10%** → Speculation system (3×3 forced matrix)

### ProActive (instant routing)
- Binary sponsor tree: User → Sponsor → Supreme Sponsor
- Buyer's position in sponsor's downline determines routing:
  - **Odd position** → income goes to the sponsor's wallet
  - **Even position** → income stays in the buyer's wallet

### Proportion & Speculation (3×3 matrix with queue)
Both use the same breadth-first ternary tree, locked via `MatrixCounter` (SELECT FOR UPDATE).

| Level | Threshold | Proportion (base $10 tier) | Speculation (base $10 tier) |
|-------|-----------|----------------------------|------------------------------|
| L1 | 3 members | $2.00 wallet + $1.00 re-entry ×1 | $0.60 wallet + $0.30 re-entry ×1 |
| L2 | 9 members | $7.00 wallet + $2.00 re-entries ×2 | $2.10 wallet + $0.60 re-entries ×2 |
| L3 | 27 members | $26.00 wallet + $3.00 re-entries ×3 | $7.20 wallet + $0.90 re-entries ×3 |

Higher tiers scale: Agent 2 ($20) = ×2, Agent 3 ($50) = ×5, Agent 4 ($100) = ×10.

### Wallet rule
Every income credit → **90% main wallet** (withdrawable) + **10% repurchase reserve** (auto-hold per tier).

## Payment Flow (NOWPayments)

```
1. POST /agents/purchase                  → creates AgentPurchase (status=pending)
2. POST /agents/purchase/{id}/checkout    → calls NOWPayments, returns invoice_url
3. User pays at invoice_url (USDT BEP-20)
4. NOWPayments → POST /webhooks/nowpayments/ipn  (HMAC-SHA512 verified)
5. Celery: activate_purchase → revenue split → matrix placement → payouts → email user
```

**Environment:**
- `APP_ENV=development` → NOWPayments sandbox (`api-sandbox.nowpayments.io`)
- `APP_ENV=production`  → NOWPayments live (`api.nowpayments.io`)

**Local webhook testing:** use ngrok to expose the IPN endpoint:
```bash
ngrok http 8000
# then set NOWPAYMENTS_CALLBACK_BASE=https://xxxx.ngrok.io in .env
```

## Withdrawal Flow

```
1. POST /wallet/withdraw          → deducts balance, creates WithdrawalRequest (status=pending)
                                    sends confirmation email with scheduled time
2. Celery process_withdrawal      → fires after 24h countdown
3. NOWPayments /v1/payout         → sends USDT on BEP-20 to user's address
4. On success → status=sent, sends "withdrawal dispatched" email
5. On failure → status=failed, refunds amount to wallet, sends "refund" email, retries up to 3×
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

For Gmail use an **App Password** (not your real password): `myaccount.google.com/apppasswords`

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
| `backend/app/core/matrix_engine.py` | Core 3×3 matrix placement + fill-count logic with concurrency safety |
| `backend/app/core/proactive.py` | Odd/even sponsor routing |
| `backend/app/core/revenue_split.py` | 60/30/10 split calculation |
| `backend/app/core/wallet_ops.py` | `credit_wallet()` + `debit_wallet()` — 90/10 split, balance checks |
| `backend/app/services/nowpayments.py` | Invoice creation, IPN signature verify, payout API |
| `backend/app/services/email_service.py` | All transactional email templates + SMTP send |
| `backend/app/workers/tasks.py` | Celery chain: activate → payout → re-entry → withdrawal |
| `backend/app/api/auth.py` | Register, email verify, password reset endpoints |
| `backend/app/api/payments.py` | Checkout endpoint + IPN webhook |
| `backend/app/api/wallet.py` | Balances, transactions, withdrawal request + history |

## Dev Notes

- All financial amounts use Python `Decimal` to avoid float precision errors.
- Matrix concurrency uses PostgreSQL `SELECT FOR UPDATE` on `MatrixCounter` + ancestor rows.
- Celery tasks retry up to 3× (60s delay) on failure — safe to requeue.
- `process_withdrawal` retries up to 3× with 300s delay on payout failure.
- `POST /agents/purchase/{id}/confirm` is a dev-only endpoint to trigger the engine without a real payment. Remove or protect it in production.
- `APP_ENV=development` always hits the NOWPayments sandbox — no real funds used.
- Login requires email verification — unverified users get HTTP 403.
