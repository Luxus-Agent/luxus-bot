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
│   │   ├── logging_config.py    # Central timestamped logging setup (LOG_LEVEL)
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
│   │       ├── admin.py         # admin-only: users + summary, transactions, withdrawals, freeze/unfreeze, treasury (transfer), platform freeze
│   │       ├── platform.py      # GET /platform/status (freeze state for any logged-in user)
│   │       ├── distribution.py  # GET /distribution/wallet-map — TokenPocket/MultiSender consolidated endpoint
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
1. POST /auth/register          → creates user (sponsor_username REQUIRED, optional BEP-20 wallet_address), sends OTP
   GET  /auth/check-username    → real-time check used for BOTH username availability (must be free)
                                  and live sponsor validation on the register form (sponsor must exist = inverted)
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
The 60% is split into two equal halves (30% each), routed up the sponsor chain
with **compression** (see below):
- **First 30%** → first eligible upline
- **Second 30%** → next eligible upline above the first

Two rules apply **together** in the Core Agent (and only here): compression
decides *who* is a valid recipient, then odd/even decides whether that recipient
keeps the amount or passes it up.

**Compression format (Core Agent only)** — tier-qualified routing:
- An upline only **qualifies** for Core income from a purchase if their own
  **highest active purchased tier ≥ the tier the buyer just purchased**.
- Uplines who bought a lower tier (or own no active agent, or are frozen) are
  **skipped** — the income compresses *past* them up the sponsor chain to the
  next eligible upline.
- Example (client slide "Compression format in Core Agent"): chain
  `Admin $100 → A $100 → B $10 → C $10 → D $20 → E $100`. When **E buys $100**
  (tier 4), uplines **D ($20), C ($10), B ($10) are all skipped** because they
  haven't bought the $100 tier; income lands on **A ($100)** and the next
  eligible upline (**Admin, $100**).
- If **no eligible upline** exists for a half → goes to **company (platform profit)**
  (not credited back to the buyer).

**Odd / Even rule at each eligible recipient** (tracked by `User.core_route_count`):
- Each recipient has a **targeting counter** incremented on every targeting — whether the amount is kept (odd) or passed up (even). Counting only kept credits (the old behaviour) left a recipient stuck on "even" forever after their first pass-up.
- If next count is **odd** → amount goes to recipient's wallet
- If next count is **even** → amount passes **up to the next ELIGIBLE upline** above the recipient (the pass-up is compressed too — ineligible uplines are skipped)
- If no eligible upline to pass to → stays with recipient

### Stream Agent (30%) — formerly Proportion
Uses a 3x3 breadth-first matrix. Each tier has its **own separate queue**.
Locked via `MatrixCounter` (SELECT FOR UPDATE).

| Level | Threshold | Wallet (base $10) | Re-entries | Sponsor share (base $10) |
|-------|-----------|-------------------|------------|--------------------------|
| L1 | 3 members | $2.00 | 1 × $1.00 | — |
| L2 | 9 members | $5.00 | 3 × $1.00 | $0.90 on completion (10% of $9 gross) |
| L3 | 27 members | $13.00 | 9 × $1.00 | $2.70 on completion (10% of $27 gross) |

Remaining pool after payouts + re-entries + sponsor share → **platform profit**.

**Tier multipliers:** Agent 1 = 1×, Agent 2 = 2×, Agent 3 = 5×, Agent 4 = 10×
Wallet, per-re-entry amount, and sponsor share all scale by multiplier.
**Re-entry COUNT is fixed at 1/3/9 across all tiers** (L1=1, L2=3, L3=9 — total 13 per full cycle, per the client doc "every Nth income spawns a re-entry"; only the $ per re-entry scales).

**Stream sponsor share:** At L2 and L3, an *extra* 10% of the level's gross is credited to the owner's sponsor on level completion — paid from the platform pool, not deducted from the owner's wallet. L1 has no sponsor share.

**Re-entry rule:** Stream re-entries are **dummy** positions placed back into the **same tier's Stream queue** (per the client matrix diagram `A·B·C·D·A1·E·F·B1·…`). They fill slots to advance the queue, earn no payout, and spawn no further re-entries. Only one real entry per user in the Stream queue at a time. Stream does **not** feed Boost.

### Boost Agent (10%) — formerly Speculation
Uses the same 3x3 matrix format. **Single global queue** (no per-tier split). Always placed at `agent_tier=1`.

| Level | Threshold | Wallet | Re-entry | Sponsor share |
|-------|-----------|--------|----------|---------------|
| L1 | 3 members | $0.60 | 1 × $0.30 | — |
| L2 | 9 members | $1.50 | 3 × $0.30 | $0.27 on completion (10% of $2.70 gross) |
| L3 | 27 members | $3.60 | 9 × $0.30 | $0.81 on completion (10% of $8.10 gross) |

Remaining pool after payouts + re-entries + sponsor share → **platform profit**.

**Boost sponsor share:** identical model to Stream — at L2 and L3 an *extra* 10% of the level's gross is credited to the owner's sponsor on level completion, paid from the platform pool (not deducted from the owner's wallet). The older per-position milestone model (5th/4th/20th member → $0.30) was **retired** in the latest client spec. L1 has no sponsor share.

**Key difference from Stream:** Boost Agent positions are **NOT dummy** — all positions (including Boost's own re-entries) receive full wallet payouts when their level fills.

**Re-entry rule:** Boost re-entries are real (non-dummy) positions placed back into the single Boost queue. (Stream no longer feeds Boost — each queue self-cycles its own re-entries.)

### Wallet rule
Every income credit → two deductions, **both computed off the gross**:
1. **10% software fee** (of gross) → platform profit (not credited to any user)
2. **20% repurchase reserve** (of gross) → held in REPURCHASE wallet per tier

Effective split of gross income: **70% main wallet** (withdrawable) + **20% repurchase** + **10% platform fee**.
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

## TokenPocket / MultiSender Distribution Endpoint

A **single consolidated, read-only** endpoint the frontend/blockchain team uses to drive the
TokenPocket DApp + MultiSender contract (per the client's "Decentralized Deposit & Distribution
System" spec, Section 6). The backend does **not** integrate TokenPocket — it only tells the
frontend *where the money should go*.

```
GET /distribution/wallet-map          → JWT auth. Returns, for the resolved user:
   • their own wallet_address + profit, AND
   • the downline subtree under them, each user with wallet_address + profit.
   Query params:
     username=<name>   → admin-only: build the map for another user (regular users always get their own)
     direct_only=true  → only level-1 referrals instead of the full sponsor subtree
     limit / offset    → pagination over the flattened downline (default/max 500)
```

- **Response is JSON** (not a bare list) so the root `user`, the paginated `downline.users[]`, and
  metadata travel together. Each user entry: `user_id, username, level` (null for root, 1 = direct),
  `wallet_address, wallet_address_source` (`registration` | `verified` | `null`), `has_wallet_address`,
  `is_active`, and a `profit` block: `total_earned, main_balance, repurchase_balance, account_balance,
  **withdrawable**` (= main + account).
- **Distribute against `profit.withdrawable`** — it mirrors the Withdraw page's combined balance
  (`get_withdrawable_balance`). Skip rows where `has_wallet_address` is false.
- **Real-time, no admin approval** — amounts are summed live from the ledger/wallets on every call.
- **Wallet address** comes from `User.wallet_address` (collected at registration); when empty it falls
  back to the user's most recent **verified** `WalletAddress`. Pre-existing users with neither show
  `wallet_address: null`.
- **Performance:** wallets, lifetime income, and fallback addresses are each one batched, grouped
  query over the page of user ids (no N+1), so it stays fast on deep trees.
- Lives in `app/api/distribution.py`; read-only — it never moves funds.

### On-chain pack purchase (BEP-20 USDT) — `POST /distribution/pack/purchase` + `/pack/status`

A **separate on-chain rail** from the deposit-first + Core/Stream/Boost matrix engine. The
frontend pays the upline split **directly on-chain** from the buyer's connected wallet (one
batched MultiSender call); the backend (1) returns the validated recipient split and (2)
records the outcome. **No internal Wallet balances are credited/debited on this rail** — the
on-chain transfer *is* the payout. On success it DOES, however, (a) create an **active
`AgentPurchase` ownership row** so the rest of the app (purchase-page "OWNED", the
sequential-unlock gate, and Core-eligibility for future on-chain splits) recognizes the
buyer, and (b) write **reporting-only `Transaction` rows** (buyer `agent_purchase` expense +
each upline's `core_income`) so transaction history and the dashboard analytics reflect the
activity. These rows carry no wallet balance. (Lives in `app/api/distribution.py`; split logic
in `app/core/pack_payout.py`; record in `app/models/pack_purchase.py` → table `pack_purchases`.)

```
POST /distribution/pack/purchase   → JWT. Body: { "pack_name": "Agent 1", "amount"?: 10 }
   Returns { purchase_id, currency, network, token_contract, decimals, recipients[] }
   recipients: { role: "buyer"|"upline"|"platform_fee", level, wallet_address,
                 has_wallet_address, amount, (user_id, username for buyer/upline) }
POST /distribution/pack/status     → JWT. Body: { purchase_id, status:"success"|"failed",
                                                   tx_hash?, failure_reason? }
   Returns { purchase_id, status, recorded_at }
```

- **Split rule = Core Agent rule ONLY** (client decision): 60% of the price → two 30% halves
  to the **first two ELIGIBLE uplines** (eligible = active **and** highest active tier ≥ buyer's
  tier; compression + odd/even via `User.core_route_count`). The remaining **40% → platform fee**.
  Stream/Boost matrix mechanics are **not** used on this rail.
- **Amounts sum to the pack price** and are the FULL on-chain amounts (the internal 70/20/10
  wallet deductions do **not** apply here — nothing hits internal wallets). Example $10 pack with
  two eligible uplines: `upline L1 $3 + upline L2 $3 + platform_fee $4`.
- **Missing/ineligible upline → platform** (client decision): a half with no eligible recipient
  (or whose recipient has no valid BEP-20 address) is folded into the `platform_fee` amount, so
  the split always sums to the price. `buyer` entry is informational (`amount: 0`, address returned
  so the FE can confirm it matches the connected wallet).
- **Odd/even counter** is `User.core_route_count` (shared with the Core Agent) and is advanced at
  **purchase-creation** time (API 1). A later on-chain failure leaves it slightly advanced — a
  harmless alternation drift. To isolate the rails, give it a dedicated counter column.
- **API 2** marks the `pack_purchases` row `success` (stores `tx_hash`) or `failed` (stores
  `failure_reason`); it is idempotent-guarded (re-recording a finalized order → 400). Optional
  on-chain `tx_hash` verification is stubbed behind `settings.VERIFY_ONCHAIN_TX` (off by default).
- **On success, API 2 also reflects the purchase internally** (`_mirror_onchain_ledger` +
  ownership row, both PENDING-guarded so they run once): an active `AgentPurchase` row (no Celery
  revenue engine queued, dup-tier guarded) + reporting-only `Transaction` rows (buyer
  `agent_purchase`, each upline `core_income`). **No Wallet rows are touched** — funds live
  on-chain in users' own wallets, so the internal main/repurchase wallets and withdrawable
  balance stay $0 on this rail. Stream/Boost/repurchase/software-fee mechanics do not run here.
- **Config** (`config.py`, override in `.env`): `PAYOUT_CURRENCY` (USDT), `PAYOUT_NETWORK` (BEP-20),
  `USDT_CONTRACT` (default `0xb2681F1CA80e080827d5f275648D2d2e2684f0C8`), `USDT_DECIMALS` (18),
  `PLATFORM_FEE_WALLET` (**set before go-live** — null until then), `VERIFY_ONCHAIN_TX`.
- **Schema setup:** `cd backend && python migrate_v15.py` (idempotent — creates `pack_purchases`);
  `create_tables.py` covers fresh installs.
- **Frontend live on-chain balance:** `frontend/src/hooks/useUsdtBalance.js` reads the connected
  wallet's live USDT balance (BSC, via wagmi `balanceOf`, reading decimals on-chain). Shown as the
  **"Wallet Balance"** card on the Dashboard, Wallet, and Buy Agents pages. Requires
  `VITE_USDT_ADDRESS` (frontend `.env`) to **match the backend `USDT_CONTRACT`** — otherwise the
  card reads a different token and shows $0. Other frontend on-chain envs: `VITE_MULTISENDER_ADDRESS`,
  `VITE_USDT_DECIMALS`, `VITE_REOWN_PROJECT_ID` (WalletConnect).

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
| `backend/app/api/distribution.py` | `GET /distribution/wallet-map` (accrued wallet+profit map) + `POST /distribution/pack/purchase` & `/pack/status` (on-chain BEP-20 pack rail) |
| `backend/app/core/pack_payout.py` | On-chain pack split (Core rule: 60% → 2 eligible uplines, 40% → platform; missing→platform). No wallet writes |
| `backend/app/models/pack_purchase.py` | `PackPurchase` — on-chain pack order record (pending/success/failed + tx_hash + recipients snapshot) |

## Dev Notes

- All financial amounts use Python `Decimal` to avoid float precision errors.
- Matrix concurrency uses PostgreSQL `SELECT FOR UPDATE` on `MatrixCounter` + ancestor rows.
- Celery tasks retry up to 3x (60s delay) on failure — safe to requeue.
- `process_withdrawal` retries up to 3x with 300s delay on payout failure.
- `POST /agents/purchase/{id}/confirm` is a dev-only endpoint (no payment needed). Remove in production.
- `APP_ENV=development` always hits the NOWPayments sandbox — no real funds used.
- Login requires email verification — unverified users get HTTP 403.
- **Sponsor is identified by username** at registration (`sponsor_username` field). The register form does a live debounced username availability check via `GET /auth/check-username`, and a **live sponsor-existence check** against the *same* endpoint inverted (`available:false` = username taken = sponsor exists = valid; `available:true` = no such user = invalid). Submit is blocked on an invalid sponsor.
- **Root/admin user has no sponsor** — created directly in DB via `seed_admin.py`.
- **BEP-20 wallet address at registration:** `User.wallet_address` (nullable column) is collected on the register form for the TokenPocket distribution flow. The register schema validates it as `0x` + 40 hex chars; it's **optional** on the backend (so existing flows don't break) but the frontend form makes it required with live validation. Exposed via `/auth/me` and `UserOut`. Existing DBs: run `cd backend && python migrate_v14.py` (idempotent — adds the nullable `users.wallet_address` column); `create_tables.py` covers fresh installs.
- **TokenPocket distribution map:** `GET /distribution/wallet-map` (`app/api/distribution.py`) is the single consolidated, read-only endpoint that returns a user + their downline with each one's wallet address and profit, for the frontend MultiSender. Distribute against `profit.withdrawable`. See the "TokenPocket / MultiSender Distribution Endpoint" section above.
- **On-chain pack purchase:** `POST /distribution/pack/purchase` + `POST /distribution/pack/status` (`app/api/distribution.py`) are a **separate on-chain (BEP-20 USDT) rail** — the frontend pays the upline split directly from the buyer's wallet; the backend returns the validated split and records the outcome. Split = **Core rule only** (60% → two 30% halves to the first two eligible uplines via `app/core/pack_payout.py`, 40% → platform fee; missing/ineligible upline → platform, so it sums to the pack price). Order record in `pack_purchases` (`app/models/pack_purchase.py`). On success it also creates an **active `AgentPurchase` ownership row** (no Celery, dup-tier guarded) and **reporting-only `Transaction` rows** (buyer `agent_purchase` + each upline `core_income`) via `_mirror_onchain_ledger` so the purchase shows as OWNED and appears in transaction history + the dashboard income chart — but **no internal Wallet balances are credited** (the on-chain transfer is the payout; main/repurchase/withdrawable stay $0, and Stream/Boost/repurchase don't run on this rail). Migration: `python migrate_v15.py`. See the "On-chain pack purchase" subsection above.
- **On-chain wallet balance display:** the "Wallet Balance" card on Dashboard / Wallet / Buy Agents pages shows the connected wallet's **live on-chain USDT** (via `frontend/src/hooks/useUsdtBalance.js`, wagmi `balanceOf`), not an internal balance. It needs `VITE_USDT_ADDRESS` (frontend `.env`) to **match the backend `USDT_CONTRACT`**; a mismatch makes the card read a different token and show $0. Restart the Vite dev server after changing `.env`.
- **Withdrawal minimum is $10.** Minimum transfer is $1. No maximum on withdrawals.
- **Withdrawals are instant** — payout dispatched immediately via NOWPayments.
- **Withdrawal addresses must be pre-verified** — register via `POST /wallet/address`, confirm OTP via `POST /wallet/address/verify`.
- **Transfer fee is 1%** — sender debited full amount; recipient receives 99%.
- **First-time transfer to a new recipient requires email OTP.**
- **One purchase per tier, bought in order** — each tier can be purchased only once, and tiers must be bought sequentially 1 → 2 → 3 → 4 (cannot skip ahead). Auto-repurchase is the only exception (it activates a tier directly, bypassing this gate).
- **Inactive sponsors are skipped** in Core Agent routing — income passes to supreme sponsor or goes to platform.
- **Core Agent compression (Core only):** an upline qualifies for Core income only if their **highest active purchased tier ≥ the buyer's purchased tier**. Lower-tier / inactive / no-agent uplines are skipped and the income compresses up the sponsor chain to the next eligible upline. The two 30% halves go to the first eligible upline and the next eligible upline above it; even-count pass-ups also compress to the next eligible upline; no eligible upline → platform profit. Implemented in `proactive.py` via `_highest_active_tier` / `_is_eligible` / `_next_eligible_upline`. Compression applies to the Core Agent ONLY — Stream and Boost matrices are unaffected.
- **Stream re-entries are dummy** — they are placed back into the **same tier's Stream queue**, fill matrix slots, do not receive wallet payouts, and spawn no further re-entries. Only one real Stream entry per user at a time.
- **Boost re-entries are NOT dummy** — all positions in the Boost queue (including Boost's own re-entries) receive full payouts when their level fills.
- **Stream re-entry count is FIXED at 1/3/9 for L1/L2/L3** across all tiers (total 13 re-entries per full cycle, per the client doc "every Nth income spawns a re-entry") — only the per-re-entry $ amount scales by tier multiplier (Agent 2 = $2 per re-entry, Agent 3 = $5, Agent 4 = $10). Boost uses the same 1/3/9 counts (always tier 1, no $ scaling).
- **Stream sponsor income (L2/L3) is paid on level completion as 10% × level gross × tier_multiplier** — L2 base $0.90, L3 base $2.70. Not a position-fill milestone. Paid extra from the platform pool; owner's wallet credit is unaffected.
- **Boost sponsor income (L2/L3) uses the same completion-share model** — L2 $0.27 (10% of $2.70 gross), L3 $0.81 (10% of $8.10 gross). Boost is always tier 1, so no multiplier scaling. The old per-position milestone model (5th/4th/20th member → $0.30) is retired. Boost L3 wallet is **$3.60** (latest client spec, down from $4.90).
- **Each queue self-cycles its own re-entries:** Stream re-entries (dummy) re-enter the same tier's Stream queue; Boost re-entries (real) re-enter the single Boost queue at agent_tier=1. Stream does not feed Boost.
- **Auto-repurchase:** when REPURCHASE wallet >= tier price, a new purchase is auto-activated via Celery.
- **Two deductions** on every wallet credit, **both off the gross**: 10% software fee (platform profit) + 20% repurchase reserve. Effective user take = 70% of gross income credited.
- **`/deposit/balance` returns `{ "account_balance": float }`** — use key `account_balance`, not `balance`.
- **Login is by username + password** (not email) — for both regular users and admin. `UserLogin` takes `username`; the frontend Login form has a Username field.
- **Admin access:** created via `seed_admin.py`. Admin endpoints at `/admin/*`. Admin logs in through the same `/login` page and is routed to `/admin` automatically. Admin pages (including Profile) render the admin sidebar.
- **Frontend auth:** two-step login — POST `/auth/login` (username + password) for JWT, then GET `/auth/me` for full profile (includes `is_admin`).
- **Login 401 handling:** the axios response interceptor (`api/client.js`) only force-logs-out + reloads to `/login` for 401s on *authenticated* requests (expired session). It **skips** that for the auth endpoints (`/auth/login`, `/auth/register`, etc.) so a failed login shows the inline error toast and **keeps the typed form values** instead of reloading the page. Was previously a bug: any 401 reloaded the page, killing the error toast and wiping the form.
- **Frontend API base URL:** `api/client.js` uses `import.meta.env.VITE_API_URL || '/api'`. Local dev / same-domain (reverse-proxy) deploys leave it unset (`/api` + Vite proxy). For split-domain hosting set `VITE_API_URL` to the backend's public URL in `frontend/.env.production`.
- **Logging:** `app/logging_config.py` configures one timestamped handler (`time | LEVEL | logger | message`) for root + uvicorn loggers; verbosity via `LOG_LEVEL` (default INFO). `main.py` adds a request-logging middleware (method/path/status/**duration**, 4xx/5xx at WARNING) and a catch-all exception handler that logs unhandled errors with a full traceback. Use `LOG_LEVEL=DEBUG` to trace, then revert.
- **CORS:** `main.py` reads allowed origins from `settings.cors_origins_list` (`CORS_ORIGINS` env, comma-separated or `*`). Set it to the frontend URL in production instead of `*`.
- **NOWPayments payouts need JWT + 2FA in production:** `send_payout` currently uses only `x-api-key` (fine for deposits/invoices). Outgoing payouts require the `/v1/auth` JWT and a 2FA verify step on the live API — wire this up before go-live or withdrawals will fail (then auto-refund).
- **Platform freeze (global kill switch):** admin can freeze all user money-movement (deposit / withdraw / transfer / purchase) via `POST /admin/platform/freeze` (reason optional, admin-only) and lift it via `POST /admin/platform/unfreeze`. While frozen, guarded user endpoints return HTTP 423; admins bypass. State lives in the single-row `platform_settings` table. Users poll `GET /platform/status` (no reason exposed); admins read `GET /admin/platform/status` (full audit). Frontend shows a red banner + a Freeze/Frozen toggle in the admin top bar.
- **Admin Treasury (separate from user flows):** the **Generate feature was removed** (frontend page/route/nav + backend `POST /admin/generate` endpoint + `AdminGenerateIn` schema), and the **"Treasury Balance" card was removed** from the admin dashboard. `POST /admin/transfer` still sends treasury funds to any user by username (no fee, instant). The `TransactionType.ADMIN_GENERATE` enum and `GET /admin/treasury/summary` (`total_generated`, `total_sent`, etc.) are **kept for historical-data integrity** — no new generate rows can be created, but existing ones still report and serialize correctly.
- **Platform profit (realized):** `platform_profit` = SUM(`SOFTWARE_FEE`) + SUM(`PLATFORM_PROFIT`). `PLATFORM_PROFIT` ledger entries are written at each realization point: matrix level-completion residual (`matrix_engine.place_in_matrix`), Core amount retained when a buyer has no sponsor (`proactive._route_half`), and the 1% transfer fee (`deposit._execute_transfer`). Software fees stay as their own `SOFTWARE_FEE` rows. The admin dashboard's "Platform Profit" card shows this. Historical events were backfilled once via `backend/backfill_platform_profit.py` (idempotent). Pending (uncompleted) matrix money is intentionally NOT counted — only realized profit.
- **Admin user management:** per-user expandable summary (agents bought, account balance, revenue generated) via `GET /admin/users/{id}/summary`; freeze/unfreeze per user; **delete user** via `DELETE /admin/users/{id}` (trash button next to freeze); no credit/debit wallet UI; admin's own row shows no controls. `GET /admin/transactions` resolves each transaction's owner username.
- **Delete user (HARD delete):** `DELETE /admin/users/{id}` permanently removes the user and ALL their rows (wallets, transactions, purchases, matrix positions, withdrawals, deposits, addresses, transfer verifications) in one transaction. Downline users are re-parented to the deleted user's sponsor (`sponsor_position` cleared). Guards: cannot delete self or any admin. Frontend shows a strong confirm dialog. Note: this erases financial history — intended for cleanup, not routine ops.
- **Transfer recipient validation:** both user and admin transfer forms validate the recipient username live (debounced, via `GET /auth/check-username`) — the recipient must exist; self-transfer is blocked client-side.
- **bcrypt pinned to 4.0.1** — bcrypt 5.x breaks passlib's 72-byte wrap detection; do not upgrade.
- `ACCOUNT_TIER = 0` is the sentinel agent_tier used for the account balance wallet.
- **Transaction types are lowercase enum *values*** (`agent_purchase`, `core_sent`, `deposit`, …) — the API serializes `TransactionType.value`, not the member name. Frontend transaction views (`Transactions.jsx`, `Wallet.jsx`, `admin/AdminTransactions.jsx`) classify them with lowercase `INCOME` / `EXPENSE` / `SYSTEM` sets. **Do not use UPPERCASE keys** to match transaction types client-side — that was a real bug where "Total In" summed every row (income + expenses + audit records) because nothing matched the uppercase `NEGATIVE` list. (`Wallet.jsx` had the same UPPERCASE bug — every row rendered as a green "+" — fixed to lowercase keys.)
- **`core_sent` is an informational/audit record**, not a wallet inflow — it records the 60% Core split routed to the upline at purchase time. It is classified as `SYSTEM` (excluded from Total In / Total Out, shown with a neutral marker), not as income.
- **All timestamps display in IST (`Asia/Kolkata`).** The backend stores naive UTC (`datetime.utcnow()`) and serializes it *without* a tz suffix, so JS would otherwise parse it as local time and show it ~5h30m early. `frontend/src/utils/datetime.js` exposes `formatDateTimeIST` / `formatDateIST` / `formatTimeIST` — they mark the value as UTC then format in IST. Use these helpers for any `created_at` rendering; do **not** call `new Date(x).toLocaleString()` directly on backend timestamps. Storage stays UTC (correct convention) — this is display-only.
- **Dashboard "Daily Income" chart uses 2-hour IST-aligned buckets.** `GET /wallet/income/daily` returns **12 two-hour buckets** (not 24 hourly) for the last 24h, anchored to IST even-hour boundaries. Bucket `hour` is still emitted as UTC ISO (`…Z`); because the anchors are IST 2-hour marks, the client renders clean IST labels (`00:00, 02:00, … 22:00`) instead of off-by-:30 values. The chart X-axis (`Dashboard.jsx`) labels every 2-hour mark (`interval="preserveStartEnd"`, thins on mobile); the Y-axis auto-scales in $1 increments (Recharts default — no fixed domain).
