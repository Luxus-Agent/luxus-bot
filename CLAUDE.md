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
│   │   │   ├── withdrawal.py    # WithdrawalRequest (instant BEP-20 payout)
│   │   │   └── platform_setting.py # Single-row platform state (global freeze kill switch)
│   │   ├── core/
│   │   │   ├── matrix_engine.py # 3x3 forced matrix + Stream & Boost 10% sponsor completion-share
│   │   │   ├── proactive.py     # Core Agent: 30% sponsor + 30% supreme, odd/even routing
│   │   │   ├── revenue_split.py # 60/30/10 split → core / stream / boost
│   │   │   ├── wallet_ops.py    # credit/debit_wallet() + credit/debit_account() + withdrawable/earnings
│   │   │   ├── platform_state.py # Freeze get/set helpers
│   │   │   └── security.py      # JWT + password hashing
│   │   ├── services/
│   │   │   ├── nowpayments.py   # Deposit invoices, IPN verify, payout API
│   │   │   └── email_service.py # SMTP email — OTP, activation, withdrawal notifications
│   │   ├── workers/
│   │   │   ├── celery_app.py    # Celery + Redis setup
│   │   │   └── tasks.py         # activate → payout → re-entry (Stream=dummy same queue / Boost=real) → withdrawal
│   │   ├── schemas/
│   │   │   ├── user.py          # Register (sponsor_username), Login (username+password), OTP, reset
│   │   │   └── agent.py         # Purchase, Deposit, Transfer, Wallet, Withdrawal, Admin treasury/freeze schemas
│   │   └── api/
│   │       ├── auth.py          # register / check-username / verify-email / login (username) / forgot & reset
│   │       ├── agents.py        # purchase (from balance, one per tier, sequential 1→2→3→4) / matrix view
│   │       ├── wallet.py        # balances / transactions / income-daily / withdraw (combined balance) / withdrawals
│   │       ├── deposit.py       # account balance / create deposit / transfer / refund
│   │       ├── admin.py         # admin-only: users + summary, transactions, withdrawals, freeze/unfreeze, treasury (generate/transfer), platform freeze
│   │       ├── platform.py      # GET /platform/status (freeze state for any logged-in user)
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
3. POST /auth/login             → login with USERNAME + password → returns JWT (blocked until email is verified)

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

| Level | Threshold | Wallet (base $10) | Re-entries | Sponsor share (base $10) |
|-------|-----------|-------------------|------------|--------------------------|
| L1 | 3 members | $2.00 | 1 × $1.00 | — |
| L2 | 9 members | $5.00 | 2 × $1.00 | $0.90 on completion (10% of $9 gross) |
| L3 | 27 members | $13.00 | 3 × $1.00 | $2.70 on completion (10% of $27 gross) |

Remaining pool after payouts + re-entries + sponsor share → **platform profit**.

**Tier multipliers:** Agent 1 = 1×, Agent 2 = 2×, Agent 3 = 5×, Agent 4 = 10×
Wallet, per-re-entry amount, and sponsor share all scale by multiplier.
**Re-entry COUNT is fixed at 1/2/3 across all tiers** (only the $ per re-entry scales).

**Stream sponsor share:** At L2 and L3, an *extra* 10% of the level's gross is credited to the owner's sponsor on level completion — paid from the platform pool, not deducted from the owner's wallet. L1 has no sponsor share.

**Re-entry rule:** Stream re-entries are **dummy** positions placed back into the **same tier's Stream queue** (per the client matrix diagram `A·B·C·D·A1·E·F·B1·…`). They fill slots to advance the queue, earn no payout, and spawn no further re-entries. Only one real entry per user in the Stream queue at a time. Stream does **not** feed Boost.

### Boost Agent (10%) — formerly Speculation
Uses the same 3x3 matrix format. **Single global queue** (no per-tier split). Always placed at `agent_tier=1`.

| Level | Threshold | Wallet | Re-entry | Sponsor share |
|-------|-----------|--------|----------|---------------|
| L1 | 3 members | $0.60 | 1 × $0.30 | — |
| L2 | 9 members | $1.50 | 2 × $0.30 | $0.27 on completion (10% of $2.70 gross) |
| L3 | 27 members | $3.60 | 3 × $0.30 | $0.81 on completion (10% of $8.10 gross) |

Remaining pool after payouts + re-entries + sponsor share → **platform profit**.

**Boost sponsor share:** identical model to Stream — at L2 and L3 an *extra* 10% of the level's gross is credited to the owner's sponsor on level completion, paid from the platform pool (not deducted from the owner's wallet). The older per-position milestone model (5th/4th/20th member → $0.30) was **retired** in the latest client spec. L1 has no sponsor share.

**Key difference from Stream:** Boost Agent positions are **NOT dummy** — all positions (including Boost's own re-entries) receive full wallet payouts when their level fills.

**Re-entry rule:** Boost re-entries are real (non-dummy) positions placed back into the single Boost queue. (Stream no longer feeds Boost — each queue self-cycles its own re-entries.)

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
| `backend/app/core/matrix_engine.py` | 3x3 matrix + Stream & Boost 10% sponsor share on level completion |
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
- **One purchase per tier, bought in order** — each tier can be purchased only once, and tiers must be bought sequentially 1 → 2 → 3 → 4 (cannot skip ahead). Auto-repurchase is the only exception (it activates a tier directly, bypassing this gate).
- **Inactive sponsors are skipped** in Core Agent routing — income passes to supreme sponsor or goes to platform.
- **Stream re-entries are dummy** — they are placed back into the **same tier's Stream queue**, fill matrix slots, do not receive wallet payouts, and spawn no further re-entries. Only one real Stream entry per user at a time.
- **Boost re-entries are NOT dummy** — all positions in the Boost queue (including Boost's own re-entries) receive full payouts when their level fills.
- **Stream re-entry count is FIXED at 1/2/3 for L1/L2/L3** across all tiers — only the per-re-entry $ amount scales by tier multiplier (Agent 2 = $2 per re-entry, Agent 3 = $5, Agent 4 = $10).
- **Stream sponsor income (L2/L3) is paid on level completion as 10% × level gross × tier_multiplier** — L2 base $0.90, L3 base $2.70. Not a position-fill milestone. Paid extra from the platform pool; owner's wallet credit is unaffected.
- **Boost sponsor income (L2/L3) uses the same completion-share model** — L2 $0.27 (10% of $2.70 gross), L3 $0.81 (10% of $8.10 gross). Boost is always tier 1, so no multiplier scaling. The old per-position milestone model (5th/4th/20th member → $0.30) is retired. Boost L3 wallet is **$3.60** (latest client spec, down from $4.90).
- **Each queue self-cycles its own re-entries:** Stream re-entries (dummy) re-enter the same tier's Stream queue; Boost re-entries (real) re-enter the single Boost queue at agent_tier=1. Stream does not feed Boost.
- **Auto-repurchase:** when REPURCHASE wallet >= tier price, a new purchase is auto-activated via Celery.
- **Two separate 10% deductions** on every wallet credit: 10% software fee (platform profit) + 10% repurchase reserve. Effective user take = 81% of gross income credited.
- **`/deposit/balance` returns `{ "account_balance": float }`** — use key `account_balance`, not `balance`.
- **Login is by username + password** (not email) — for both regular users and admin. `UserLogin` takes `username`; the frontend Login form has a Username field.
- **Admin access:** created via `seed_admin.py`. Admin endpoints at `/admin/*`. Admin logs in through the same `/login` page and is routed to `/admin` automatically. Admin pages (including Profile) render the admin sidebar.
- **Frontend auth:** two-step login — POST `/auth/login` (username + password) for JWT, then GET `/auth/me` for full profile (includes `is_admin`).
- **Platform freeze (global kill switch):** admin can freeze all user money-movement (deposit / withdraw / transfer / purchase) via `POST /admin/platform/freeze` (reason optional, admin-only) and lift it via `POST /admin/platform/unfreeze`. While frozen, guarded user endpoints return HTTP 423; admins bypass. State lives in the single-row `platform_settings` table. Users poll `GET /platform/status` (no reason exposed); admins read `GET /admin/platform/status` (full audit). Frontend shows a red banner + a Freeze/Frozen toggle in the admin top bar.
- **Admin Treasury (separate from user flows):** `POST /admin/generate` mints funds into the admin's own account balance (for off-platform payments — cash/GPay/cheque/crypto, NOT a deposit); `POST /admin/transfer` sends treasury funds to any user by username (no fee, instant); `GET /admin/treasury/summary` returns account_balance / total_generated / total_sent / total_invested / total_deposited / **platform_profit**. Admin nav has a Treasury group (Generate, Send to User) and no longer reuses the user Wallet/Withdraw pages.
- **Platform profit (realized):** `platform_profit` = SUM(`SOFTWARE_FEE`) + SUM(`PLATFORM_PROFIT`). `PLATFORM_PROFIT` ledger entries are written at each realization point: matrix level-completion residual (`matrix_engine.place_in_matrix`), Core amount retained when a buyer has no sponsor (`proactive._route_half`), and the 1% transfer fee (`deposit._execute_transfer`). Software fees stay as their own `SOFTWARE_FEE` rows. The admin dashboard's "Platform Profit" card shows this. Historical events were backfilled once via `backend/backfill_platform_profit.py` (idempotent). Pending (uncompleted) matrix money is intentionally NOT counted — only realized profit.
- **Admin user management:** per-user expandable summary (agents bought, account balance, revenue generated) via `GET /admin/users/{id}/summary`; freeze/unfreeze per user; no credit/debit wallet UI; admin's own row shows no controls. `GET /admin/transactions` resolves each transaction's owner username.
- **Transfer recipient validation:** both user and admin transfer forms validate the recipient username live (debounced, via `GET /auth/check-username`) — the recipient must exist; self-transfer is blocked client-side.
- **bcrypt pinned to 4.0.1** — bcrypt 5.x breaks passlib's 72-byte wrap detection; do not upgrade.
- `ACCOUNT_TIER = 0` is the sentinel agent_tier used for the account balance wallet.
