# Luxus Agent Revenue Sharing Platform

## Project Overview

A multi-tier passive income platform. Users make a one-time purchase of an AI agent tier ($10 / $20 / $50 / $100). Each purchase automatically activates three revenue mechanisms that run in parallel.

**Payment model:** Deposit-first. Users top up their account balance via NOWPayments (USDT BEP-20), then spend that balance to purchase agent tiers instantly. Users can also transfer balance to other users.

## Directory Structure

```
agent-revenue-sharing-platform/
├── frontend/                    # Vite + React SPA (user + admin dashboards)
│   ├── src/
│   │   ├── api/client.js        # Axios instance with JWT interceptor + auto-logout
│   │   ├── context/AuthContext.jsx  # Auth state, login (token + /auth/me), logout
│   │   ├── components/
│   │   │   ├── Layout.jsx       # UserLayout + AdminLayout (separate nav, profile dropdown)
│   │   │   ├── ProtectedRoute.jsx   # Requires auth; allows both user and admin
│   │   │   └── AdminRoute.jsx   # Requires is_admin=true
│   │   ├── pages/
│   │   │   ├── Login.jsx / Register.jsx / VerifyEmail.jsx
│   │   │   ├── ForgotPassword.jsx / ResetPassword.jsx
│   │   │   ├── Dashboard.jsx / AgentPurchase.jsx / Matrix.jsx
│   │   │   ├── Wallet.jsx / Deposit.jsx / Transfer.jsx / Withdraw.jsx / Transactions.jsx
│   │   │   └── admin/
│   │   │       ├── AdminDashboard.jsx / AdminUsers.jsx
│   │   │       └── AdminTransactions.jsx / AdminWithdrawals.jsx
│   └── vite.config.js           # Tailwind, port 3000, /api proxy → localhost:8000
├── backend/
│   ├── seed_admin.py            # One-time admin user creation from .env credentials
│   ├── app/
│   │   ├── main.py              # FastAPI app + CORS
│   │   ├── config.py            # Settings (reads ../.env)
│   │   ├── database.py          # SQLAlchemy engine + session
│   │   ├── models/
│   │   │   ├── user.py          # User + OTP fields (email verify, password reset)
│   │   │   ├── agent.py         # AgentPurchase
│   │   │   ├── matrix.py        # MatrixPosition, MatrixCounter (SystemType: STREAM, BOOST)
│   │   │   ├── wallet.py        # Wallet (MAIN + REPURCHASE + ACCOUNT types)
│   │   │   ├── transaction.py   # Transaction ledger (TransactionType enum)
│   │   │   ├── deposit.py       # Deposit (account balance top-up via NOWPayments)
│   │   │   └── withdrawal.py    # WithdrawalRequest (instant BEP-20 payout)
│   │   ├── core/
│   │   │   ├── matrix_engine.py # 3x3 forced matrix + sponsor milestones (Stream + Boost)
│   │   │   ├── proactive.py     # Core Agent: 30% sponsor + 30% supreme, odd/even routing
│   │   │   ├── revenue_split.py # 60/30/10 split → core / stream / boost
│   │   │   ├── wallet_ops.py    # credit/debit_wallet() + credit/debit_account()
│   │   │   └── security.py      # JWT + password hashing
│   │   ├── services/
│   │   │   ├── nowpayments.py   # Deposit invoices, IPN verify, payout API
│   │   │   └── email_service.py # SMTP email — OTP, activation, withdrawal notifications
│   │   ├── workers/
│   │   │   ├── celery_app.py    # Celery + Redis setup
│   │   │   └── tasks.py         # activate → payout → re-entry(BOOST) → withdrawal
│   │   ├── schemas/
│   │   │   ├── user.py          # Register (sponsor_username required), Login, OTP, reset
│   │   │   └── agent.py         # Purchase, Deposit, Transfer, Wallet, Withdrawal schemas
│   │   └── api/
│   │       ├── auth.py          # register / check-username / verify-email / login / forgot & reset
│   │       ├── agents.py        # purchase (from balance, multiple per tier) / matrix view
│   │       ├── wallet.py        # balances / transactions / withdraw / withdrawals list
│   │       ├── deposit.py       # account balance / create deposit / transfer / refund
│   │       ├── admin.py         # admin-only: users, wallets, transactions, freeze/unfreeze
│   │       └── payments.py      # NOWPayments IPN webhook
│   ├── create_tables.py         # One-time DB table creation (run once on fresh setup)
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
| Frontend | Vite + React + Tailwind CSS |
| Backend | FastAPI (Python) |
| Database | PostgreSQL 18 |
| Task Queue | Celery + Redis |
| Auth | JWT (python-jose + passlib/bcrypt==4.0.1) |
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
1. POST /auth/register          → creates user (sponsor_username REQUIRED), sends OTP
   GET  /auth/check-username    → real-time username availability check (used by register form)
2. POST /auth/verify-email      → verifies OTP, marks email as verified
3. POST /auth/login             → returns JWT (blocked until email is verified)

Password reset:
4. POST /auth/forgot-password   → sends reset OTP (1h expiry)
5. POST /auth/reset-password    → validates OTP, sets new password

Resend:
   POST /auth/resend-verification → sends a fresh OTP
```

**Note:** Every user must register under a sponsor identified by the **sponsor's username** (not a referral code). The `sponsor_username` field is mandatory at registration.
Only the platform root/admin user can exist without a sponsor — create it directly in the DB via `seed_admin.py`.

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
   POST /deposit/transfer         → 1% fee deducted; first transfer to a new recipient requires email OTP
   POST /deposit/transfer/verify  → confirm OTP for first-time recipient; executes the transfer

Balance query:
   GET  /deposit/balance          → returns { "account_balance": float }
   GET  /deposit                  → deposit history

Withdrawal address management (required before withdrawing):
   POST /wallet/address           → register a BEP-20 address; sends email OTP
   POST /wallet/address/verify    → confirm OTP; marks address as verified
   GET  /wallet/addresses         → list user's verified addresses
   DELETE /wallet/address/{id}    → remove a registered address
```

## Revenue Mechanics

### Split (on every confirmed purchase)
- **60%** → Core Agent system
- **30%** → Stream Agent system (3x3 forced matrix, separate queue per tier)
- **10%** → Boost Agent system (3x3 forced matrix, single global queue)

### Core Agent (60%) — formerly ProActive
The 60% is split into two equal halves (30% each):
- **First 30%** → Buyer's direct Sponsor
- **Second 30%** → Buyer's Supreme Sponsor (sponsor's sponsor)

**Odd / Even rule at each recipient:**
- Count how many `CORE_INCOME` transactions the recipient has already received.
- If next count is **odd** → amount goes to recipient's wallet
- If next count is **even** → amount passes to recipient's sponsor's wallet instead
- If no upline to pass to → stays with recipient
- If sponsor / supreme sponsor does not exist → goes to **company (platform profit)**

### Stream Agent (30%) — formerly Proportion
Uses a 3x3 breadth-first matrix. Each tier has its **own separate queue**.
Locked via `MatrixCounter` (SELECT FOR UPDATE).

| Level | Threshold | Wallet (base $10) | Re-entries (base) | Sponsor milestone |
|-------|-----------|-------------------|-------------------|------------------|
| L1 | 3 members | $2.00 | 1 × tier_multiplier | — |
| L2 | 9 members | $5.00 | 2 × tier_multiplier | 5th member → $1.00 |
| L3 | 27 members | $13.00 | 3 × tier_multiplier | 20th member → $1.00 |

Remaining pool after payouts + re-entries + sponsor milestone → **platform profit**.

**Tier multipliers:** Agent 1 = 1×, Agent 2 = 2×, Agent 3 = 5×, Agent 4 = 10×
(wallet amounts and re-entry counts both scale by multiplier)

**Re-entry rule:** All Stream re-entries go into the **Boost** queue (not back into Stream).
Only one real entry per user in the Stream queue at a time — re-entries are **dummy** (fill slots, no payout).

### Boost Agent (10%) — formerly Speculation
Uses the same 3x3 matrix format. **Single global queue** (no per-tier split). Always placed at `agent_tier=1`.

| Level | Threshold | Wallet | Re-entry | Sponsor milestone |
|-------|-----------|--------|----------|------------------|
| L1 | 3 members | $0.60 | 1 × $0.30 | — |
| L2 | 9 members | $1.50 | 2 × $0.60 | 5th member → $0.30 |
| L3 | 27 members | $4.90 | 3 × $0.90 | 4th → $0.30, 20th → $0.30 |

Remaining pool after payouts → **platform profit**.

**Key difference from Stream:** Boost Agent positions are **NOT dummy** — all positions (including re-entries from Stream and Boost) receive full wallet payouts when their level fills.

**Re-entry rule:** All re-entries (from both Stream and Boost) go back into the single Boost queue as real (non-dummy) positions.

### Wallet rule
Every income credit → two separate 10% deductions:
1. **10% software fee** → platform profit (not credited to any user)
2. **10% repurchase reserve** (of the remaining 90%) → held in REPURCHASE wallet per tier

Effective split of gross income: **81% main wallet** (withdrawable) + **9% repurchase** + **10% platform fee**.
ACCOUNT balance (deposits/transfers) is credited at **100%** — no deductions.

### Auto-repurchase
When a user's REPURCHASE wallet for a given tier accumulates >= tier price, a new agent purchase is automatically created and activated via Celery (`auto_repurchase` task).

## Withdrawal Flow

```
1. POST /wallet/withdraw          → min $10, deducts from MAIN wallet, creates request
2. NOWPayments /v1/payout         → sends USDT on BEP-20 to user's verified BEP-20 address
3. On success → status=sent, sends "withdrawal dispatched" email
4. On failure → status=failed, refunds to MAIN wallet, sends "refund" email, retries 3x
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

### Setup (first time — fresh install)

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

# 4. Seed the admin user (run once)
python seed_admin.py
```

No migration scripts are needed on a fresh install — `create_tables.py` creates all tables with the current schema.

### Running the backend

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

### Running the frontend

```bash
cd frontend
npm install      # first time only
npm run dev      # starts on port 3000
```

### Seeding the admin user

```bash
cd backend
python seed_admin.py
```

Admin credentials are read from `.env` (`ADMIN_EMAIL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`).
Safe to re-run — exits early if an admin already exists.

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/core/matrix_engine.py` | 3x3 matrix + sponsor milestones (Stream + Boost) |
| `backend/app/core/proactive.py` | Core Agent: 30%/30% sponsor chain routing with odd/even logic |
| `backend/app/core/revenue_split.py` | 60/30/10 split → core / stream / boost |
| `backend/app/core/wallet_ops.py` | credit/debit wallet + account balance functions |
| `backend/app/models/matrix.py` | MatrixPosition, MatrixCounter, SystemType (STREAM, BOOST) |
| `backend/app/models/transaction.py` | TransactionType enum (CORE_INCOME, STREAM_PAYOUT, BOOST_PAYOUT, etc.) |
| `backend/app/models/deposit.py` | Deposit model for account balance top-ups |
| `backend/app/api/deposit.py` | Deposit creation, transfer, balance query |
| `backend/app/api/auth.py` | Register (sponsor_username), check-username, email verify, password reset |
| `backend/app/services/nowpayments.py` | Deposit invoices, IPN routing, payout API |
| `backend/app/services/email_service.py` | All transactional email templates + SMTP send |
| `backend/app/workers/tasks.py` | Celery chain: activate → payout → re-entry(BOOST) → withdrawal |
| `backend/app/api/payments.py` | NOWPayments IPN webhook (deposit IPNs) |
| `backend/app/api/wallet.py` | Per-tier balances, transactions, withdrawal request + history |

## Dev Notes

- All financial amounts use Python `Decimal` to avoid float precision errors.
- Matrix concurrency uses PostgreSQL `SELECT FOR UPDATE` on `MatrixCounter` + ancestor rows.
- Celery tasks retry up to 3x (60s delay) on failure — safe to requeue.
- `process_withdrawal` retries up to 3x with 300s delay on payout failure.
- `POST /agents/purchase/{id}/confirm` is a dev-only endpoint (no payment needed). Remove in production.
- `APP_ENV=development` always hits the NOWPayments sandbox — no real funds used.
- Login requires email verification — unverified users get HTTP 403.
- **Sponsor is identified by username** at registration (`sponsor_username` field). The register form also does a live debounced username availability check via `GET /auth/check-username`.
- **Root/admin user has no sponsor** — created directly in DB via `seed_admin.py`.
- **Withdrawal minimum is $10.** Minimum transfer is $1. No maximum on withdrawals.
- **Withdrawals are instant** — payout dispatched immediately via NOWPayments.
- **Withdrawal addresses must be pre-verified** — register via `POST /wallet/address`, confirm OTP via `POST /wallet/address/verify`.
- **Transfer fee is 1%** — sender debited full amount; recipient receives 99%.
- **First-time transfer to a new recipient requires email OTP.**
- **Multiple agents per tier allowed** — users can purchase the same tier multiple times.
- **Inactive sponsors are skipped** in Core Agent routing — income passes to supreme sponsor or goes to platform.
- **Stream re-entries are dummy** — they fill matrix slots but do not receive wallet payouts. Only one real Stream entry per user at a time.
- **Boost re-entries are NOT dummy** — all positions in the Boost queue (including re-entries from Stream/Boost) receive full payouts when their level fills.
- **Re-entry count scales by tier multiplier** for Stream Agent (Agent 2 = 2×, Agent 3 = 5×, Agent 4 = 10×).
- **All re-entries go into the single Boost queue** at agent_tier=1, regardless of source tier.
- **Auto-repurchase:** when REPURCHASE wallet >= tier price, a new purchase is auto-activated via Celery.
- **Two separate 10% deductions** on every wallet credit: 10% software fee (platform profit) + 10% repurchase reserve. Effective user take = 81% of gross income credited.
- **`/deposit/balance` returns `{ "account_balance": float }`** — use key `account_balance`, not `balance`.
- **Admin access:** created via `seed_admin.py`. Admin endpoints at `/admin/*`. Admin logs in through the same `/login` page and is routed to `/admin` automatically.
- **Frontend auth:** two-step login — POST `/auth/login` for JWT, then GET `/auth/me` for full profile (includes `is_admin`).
- **bcrypt pinned to 4.0.1** — bcrypt 5.x breaks passlib's 72-byte wrap detection; do not upgrade.
- `ACCOUNT_TIER = 0` is the sentinel agent_tier used for the account balance wallet.
