# Luxus Agent Revenue Sharing Platform

## Project Overview

A multi-tier passive income platform. Users make a one-time purchase of an AI agent tier ($10 / $20 / $50 / $100). Each purchase automatically activates three revenue mechanisms that run in parallel.

**Payment model:** On-chain (TokenPocket / MultiSender DApp, USDT BEP-20). Users buy agent tiers by paying the upline split **directly from their own connected wallet** on-chain; the backend computes the split and records the outcome (`POST /distribution/pack/purchase` + `/pack/status`). Income lands directly in users' on-chain wallets — the **spendable money never moves through internal balances**. For DISPLAY, each on-chain commission is also mirrored into the internal wallets as a **virtual 80% main / 20% repurchase-reserve** split (bookkeeping only — see "On-chain pack purchase").

> **Removed (on-chain migration):** the legacy **deposit-first money rail is gone** — NOWPayments (deposit invoices + IPN webhooks + payout/withdrawal), the `/deposit` endpoints, user-to-user `/deposit/transfer`, the `/wallet/withdraw(+withdrawals)` endpoints, the account-balance `/agents/purchase` path, and the `deposit` / `withdrawal_requests` / `webhook_events` / `transfer_verifications` models/tables.
>
> The internal **Core/Stream/Boost revenue engine has also been removed** — `app/workers/` (Celery app + tasks), `core/matrix_engine.py`, `core/revenue_split.py`, the `matrix_positions` / `matrix_counters` models, the `/agents/matrix` endpoint, and the frontend Matrix/"Queue" page. **Celery and Redis are no longer used or required** (removed from `requirements.txt` and config). The on-chain pack split uses the **Core rule only** via `core/pack_payout.py` + the eligibility/compression helpers kept in `core/proactive.py`.
>
> **Kept:** the internal `Wallet` model + `/wallet/balances` + the Wallet page (read by `/distribution/wallet-map` and the admin views). On the on-chain rail these wallets are populated as a **virtual 80/20 display split** of each commission (not movable funds — the real balance is on-chain); the new `GET /wallet/earnings` is the source of truth for "Total Earnings". Also kept: the admin manual wallet credit/debit endpoints. The old DB tables (`deposits`, `withdrawal_requests`, `webhook_events`, `transfer_verifications`, `matrix_positions`, `matrix_counters`) are left in the database untouched (no data dropped); they're simply no longer created or read.

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
│   │   │   ├── Dashboard.jsx / AgentPurchase.jsx (on-chain buy)
│   │   │   ├── Wallet.jsx / Transactions.jsx / Profile.jsx
│   │   │   └── admin/
│   │   │       ├── AdminDashboard.jsx / AdminUsers.jsx
│   │   │       └── AdminTransactions.jsx
│   │   ├── hooks/useUsdtBalance.js  # Live on-chain USDT balance (wagmi balanceOf)
│   │   └── config/appkit.js     # Reown/WalletConnect + wagmi (BSC) wallet config
│   └── vite.config.js           # Tailwind, port 3000, /api proxy → localhost:8000
├── backend/
│   ├── seed_admin.py            # One-time admin user creation from .env credentials
│   ├── app/
│   │   ├── main.py              # FastAPI app + CORS
│   │   ├── config.py            # Settings (reads ../.env)
│   │   ├── database.py          # SQLAlchemy engine + session
│   │   ├── models/
│   │   │   ├── user.py          # User + OTP fields (email verify, password reset) + wallet_address
│   │   │   ├── agent.py         # AgentPurchase
│   │   │   ├── wallet.py        # Wallet (MAIN + REPURCHASE + ACCOUNT types — internal, virtual 80/20 display split on-chain)
│   │   │   ├── wallet_address.py # Verified BEP-20 payout addresses
│   │   │   ├── transaction.py   # Transaction ledger (TransactionType enum)
│   │   │   ├── pack_purchase.py # On-chain pack order record (pending/success/failed + tx_hash)
│   │   │   └── platform_setting.py # Single-row platform state (global freeze kill switch)
│   │   ├── core/
│   │   │   ├── pack_payout.py   # On-chain pack split (Core rule: 60% → 2 eligible uplines, 40% platform)
│   │   │   ├── proactive.py     # Core Agent eligibility/compression helpers (used by pack_payout)
│   │   │   ├── wallet_ops.py    # credit/debit_wallet() + credit/debit_account() + withdrawable/earnings
│   │   │   ├── platform_state.py # Freeze get/set helpers
│   │   │   └── security.py      # JWT + password hashing
│   │   ├── logging_config.py    # Central timestamped logging setup (LOG_LEVEL)
│   │   ├── services/
│   │   │   └── email_service.py # SMTP email — OTP / verification notifications
│   │   ├── schemas/
│   │   │   ├── user.py          # Register (sponsor_username), Login (username+password), OTP, reset
│   │   │   └── agent.py         # Purchase, Wallet, WalletAddress, Admin treasury/freeze schemas
│   │   └── api/
│   │       ├── auth.py          # register / check-username / verify-email / login (username) / forgot & reset
│   │       ├── agents.py        # GET purchases (read-only ownership list)
│   │       ├── wallet.py        # balances / transactions / earnings / income-daily / BEP-20 address management
│   │       ├── admin.py         # admin-only: users + summary, transactions, freeze/unfreeze, treasury (transfer), platform freeze
│   │       ├── platform.py      # GET /platform/status (freeze state for any logged-in user)
│   │       └── distribution.py  # /distribution/wallet-map + on-chain pack rail (/pack/purchase, /pack/status)
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
| Auth | JWT (python-jose + passlib/bcrypt==4.0.1) |
| Payments | On-chain USDT (BEP-20) via TokenPocket / MultiSender DApp |
| Email | SMTP (Gmail / any provider) |

## Database

- **Host**: localhost:5432
- **Database**: `luxus`
- **User**: `luxus`
- **Password**: `dhanush`
- **Connection string**: `postgresql://luxus:dhanush@localhost/luxus`

Tables (created by `create_tables.py`): `users`, `agent_purchases`, `wallets`, `wallet_addresses`, `transactions`, `pack_purchases`, `platform_settings`.

> Legacy tables (`deposits`, `withdrawal_requests`, `webhook_events`, `transfer_verifications`, `matrix_positions`, `matrix_counters`) may still exist in older databases — they are no longer created or read after the on-chain migration. Drop them manually if you want a clean schema.

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

## Purchase Flow (on-chain)

Purchases happen **on-chain** — the buyer pays the upline split directly from their
connected wallet via the TokenPocket / MultiSender DApp. See the "On-chain pack
purchase" section below for the full detail.

```
1. POST /distribution/pack/purchase  → backend computes the Core-rule split and
                                        returns recipients + amounts (sums to price)
2. Frontend sends the batched USDT (BEP-20) payment on-chain (MultiSender)
3. POST /distribution/pack/status    → backend records success (tx_hash) or failure;
                                        on success creates the AgentPurchase ownership
                                        row + reporting-only Transaction rows

Wallet address management (BEP-20 payout target, used by the distribution map):
   POST /wallet/address           → register a BEP-20 address; sends email OTP
   POST /wallet/address/verify    → confirm OTP; marks address as verified
   GET  /wallet/addresses         → list user's verified addresses
   DELETE /wallet/address/{id}    → remove a registered address
```

> **Removed:** account-balance deposits, user-to-user transfers, and withdrawals —
> along with NOWPayments. There is no internal money-in/money-out flow anymore;
> all value moves on-chain in users' own wallets.

## Revenue Mechanics

> **Status after the on-chain migration:** Only the **Core Agent rule** is live — it
> drives the on-chain pack split (`core/pack_payout.py` + the eligibility/compression
> helpers in `core/proactive.py`): **60% → two 30% halves to the first two eligible
> uplines, 40% → platform fee** (see "On-chain pack purchase" below). The **Stream
> (30%) and Boost (10%) matrix systems, the 60/30/10 split, and auto-repurchase were
> REMOVED** with the deposit-first engine. The internal-wallet 70/20/10 deduction
> logic (`credit_wallet`) still exists but is now only reachable via the admin
> manual wallet-credit tool — no automatic income flows through it. (Separately,
> the on-chain rail mirrors each commission into the internal wallets as a
> **virtual 80/20 main/repurchase display split** via
> `wallet_ops.mirror_onchain_earning_split` — bookkeeping only, distinct from
> `credit_wallet`'s 70/20/10.) The Stream/Boost/Wallet-rule subsections below are
> retained as **historical reference** for the original business model — they no
> longer run.

### Split (historical — deposit-first model, removed)
- **60%** → Core Agent system
- **30%** → Stream Agent system (3x3 forced matrix, separate queue per tier)
- **10%** → Boost Agent system (3x3 forced matrix, single global queue)

### Core Agent (60%) — formerly ProActive
*(The compression + odd/even rule below is LIVE — it is exactly what the on-chain
pack split applies, except the on-chain split routes 40% to the platform instead of
30% Stream + 10% Boost.)*
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

### Stream Agent (30%) — formerly Proportion  *(REMOVED — historical reference)*
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

### Boost Agent (10%) — formerly Speculation  *(REMOVED — historical reference)*
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

Effective split of gross income: **70% main wallet** + **20% repurchase** + **10% platform fee**.

> **Status:** `credit_wallet()` (the 70/20/10 logic above) still exists but is now only
> reachable via the **admin manual wallet-credit** endpoint. No automatic income flows
> through this path anymore. The on-chain rail pays users directly on-chain (the real
> spendable money), and **separately** mirrors each commission into the internal
> wallets as a **virtual 80% main / 20% repurchase-reserve** display split (no software
> fee) via `wallet_ops.mirror_onchain_earning_split` — so per-tier balances and the
> Repurchase Reserve populate for display. These wallet figures are bookkeeping only,
> not movable funds. "Total Earnings" reads the **gross** from the ledger
> (`GET /wallet/earnings`), which equals main + reserve.

### Auto-repurchase  *(LIVE — `app/core/repurchase.py`)*
Every income credit holds back 20% into the earner's per-tier `REPURCHASE` wallet
(via `credit_wallet` / `mirror_onchain_earning_split`). When a tier's reserve reaches its
**threshold = pack price + a fixed gas allowance**, the platform automatically re-buys that
**same tier** from the reserve, unbounded ("to its infinity" — a manual buy happens once,
repurchases keep going while the reserve can afford them).

Thresholds (per the client spec):

| Tier | Price | Gas | Threshold |
|------|-------|-----|-----------|
| Agent 1 | $10 | $0.25 | **$10.25** |
| Agent 2 | $20 | $0.50 | **$20.50** |
| Agent 3 | $50 | $1.25 | **$51.25** |
| Agent 4 | $100 | $2.50 | **$102.50** |

A repurchase **acts like a normal purchase**: it re-runs the Core 60% compressed/odd-even
split to eligible uplines (credited via `credit_wallet`, so uplines build their *own* reserve →
**compounding**, per client Q6) plus the Stream/Boost matrix placement + payout cascade. The
buy portion is recorded as a `REPURCHASE_BUY` ledger row and the gas portion as `REPURCHASE_GAS`
(platform pays the network gas, per the client). Boost reserve always accrues in the **tier-1**
bucket (single global queue), so Boost-driven repurchases re-buy Agent 1.

The driver is `sweep_auto_repurchases(db)` — it scans every user's reserve and re-buys any tier
at/over threshold, re-scanning each round so the upline compounding cascade is drained (bounded
by a step cap). It is called inside the `/distribution/pack/status` success transaction, right
after the Stream/Boost matrices. Reserves of frozen/inactive users are **held** (not consumed),
per client Q8.

**Frontend support:** `GET /wallet/repurchase` returns per-tier reserve + threshold +
`progress_percent` + `ready` (for the progress bar); `GET /wallet/repurchase/history` lists
executed auto-repurchases (`REPURCHASE_BUY` rows). On-chain *broadcasting* of the repurchase from
the platform reserve wallet is **not yet wired** — this implements the internal accounting only.

## Withdrawal Flow  *(REMOVED)*

Withdrawals were removed with NOWPayments. Users hold their funds on-chain in their own
wallets, so there is no internal withdrawal/payout flow. (BEP-20 address registration under
`/wallet/address` is kept — it's the payout target used by the distribution map.)

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
records the outcome. The on-chain transfer *is* the payout (no real money moves through
internal wallets). On success it (a) creates an **active `AgentPurchase` ownership row** so
the rest of the app (purchase-page "OWNED", the sequential-unlock gate, and Core-eligibility
for future on-chain splits) recognizes the buyer, (b) writes **reporting `Transaction` rows**
(buyer `agent_purchase` expense + each upline's `core_income`) so transaction history and the
dashboard analytics reflect the activity, and (c) mirrors each upline's commission into their
internal per-tier wallets as a **virtual 80% main / 20% repurchase-reserve display split**
(via `wallet_ops.mirror_onchain_earning_split`) so the per-tier balances and Repurchase
Reserve populate — these wallet figures are bookkeeping only, NOT movable funds. (Lives in
`app/api/distribution.py`; split logic in `app/core/pack_payout.py`; record in
`app/models/pack_purchase.py` → table `pack_purchases`.)

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
  `credit_wallet` deductions do **not** apply here). Example $10 pack with two eligible uplines:
  `upline L1 $3 + upline L2 $3 + platform_fee $4`. (The recipient's $3 lands in full on-chain;
  the internal wallets separately record a virtual $2.40 main / $0.60 reserve for display.)
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
  revenue engine queued, dup-tier guarded) + reporting `Transaction` rows (buyer
  `agent_purchase`, each upline `core_income`) + the **virtual 80/20 wallet display split** for
  each upline (via `mirror_onchain_earning_split`). The wallet balances are bookkeeping/display
  only — the real spendable money is on-chain. The software-fee path and Stream/Boost matrix
  mechanics do not run here; there is no auto-repurchase (the reserve just accumulates).
  To backfill internal wallets for purchases recorded before the 80/20 mirror existed, run
  `python backfill_repurchase_reserve.py` (idempotent — recomputes wallets from `core_income`).
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

| Event | Endpoint |
|-------|----------------|
| OTP verification on register | `POST /auth/register` |
| Resend OTP | `POST /auth/resend-verification` |
| Password reset OTP | `POST /auth/forgot-password` |
| BEP-20 address verification OTP | `POST /wallet/address` |

> These four OTP emails are the **only** emails the platform sends. The deposit /
> agent-activation / withdrawal / transfer email templates were **deleted** from
> `email_service.py` (along with the `_send_sync` helper they used) — they belonged to the
> removed deposit-first + NOWPayments rails.

SMTP config keys: `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SENDER_EMAIL`

For Gmail use an **App Password**: `myaccount.google.com/apppasswords`

## How to Run

### Prerequisites
- Python 3.11+ in conda env `luxus`
- PostgreSQL 18 running locally
- (Celery/Redis are no longer used — the backend is fully synchronous)

### Setup (first time — fresh install)

```bash
# 1. Fill in your .env
cp .env.example .env
# edit .env — SMTP credentials, SECRET_KEY, ADMIN_*, and on-chain settings
# (USDT_CONTRACT, PLATFORM_FEE_WALLET, etc.)

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
# API server (from backend/) — no Celery worker needed anymore
conda activate luxus
cd backend
uvicorn app.main:app --reload
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
| `backend/app/api/distribution.py` | `GET /distribution/wallet-map` (wallet+profit map) + the on-chain pack rail (`POST /pack/purchase`, `/pack/status`) |
| `backend/app/core/pack_payout.py` | On-chain pack split (Core rule: 60% → 2 eligible uplines, 40% → platform; missing→platform). No wallet writes |
| `backend/app/core/proactive.py` | Core eligibility/compression helpers (`_is_eligible`, `_next_eligible_upline`) used by `pack_payout` |
| `backend/app/models/pack_purchase.py` | `PackPurchase` — on-chain pack order record (pending/success/failed + tx_hash + recipients snapshot) |
| `backend/app/core/wallet_ops.py` | credit/debit wallet + account balance helpers; `get_ledger_earnings` (lifetime income from the ledger — source of truth for "Total Earnings"); `mirror_onchain_earning_split` (virtual 80/20 main/repurchase display split for on-chain commissions) |
| `backend/app/models/transaction.py` | `TransactionType` enum (CORE_INCOME, AGENT_PURCHASE, SOFTWARE_FEE, PLATFORM_PROFIT, …) |
| `backend/app/api/auth.py` | Register (sponsor_username), check-username, email verify, password reset |
| `backend/app/api/wallet.py` | Balances, transactions, **earnings** (`GET /wallet/earnings` — lifetime income from the ledger), daily income, BEP-20 address management |
| `backend/app/api/agents.py` | `GET /agents/purchases` — read-only ownership list |
| `backend/app/api/admin.py` | Admin: users, transactions, freeze/unfreeze, treasury transfer, platform freeze, manual wallet credit/debit |
| `backend/app/services/email_service.py` | Transactional email templates + SMTP send (OTP / verification) |

## Dev Notes

> **Many notes below describe the removed deposit-first / matrix / Celery / withdrawal
> model.** They are kept where they still document live behavior (Core eligibility,
> auth, freeze, IST timestamps, etc.) and marked *(REMOVED)* where they don't. The
> backend is now fully synchronous (no Celery/Redis) and all value moves on-chain.

- All financial amounts use Python `Decimal` to avoid float precision errors.
- The backend is fully synchronous — there are **no background tasks / Celery / Redis** anymore.
- Login requires email verification — unverified users get HTTP 403.
- **Sponsor is identified by username** at registration (`sponsor_username` field). The register form does a live debounced username availability check via `GET /auth/check-username`, and a **live sponsor-existence check** against the *same* endpoint inverted (`available:false` = username taken = sponsor exists = valid; `available:true` = no such user = invalid). Submit is blocked on an invalid sponsor.
- **Root/admin user has no sponsor** — created directly in DB via `seed_admin.py`.
- **BEP-20 wallet address at registration:** `User.wallet_address` (nullable column) is collected on the register form for the TokenPocket distribution flow. The register schema validates it as `0x` + 40 hex chars; it's **optional** on the backend (so existing flows don't break) but the frontend form makes it required with live validation. Exposed via `/auth/me` and `UserOut`. Existing DBs: run `cd backend && python migrate_v14.py` (idempotent — adds the nullable `users.wallet_address` column); `create_tables.py` covers fresh installs.
- **TokenPocket distribution map:** `GET /distribution/wallet-map` (`app/api/distribution.py`) is the single consolidated, read-only endpoint that returns a user + their downline with each one's wallet address and profit, for the frontend MultiSender. Distribute against `profit.withdrawable`. See the "TokenPocket / MultiSender Distribution Endpoint" section above.
- **On-chain pack purchase:** `POST /distribution/pack/purchase` + `POST /distribution/pack/status` (`app/api/distribution.py`) are a **separate on-chain (BEP-20 USDT) rail** — the frontend pays the upline split directly from the buyer's wallet; the backend returns the validated split and records the outcome. Split = **Core rule only** (60% → two 30% halves to the first two eligible uplines via `app/core/pack_payout.py`, 40% → platform fee; missing/ineligible upline → platform, so it sums to the pack price). Order record in `pack_purchases` (`app/models/pack_purchase.py`). On success it also creates an **active `AgentPurchase` ownership row** (no Celery, dup-tier guarded), **reporting `Transaction` rows** (buyer `agent_purchase` + each upline `core_income`), and a **virtual 80% main / 20% repurchase-reserve display split** into each upline's internal wallets (`mirror_onchain_earning_split`) so the purchase shows as OWNED, appears in transaction history + the dashboard income chart, and populates the per-tier balances + Repurchase Reserve. These internal wallet figures are **bookkeeping/display only — not movable funds** (the real spendable money is on-chain). "Total Earnings" is read from the ledger via `GET /wallet/earnings`, not from wallet balances. Migration: `python migrate_v15.py`; backfill older internal wallets with `python backfill_repurchase_reserve.py`. See the "On-chain pack purchase" subsection above.
- **On-chain wallet balance display:** the "Wallet Balance" card on Dashboard / Wallet / Buy Agents pages shows the connected wallet's **live on-chain USDT** (via `frontend/src/hooks/useUsdtBalance.js`, wagmi `balanceOf`), not an internal balance. It needs `VITE_USDT_ADDRESS` (frontend `.env`) to **match the backend `USDT_CONTRACT`**; a mismatch makes the card read a different token and show $0. Restart the Vite dev server after changing `.env`.
- **BEP-20 address management is kept** — register via `POST /wallet/address`, confirm OTP via `POST /wallet/address/verify`. It's the payout target used by the distribution map (not a withdrawal address anymore).
- *(REMOVED)* Deposits, user-to-user transfers (1% fee / OTP), and withdrawals — gone with NOWPayments.
- **One purchase per tier, bought in order** — each tier can be purchased only once, and tiers must be bought sequentially 1 → 2 → 3 → 4 (cannot skip ahead). Ownership is recorded by the on-chain `/pack/status` success handler.
- **Inactive / ineligible uplines are skipped** in the Core split — see compression below.
- **Core Agent compression + odd/even (LIVE — the on-chain pack split rule):** an upline qualifies for Core income only if their **highest active purchased tier ≥ the buyer's purchased tier**. Lower-tier / inactive / no-agent uplines are skipped and the income compresses up the sponsor chain to the next eligible upline. The two 30% halves go to the first eligible upline and the next eligible upline above it; even-count pass-ups (via `User.core_route_count`) also compress to the next eligible upline. On the on-chain rail, a half with no eligible recipient (or no valid BEP-20 address) folds into the 40% platform fee. Implemented in `pack_payout.py` + `proactive.py` (`_highest_active_tier` / `_is_eligible` / `_next_eligible_upline`).
- *(REMOVED)* Stream / Boost matrix mechanics (3×3 queues, dummy/real re-entries, sponsor completion-share, re-entry counts) — the entire matrix engine is gone.
- **Auto-repurchase (LIVE — `app/core/repurchase.py`):** when a tier's `REPURCHASE` reserve reaches its **threshold = price + gas** ($10.25 / $20.50 / $51.25 / $102.50), the platform auto-re-buys that same tier from the reserve, unbounded. A repurchase re-runs the Core split + Stream/Boost matrices like a normal purchase (uplines build their own reserve → compounding). Driven by `sweep_auto_repurchases(db)`, called in the `/distribution/pack/status` success transaction after the matrices; re-scans each round to drain the cascade. Records `REPURCHASE_BUY` (price) + `REPURCHASE_GAS` (gas → platform) ledger rows; frozen/inactive users' reserves are held. Progress + history via `GET /wallet/repurchase` and `GET /wallet/repurchase/history`. On-chain *broadcast* of the repurchase is not yet wired (internal accounting only). See the "Auto-repurchase" section above.
- **Internal wallet deductions** (10% software fee + 20% repurchase = 70% main) live in `credit_wallet`, reached by both the Stream/Boost matrix payouts and the **admin manual wallet-credit** tool (`/admin/wallet/credit`, recorded as `ADMIN_CREDIT` — previously referenced a non-existent `PROPORTION_PAYOUT` and threw; fixed). The on-chain Core rail uses `mirror_onchain_earning_split` (same 70/20/10) so each upline's 20% lands in their per-tier reserve and can trigger auto-repurchase.
- **Total Earnings = ledger, not wallets.** `GET /wallet/earnings` (`wallet_ops.get_ledger_earnings`) sums lifetime income (`core_income` + stream/boost/sponsor types) from the transaction ledger — live, no admin approval, not capped at the 200-row tx listing. Dashboard, Wallet, and the admin per-user "revenue_generated" all read this (NOT `sum(MAIN wallet balances)`, which previously read $0 because on-chain commissions never credit internal wallets as real funds). The earnings fetch on Dashboard/Wallet is **non-fatal** (falls back to $0) so a failing endpoint can't blank the page. Earnings show even with the wallet disconnected (they come from the DB, not the chain).
- **Auto-repurchase is back.** The per-tier repurchase reserve auto-triggers a same-tier re-buy at the price+gas threshold ($10.25 / $20.50 / $51.25 / $102.50) via `app/core/repurchase.py` — see the dedicated note above. New transaction types: `REPURCHASE_BUY`, `REPURCHASE_GAS`. Run `python migrate_v17.py` on existing DBs (adds these + `ADMIN_CREDIT` and the matrix pool types to the Postgres `transactiontype` enum).
- **Wallet page** has no "Account Balance" card (removed — always $0 on-chain); it shows Wallet Balance (on-chain USDT) + Total Earnings (ledger) + Repurchase Reserve (virtual).
- **Login is by username + password** (not email) — for both regular users and admin. `UserLogin` takes `username`; the frontend Login form has a Username field.
- **Admin access:** created via `seed_admin.py`. Admin endpoints at `/admin/*`. Admin logs in through the same `/login` page and is routed to `/admin` automatically. Admin pages (including Profile) render the admin sidebar.
- **Frontend auth:** two-step login — POST `/auth/login` (username + password) for JWT, then GET `/auth/me` for full profile (includes `is_admin`).
- **Login 401 handling:** the axios response interceptor (`api/client.js`) only force-logs-out + reloads to `/login` for 401s on *authenticated* requests (expired session). It **skips** that for the auth endpoints (`/auth/login`, `/auth/register`, etc.) so a failed login shows the inline error toast and **keeps the typed form values** instead of reloading the page. Was previously a bug: any 401 reloaded the page, killing the error toast and wiping the form.
- **Frontend API base URL:** `api/client.js` uses `import.meta.env.VITE_API_URL || '/api'`. Local dev / same-domain (reverse-proxy) deploys leave it unset (`/api` + Vite proxy). For split-domain hosting set `VITE_API_URL` to the backend's public URL in `frontend/.env.production`.
- **Logging:** `app/logging_config.py` configures one timestamped handler (`time | LEVEL | logger | message`) for root + uvicorn loggers; verbosity via `LOG_LEVEL` (default INFO). `main.py` adds a request-logging middleware (method/path/status/**duration**, 4xx/5xx at WARNING) and a catch-all exception handler that logs unhandled errors with a full traceback. Use `LOG_LEVEL=DEBUG` to trace, then revert.
- **CORS:** `main.py` reads allowed origins from `settings.cors_origins_list` (`CORS_ORIGINS` env, comma-separated or `*`). Set it to the frontend URL in production instead of `*`.
- **Platform freeze (global kill switch):** admin can freeze user money-movement via `POST /admin/platform/freeze` (reason optional, admin-only) and lift it via `POST /admin/platform/unfreeze`. The guarded endpoint now is the on-chain **`POST /distribution/pack/purchase`** (it depends on `require_platform_active`); while frozen it returns HTTP 423, admins bypass. State lives in the single-row `platform_settings` table. Users poll `GET /platform/status` (no reason exposed); admins read `GET /admin/platform/status` (full audit). Frontend shows a red banner + a Freeze/Frozen toggle in the admin top bar.
- **Admin Treasury (separate from user flows):** the **Generate feature was removed** (frontend page/route/nav + backend `POST /admin/generate` endpoint + `AdminGenerateIn` schema), and the **"Treasury Balance" card was removed** from the admin dashboard. `POST /admin/transfer` still sends treasury funds to any user by username (no fee, instant). The `TransactionType.ADMIN_GENERATE` enum and `GET /admin/treasury/summary` (`total_generated`, `total_sent`, etc.) are **kept for historical-data integrity** — no new generate rows can be created, but existing ones still report and serialize correctly.
- **Platform profit (realized):** the admin dashboard still computes `platform_profit` = SUM(`SOFTWARE_FEE`) + SUM(`PLATFORM_PROFIT`), but the code paths that *wrote* those rows (matrix residuals, core-retained, transfer fee) were all removed with the engine. So this now reflects **historical rows only** (plus any `SOFTWARE_FEE` from admin manual credits). On the on-chain rail the platform's 40% is paid on-chain to `PLATFORM_FEE_WALLET` and is **not** ledgered as a `PLATFORM_PROFIT` transaction — to surface on-chain platform revenue, sum the `platform_fee` recipients from `pack_purchases` instead.
- **Admin user management:** per-user expandable summary (agents bought, account balance, revenue generated) via `GET /admin/users/{id}/summary`; freeze/unfreeze per user; **delete user** via `DELETE /admin/users/{id}` (trash button next to freeze); no credit/debit wallet UI; admin's own row shows no controls. `GET /admin/transactions` resolves each transaction's owner username.
- **Delete user (HARD delete):** `DELETE /admin/users/{id}` permanently removes the user and their rows (wallets, transactions, purchases, wallet addresses) in one transaction. Downline users are re-parented to the deleted user's sponsor (`sponsor_position` cleared). Guards: cannot delete self or any admin. Frontend shows a strong confirm dialog. Note: this erases financial history — intended for cleanup, not routine ops.
- **Admin treasury transfer recipient validation:** the admin treasury *Send to User* form validates the recipient username live (debounced, via `GET /auth/check-username`) — the recipient must exist; self-transfer is blocked client-side.
- **bcrypt pinned to 4.0.1** — bcrypt 5.x breaks passlib's 72-byte wrap detection; do not upgrade.
- `ACCOUNT_TIER = 0` is the sentinel agent_tier used for the account balance wallet.
- **Transaction types are lowercase enum *values*** (`agent_purchase`, `core_sent`, `deposit`, …) — the API serializes `TransactionType.value`, not the member name. Frontend transaction views (`Transactions.jsx`, `Wallet.jsx`, `admin/AdminTransactions.jsx`) classify them with lowercase `INCOME` / `EXPENSE` / `SYSTEM` sets. **Do not use UPPERCASE keys** to match transaction types client-side — that was a real bug where "Total In" summed every row (income + expenses + audit records) because nothing matched the uppercase `NEGATIVE` list. (`Wallet.jsx` had the same UPPERCASE bug — every row rendered as a green "+" — fixed to lowercase keys.)
- **`core_sent` is no longer written** — it was the deposit-first audit record for the 60% Core routing. The on-chain rail instead writes a buyer `agent_purchase` row + each upline's `core_income` row (reporting-only, no wallet balance). The `CORE_SENT` enum value is retained for historical rows; frontends still classify it as `SYSTEM`.
- **All timestamps display in IST (`Asia/Kolkata`).** The backend stores naive UTC (`datetime.utcnow()`) and serializes it *without* a tz suffix, so JS would otherwise parse it as local time and show it ~5h30m early. `frontend/src/utils/datetime.js` exposes `formatDateTimeIST` / `formatDateIST` / `formatTimeIST` — they mark the value as UTC then format in IST. Use these helpers for any `created_at` rendering; do **not** call `new Date(x).toLocaleString()` directly on backend timestamps. Storage stays UTC (correct convention) — this is display-only.
- **Dashboard "Daily Income" chart uses 2-hour IST-aligned buckets.** `GET /wallet/income/daily` returns **12 two-hour buckets** (not 24 hourly) for the last 24h, anchored to IST even-hour boundaries. Bucket `hour` is still emitted as UTC ISO (`…Z`); because the anchors are IST 2-hour marks, the client renders clean IST labels (`00:00, 02:00, … 22:00`) instead of off-by-:30 values. The chart X-axis (`Dashboard.jsx`) labels every 2-hour mark (`interval="preserveStartEnd"`, thins on mobile); the Y-axis auto-scales in $1 increments (Recharts default — no fixed domain).
