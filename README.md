# Luxus — Agent Revenue Sharing Platform

A multi-tier passive income platform where users buy AI Agent tiers **on-chain** (USDT BEP-20) and earn through three parallel revenue engines: **Core Agent**, **Stream Agent**, and **Boost Agent**.

---

## Table of Contents

- [Key Features](#key-features)
- [Architecture](#architecture)
- [Revenue Mechanics](#revenue-mechanics)
- [User Journey](#user-journey)
- [Auth Flow](#auth-flow)
- [Deposit & Purchase Flow](#deposit--purchase-flow)
- [Matrix System](#matrix-system)
- [Withdrawal Flow](#withdrawal-flow)
- [TokenPocket Distribution Endpoint](#tokenpocket-distribution-endpoint)
- [On-Chain Pack Purchase](#on-chain-pack-purchase)
- [Tech Stack](#tech-stack)
- [Setup & Installation](#setup--installation)
- [Running the Project](#running-the-project)
- [Admin Setup](#admin-setup)
- [Environment Variables](#environment-variables)

---

## Key Features

- 🔗 **Fully on-chain payments** — buyers pay the upline split directly from their own wallet (TokenPocket / MultiSender, USDT BEP-20); no custodial deposit/withdrawal rail.
- 💸 **Three-engine 60 / 30 / 10 revenue split** — Core (compressed upline routing with odd/even), Stream (per-tier 3×3 matrix), Boost (single global 3×3 matrix + 1% admin).
- 🔁 **Automatic repurchase** — a 20% per-tier reserve auto re-buys the same tier at its price+gas threshold, unbounded and compounding through uplines.
- 🌳 **Username-based sponsor tree** — every user registers under a sponsor; live sponsor-existence + wallet-address validation on the register form.
- 🧮 **70 / 20 / 10 wallet rule** — every commission splits into main wallet / repurchase reserve / software fee.
- 🛡️ **Admin controls** — per-user freeze, treasury transfer, and a global platform-freeze kill switch (HTTP 423 on purchases while frozen).
- 📊 **Real-time earnings & distribution map** — ledger-sourced totals plus a read-only `wallet-map` endpoint that feeds the MultiSender payout.
- ✉️ **Email OTP** — verification on register, password reset, and BEP-20 address confirmation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Frontend  (Vite + React, port 3000)                    │
│  /api/* → proxy → localhost:8000                        │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Backend   (FastAPI, port 8000 — fully synchronous)     │
│  └── REST API (auth, agents, wallet, distribution, admin)│
│           │                                             │
│           ▼                                             │
│      PostgreSQL 18                                      │
└────────────────────────┬────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
   On-chain USDT (BEP-20)          SMTP Email
   TokenPocket / MultiSender       Notifications
   (buyer pays uplines directly)
```

---

## Revenue Mechanics

Every confirmed agent purchase triggers a **60 / 30 / 10 split** across three parallel engines.

### Agent Tiers & Max Payouts

| Tier    | Base | Platform fee | Total cost | Core Agent | Stream Agent | Boost Agent |
|---------|------|--------------|-----------|-----------|-------------|------------|
| Agent 1 | $10  | $1   | **$11**  | $6.00     | $20.00      | $5.70      |
| Agent 2 | $20  | $2   | **$22**  | $12.00    | $40.00      | $5.70      |
| Agent 3 | $50  | $5   | **$55**  | $30.00    | $100.00     | $5.70      |
| Agent 4 | $100 | $11  | **$111** | $60.00    | $200.00     | $5.70      |

> The buyer pays **Total cost = Base + Platform fee**; the flat platform fee goes straight to the platform profit wallet and is **not** part of the 60/30/10 split (which runs off the **Base**). Applies to repurchase too.
>
> Boost runs a **single global queue** (always tier 1), so its payout does not scale with the purchased tier — the full Boost cycle is $0.60 + $1.50 + $3.60 = **$5.70** wallet for every tier.

---

### 60% — Core Agent (Upline Routing with Compression)

The 60% is split into two equal halves (30% each), routed up the sponsor chain
with **compression**. Two rules apply together — and **only** in the Core Agent:
compression decides *who* is a valid recipient, then odd/even decides whether
that recipient keeps the amount or passes it up.

**1. Compression (tier-qualified routing):**
- An upline only **qualifies** for Core income if their own **highest active
  purchased tier ≥ the tier the buyer just purchased**.
- Uplines who bought a lower tier (or own no active agent, or are frozen) are
  **skipped** — the income compresses *past* them up the chain to the next
  eligible upline.
- **First 30%** → first eligible upline above the buyer.
- **Second 30%** → next eligible upline above the first.
- If **no eligible upline** exists for a half → retained by the platform
  (realized profit) — **not** credited back to the buyer.

> Example (`Admin $100 → A $100 → B $10 → C $10 → D $20 → E $100`): when **E buys
> $100** (tier 4), uplines **D ($20), C ($10), B ($10) are all skipped** because
> none bought the $100 tier; income lands on **A ($100)** and **Admin ($100)**.

**2. Odd/Even rule** at each eligible recipient (tracked by `User.core_route_count`):
- Each recipient has a targeting counter, incremented **every time they are targeted** — whether they keep the amount or pass it up.
- If the resulting count is **odd** → credited directly to their wallet.
- If it is **even** → amount passes up to the next **eligible** upline above them (the pass-up is compressed too).
- If no eligible upline exists for an even pass-up → the recipient keeps it.

> The counter increments on every targeting (not only on kept credits) so the alternation never gets stuck on "even" after a recipient's first pass-up. Compression applies to the Core Agent **only** — Stream and Boost matrices are unaffected.

Implemented in `proactive.py` via `_highest_active_tier` / `_is_eligible` / `_next_eligible_upline`.

---

### 30% — Stream Agent (3×3 Forced Matrix)

- **Separate queue per tier** — Agent 1, 2, 3, and 4 each have their own BFS queue.
- Positions fill breadth-first in a ternary tree (3 children per node).
- Payouts trigger when L1 (3 members), L2 (9 members), and L3 (27 members) fill.
- Re-entries generated by Stream are **dummy** and cycle back into the **same tier's Stream queue** — they fill slots to advance the queue but receive no payouts and spawn no further re-entries (per the client matrix diagram `A·B·C·D·A1·E·F·B1·…`). Stream does **not** feed Boost.
- **Re-entry COUNT is fixed at 1 / 3 / 9** (L1/L2/L3) across all tiers — "every Nth income spawns a re-entry" (total 13 per full cycle). Only the wallet payout and the per-re-entry **$ amount** scale by the tier multiplier (Agent 1=1×, 2=2×, 3=5×, 4=10×).

**Payout schedule (Agent 1 / $10 base):**

| Level | Members | Wallet Payout | Re-entries | Sponsor share (on completion) |
|-------|---------|--------------|-----------|-------------------------------|
| L1    | 3       | $2.00        | 1         | —                             |
| L2    | 9       | $5.00        | 3         | $0.90 (10% of $9 gross)       |
| L3    | 27      | $13.00       | 9         | $2.70 (10% of $27 gross)      |

Higher tiers multiply wallet payouts, per-re-entry $ amounts, and sponsor share by their multiplier (re-entry counts stay 1/3/9).

**Sponsor share:** At L2 and L3 an *extra* 10% of the level's gross is credited to the owner's sponsor when the level completes — paid from the platform pool, **not** deducted from the owner's wallet. L1 has no sponsor share.

---

### 10% — Boost Agent (3×3 Forced Matrix)

- **Single global queue** — all positions use Agent 1 (tier 1).
- **All positions are real** — including Boost's own re-entries, which cycle back into this same queue (no dummy entries).
- Same 3×3 BFS structure as Stream.

**Payout schedule:**

| Level | Members | Wallet Payout | Re-entries | Sponsor share (on completion) |
|-------|---------|--------------|-----------|-------------------------------|
| L1    | 3       | $0.60        | 1         | —                             |
| L2    | 9       | $1.50        | 3         | $0.27 (10% of $2.70 gross)    |
| L3    | 27      | $3.60        | 9         | $0.81 (10% of $8.10 gross)    |

**Sponsor share:** Identical model to Stream — at L2/L3 an extra 10% of the level's gross is credited to the owner's sponsor on level completion, paid from the platform pool (not deducted from the owner's wallet). Boost is always tier 1, so no multiplier. *(The older per-position milestone model — 5th/4th/20th member → $0.30 — was retired.)*

---

### Wallet Credit Split

Every wallet income credit applies two deductions, **both computed off the gross**:

1. **10% software fee** (of gross) → platform profit (not credited to any wallet)
2. **20% repurchase reserve** (of gross) → auto-held per tier

Effective split: **70% main wallet** (withdrawable) + **20% repurchase reserve** + **10% platform fee**.

When the repurchase reserve for a tier reaches its **threshold (price + gas)**, the platform automatically re-buys that same tier from the reserve — see [Auto-Repurchase](#auto-repurchase).

> Account balance (deposits / transfers) is credited at 100% — no deductions.

---

### Auto-Repurchase

Implemented in `app/core/repurchase.py`. Every income credit holds back 20% into the earner's per-tier `REPURCHASE` wallet. When a tier's reserve reaches its threshold (**pack price + the flat platform fee**, i.e. the same total cost as a manual buy), the platform automatically re-buys that **same tier** from the reserve — automatic and **unbounded** (a manual purchase happens once; repurchases keep going while the reserve can afford them).

| Tier    | Base  | Platform fee | Threshold |
|---------|-------|--------------|-----------|
| Agent 1 | $10   | $1   | **$11**  |
| Agent 2 | $20   | $2   | **$22**  |
| Agent 3 | $50   | $5   | **$55**  |
| Agent 4 | $100  | $11  | **$111** |

- A repurchase **acts like a normal purchase**: it re-runs the Core 60% compressed/odd-even split to eligible uplines (credited via `credit_wallet`, so uplines build their **own** reserve → intended **compounding**) plus the Stream/Boost matrix placement + payout cascade.
- The buy is recorded as a `REPURCHASE_BUY` ledger row, the platform fee as a `REPURCHASE_GAS` row (→ platform profit; the same flat fee charged on a manual purchase). Boost reserve always accrues in the **tier-1** bucket (single global queue), so Boost-driven repurchases re-buy Agent 1.
- Driven by `sweep_auto_repurchases(db)`, run inside the `/distribution/pack/status` success transaction (after the matrices). It re-scans every reserve each round so the upline compounding cascade is fully drained, with a step cap as a loop guard. Reserves of frozen/inactive users are **held**, not consumed.
- **Frontend support:** `GET /wallet/repurchase` (per-tier reserve, threshold, `progress_percent`, `ready` — for the progress bar) and `GET /wallet/repurchase/history` (executed repurchases).
- On-chain **broadcasting** of the repurchase from the platform reserve wallet is **not yet wired** — this is the internal accounting layer.
- **Migration:** existing DBs run `cd backend && python migrate_v17.py` once (adds `repurchase_buy` / `repurchase_gas` / `admin_credit` + the matrix pool types to the Postgres `transactiontype` enum); `create_tables.py` covers fresh installs.

---

## User Journey

```
1. Register (sponsor's username required + BEP-20 wallet address)
2. Verify email via OTP
3. Login → Dashboard
4. Deposit USDT via NOWPayments invoice
5. Account balance credited on payment confirmation
6. Purchase Agent tier(s) from account balance
7. Three revenue engines activate automatically
8. Earn through Core (upline) + Stream (matrix) + Boost (matrix)
9. Auto-repurchase triggers when reserve fills
10. Register BEP-20 withdrawal address (OTP verified)
11. Withdraw from main wallet (min $10, instant payout)
```

---

## Auth Flow

```
POST /auth/register          → creates user (sponsor_username REQUIRED, optional BEP-20 wallet_address), sends OTP
POST /auth/verify-email      → verify OTP, mark email verified
POST /auth/login             → login with USERNAME + password → returns JWT (blocked until email verified)

Password reset:
POST /auth/forgot-password   → sends reset OTP (1h expiry)
POST /auth/reset-password    → validates OTP, sets new password

Resend OTP:
POST /auth/resend-verification → sends a fresh OTP

Username availability check:
GET  /auth/check-username?username=<name> → { "available": true/false }
```

**Note:** Every user must register under a sponsor — the sponsor's **username** is required. The platform admin is the root sponsor and is created directly in the database.

The register form validates **live** as you type: username availability, **sponsor existence** (both via `GET /auth/check-username`), and the **BEP-20 wallet address** format (`0x` + 40 hex). An invalid sponsor or wallet address blocks submission with inline feedback. The wallet address is stored on the user and later used by the distribution endpoint below.

---

## Deposit & Purchase Flow

```
Deposit (top up account balance):
POST /deposit                         → creates NOWPayments USDT invoice
[User pays invoice URL]
POST /webhooks/nowpayments/ipn        → HMAC-verified; credits ACCOUNT balance

Purchase (spend account balance):
POST /agents/purchase                 → deducts ACCOUNT balance, queues Celery
Celery: activate_purchase             → revenue split → Core routing → matrix placement → payouts → email

Transfer (user-to-user):
POST /deposit/transfer                → 1% fee; first transfer to new recipient requires OTP
POST /deposit/transfer/verify         → confirm OTP; executes transfer

GET  /deposit/balance                 → { "account_balance": <float> }
GET  /deposit                         → deposit history
```

---

## Matrix System

Both Stream and Boost use a 3×3 breadth-first forced matrix:

```
Position (you)
├── Slot 1  ──┬── Slot 4
│             ├── Slot 5
│             └── Slot 6
├── Slot 2  ──┬── Slot 7
│             ├── Slot 8
│             └── Slot 9
└── Slot 3  ──┬── Slot 10
              ├── Slot 11
              └── Slot 12

L1 = 3 filled  (Slots 1–3)
L2 = 9 filled  (Slots 4–12)
L3 = 27 filled (next ring)
```

Concurrency is protected via PostgreSQL `SELECT FOR UPDATE` on `MatrixCounter` rows, preventing race conditions under parallel activations.

---

## Withdrawal Flow

```
POST /wallet/address           → register BEP-20 address; sends OTP
POST /wallet/address/verify    → confirm OTP; marks address verified
GET  /wallet/addresses         → list verified addresses
DELETE /wallet/address/{id}    → remove a registered address

POST /wallet/withdraw          → min $10, deducts from MAIN wallet
                                 queues Celery process_withdrawal immediately
Celery: process_withdrawal     → POST NOWPayments /v1/payout (USDT BEP-20)
  Success → status=sent, sends "dispatched" email
  Failure → status=failed, refunds to MAIN wallet, sends "refund" email (retries 3×)

GET  /wallet/withdrawals       → full withdrawal history
```

---

## TokenPocket Distribution Endpoint

A **single consolidated, read-only** endpoint that powers the frontend's TokenPocket DApp +
MultiSender contract integration (per the client's "Decentralized Deposit & Distribution System"
spec). The backend does not integrate TokenPocket itself — it only exposes *where the money should
go*. The frontend/blockchain team handles wallet connection and the on-chain distribution.

```
GET /distribution/wallet-map     → JWT auth. Returns the caller's wallet address + profit,
                                   plus the downline subtree under them, each user with their
                                   wallet address + profit.
  Query params:
    username=<name>   → admin-only: build the map for another user
    direct_only=true  → only direct (level-1) referrals instead of the full subtree
    limit / offset    → paginate the flattened downline (default/max 500)
```

**Response shape (JSON):**

```json
{
  "user": {
    "user_id": 12, "username": "alice", "level": null,
    "wallet_address": "0x…", "wallet_address_source": "registration",
    "has_wallet_address": true, "is_active": true,
    "profit": {
      "total_earned": 412.50, "main_balance": 318.20, "repurchase_balance": 41.25,
      "account_balance": 60.00, "withdrawable": 378.20
    }
  },
  "downline": {
    "total": 4, "count": 4, "limit": 500, "offset": 0, "direct_only": false,
    "users": [ { "...same shape, level: 1, 2, …": "…" } ]
  },
  "generated_at": "2026-06-10T11:42:08Z"
}
```

- **Distribute against `profit.withdrawable`** (= account balance + all main-wallet earnings, mirroring
  the Withdraw page). Skip users where `has_wallet_address` is `false`.
- **Real-time, no admin approval** — amounts are summed live from the ledger on every call.
- **Wallet address** is taken from the user's registration field, falling back to their most recent
  **verified** withdrawal address (`wallet_address_source` tells you which).
- Read-only and N+1-free (batched, grouped queries) — never moves funds.

Typical frontend usage:

```js
const { user, downline } = await fetchWalletMap()
const payouts = [user, ...downline.users]
  .filter(u => u.has_wallet_address && u.profit.withdrawable > 0)
  .map(u => ({ to: u.wallet_address, amount: u.profit.withdrawable }))
// → feed `payouts` into the MultiSender contract
```

---

## On-Chain Pack Purchase

The **on-chain rail** (BEP-20 USDT) is how packs are bought. When a user buys a pack, the
frontend pays the split **directly on-chain** from the buyer's connected wallet (one batched
MultiSender call). The backend (1) returns the validated recipient split and (2) records the
outcome and runs the **full revenue engine** internally.

The split is the **complete 60 / 30 / 10 model** (not Core-only): Core 60% → eligible uplines,
Stream 30% → the per-tier Stream pool wallet, Boost 9% → the global Boost pool wallet, and 1% →
the admin income wallet. Each upline's Core commission is paid out on-chain under the **70 / 20 / 10
wallet rule** — 70% to the upline's address, 20% to the repurchase-reserve wallet, 10% to the
software-fee wallet. On `pack/status` **success** the backend: creates an **active `AgentPurchase`
ownership row** (agent shows OWNED, the sequential-unlock gate works, buyer becomes Core-eligible),
writes reporting ledger rows, **runs the Stream + Boost matrix placement + payout cascade**
(`run_purchase_matrices`, crediting internal wallets via `credit_wallet`), and **sweeps
auto-repurchases** (`sweep_auto_repurchases`) for any reserve that has reached its threshold. So
the internal wallets, matrices, and repurchase reserve **do** populate on this rail.

```
POST /distribution/pack/purchase   → JWT. Body: { "pack_name": "Agent 1", "amount"?: 10 }
   → returns purchase_id + the recipient split (buyer, upline levels, platform_fee)
POST /distribution/pack/status     → JWT. Body: { purchase_id, status, tx_hash?, failure_reason? }
   → records the on-chain result (success/failed)
```

**Split rule — full 60 / 30 / 10:** Core 60% → two 30% halves to the **first two eligible uplines**
(eligible = active **and** highest active tier ≥ buyer's tier; compression + odd/even), Stream 30%
→ the per-tier Stream pool wallet, Boost 9% → the global Boost pool wallet, admin 1% → the admin
income wallet. Each Core upline commission is further split **70 / 20 / 10** (upline / repurchase
reserve / software fee). A Core half with no eligible upline (or no valid BEP-20 address) is folded
into the platform fee, so **the split always sums to the pack price**. (Split logic in
`app/core/pack_payout.py`; matrix + repurchase execution on `pack/status` in
`app/core/matrix_runtime.py` + `app/core/repurchase.py`.)

**API 1 — request:**

```json
{ "pack_name": "Agent 1", "amount": 10 }
```

**API 1 — response** (example, $10 pack with two eligible uplines):

```json
{
  "purchase_id": "ord_07f33afb8fdd",
  "currency": "USDT",
  "network": "BEP-20",
  "token_contract": "0xb2681F1CA80e080827d5f275648D2d2e2684f0C8",
  "decimals": 18,
  "recipients": [
    { "role": "buyer",             "level": 0,    "wallet_address": "0x…", "has_wallet_address": true, "amount": 0.0 },
    { "role": "upline",            "level": 1,    "wallet_address": "0x…", "has_wallet_address": true, "amount": 2.10, "gross_amount": 3.0 },
    { "role": "upline",            "level": 2,    "wallet_address": "0x…", "has_wallet_address": true, "amount": 2.10, "gross_amount": 3.0 },
    { "role": "repurchase_reserve","level": null, "wallet_address": "0x…", "has_wallet_address": true, "amount": 1.20 },
    { "role": "software_fee",      "level": null, "wallet_address": "0x…", "has_wallet_address": true, "amount": 0.60 },
    { "role": "stream_pool",       "level": null, "wallet_address": "0x…", "has_wallet_address": true, "amount": 3.0 },
    { "role": "boost_pool",        "level": null, "wallet_address": "0x…", "has_wallet_address": true, "amount": 0.90 },
    { "role": "admin",             "level": null, "wallet_address": "0x…", "has_wallet_address": true, "amount": 0.10 }
  ]
}
```

> $10 pack, two eligible uplines: each upline's $3 Core half is paid 70/20/10 → **$2.10** on-chain
> + **$0.60** reserve + **$0.30** fee (reserve/fee shown summed across uplines). Stream $3 + Boost
> $0.90 + admin $0.10 complete the $10. Roles and amounts vary with eligibility.

**API 2 — request / response:**

```json
// request
{ "purchase_id": "ord_07f33afb8fdd", "status": "success", "tx_hash": "0x…", "failure_reason": null }
// response
{ "purchase_id": "ord_07f33afb8fdd", "status": "success", "recorded_at": "2026-06-22T08:52:45Z" }
```

- `buyer` is informational (`amount: 0`) so the frontend can confirm it matches the connected wallet.
- Send on-chain to every recipient where `has_wallet_address` is `true`; skip the rest.
- `status: "success"` requires a valid `tx_hash` (0x + 64 hex); re-recording a finalized order → 400.
- **On success the backend runs the full engine internally** (idempotent, runs once): an active
  `AgentPurchase` ownership row (dup-tier guarded) + reporting `Transaction` rows (buyer
  `agent_purchase`, each upline `core_income`) + the **Stream/Boost matrix cascade**
  (`run_purchase_matrices`, crediting wallets via `credit_wallet`) + the **auto-repurchase sweep**
  (`sweep_auto_repurchases`). Internal main / repurchase-reserve balances populate accordingly.
- **Live wallet balance:** the "Wallet Balance" card on the Dashboard, Wallet, and Buy Agents pages
  shows the connected wallet's **live on-chain USDT** (`frontend/src/hooks/useUsdtBalance.js`), not an
  internal balance. It requires `VITE_USDT_ADDRESS` to **match the backend `USDT_CONTRACT`** (else it
  reads a different token and shows `$0`); restart the Vite dev server after editing `.env`.
- Order records live in `pack_purchases` (`app/models/pack_purchase.py`). Run `python migrate_v15.py`
  once on existing DBs; `create_tables.py` covers fresh installs.
- Config (`.env`): `USDT_CONTRACT`, `USDT_DECIMALS`, `PAYOUT_CURRENCY`, `PAYOUT_NETWORK`,
  `PLATFORM_FEE_WALLET` (**set before go-live**), `VERIFY_ONCHAIN_TX` (optional tx verification, off
  by default), plus the pool/income wallets `STREAM_POOL_WALLET`, `BOOST_POOL_WALLET`,
  `ADMIN_INCOME_WALLET`, `REPURCHASE_RESERVE_WALLET` (each falls back to `PLATFORM_FEE_WALLET` when
  unset — set distinct addresses before go-live).

---

## Tech Stack

| Layer        | Technology                                     |
|--------------|------------------------------------------------|
| Frontend     | Vite + React 18 + Tailwind CSS                 |
| Backend      | FastAPI (Python 3.11+)                         |
| Database     | PostgreSQL 18                                  |
| Auth         | JWT — python-jose + passlib/bcrypt==4.0.1      |
| Payments     | On-chain USDT (BEP-20) via TokenPocket / MultiSender DApp |
| Email        | SMTP (Gmail App Password or any provider)      |

> **Note:** Packs are bought **on-chain** (BEP-20 USDT via TokenPocket / MultiSender) — the legacy
> deposit-first money rail (NOWPayments deposits / withdrawals / transfers) and Celery/Redis were
> removed (the backend is fully synchronous). The **Core / Stream / Boost revenue engine and
> auto-repurchase are live** and run on the on-chain rail at `pack/status` success (`pack_payout.py`,
> `matrix_runtime.py`, `repurchase.py`). A few sections below (User Journey, Deposit & Purchase Flow,
> Withdrawal Flow) still reference the removed NOWPayments deposit/withdrawal/transfer steps and are
> retained as historical context only — the revenue mechanics they describe are current.

---

## Setup & Installation

### Prerequisites

- Python 3.11+ (conda env `luxus` recommended)
- PostgreSQL 18 on localhost:5432 with database `luxus` and user `luxus`
- Node.js 18+

### 1. Clone & configure

```bash
cp .env.example .env
# Edit .env — fill in SMTP credentials, SECRET_KEY, ADMIN_* fields,
# and the on-chain settings (USDT_CONTRACT, PLATFORM_FEE_WALLET, etc.)
```

### 2. Install backend dependencies

```bash
conda activate luxus
pip install -r requirements.txt
```

### 3. Create database tables (fresh install — run once)

```bash
cd backend
python create_tables.py
```

### 4. Seed the admin user (run once)

```bash
cd backend
python seed_admin.py
```

Reads `ADMIN_EMAIL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_REFERRAL_CODE` from `.env`. Safe to re-run — exits early if admin already exists.

### 5. Install frontend dependencies

```bash
cd ../frontend
npm install
```

---

## Running the Project

```bash
# Terminal 1 — Backend API (no Celery worker needed — fully synchronous)
conda activate luxus
cd backend
uvicorn app.main:app --reload
# API → http://localhost:8000
# Swagger → http://localhost:8000/docs

# Terminal 2 — Frontend dev server
cd frontend
npm run dev
# App → http://localhost:3000
```

---

## Admin Setup

The platform admin cannot self-register. Create via seed script:

```bash
# In .env:
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=StrongPassword@123
ADMIN_REFERRAL_CODE=ADMIN001

cd backend
python seed_admin.py
```

Admin logs in at `http://localhost:3000` and is automatically routed to `/admin`.

**Admin capabilities:**
- Platform-wide stats (platform profit, total deposited by users, total invested by users) and transaction history (resolved to usernames)
- View per-user details (agents bought, account balance, revenue generated); freeze / unfreeze individual users
- **Treasury** — *Send to User* by username, instantly and fee-free (kept fully separate from the user deposit/transfer/withdraw flows). *(The *Generate* / fund-minting feature and the "Treasury Balance" dashboard card were removed; the `ADMIN_GENERATE` ledger type is retained only for historical reporting.)*
- **Global freeze (kill switch)** — one click pauses all user deposits, withdrawals, transfers, and purchases platform-wide; only an admin can lift it
- Review and manage all withdrawal requests

---

## Environment Variables

| Variable                    | Description                                                   |
|-----------------------------|---------------------------------------------------------------|
| `DATABASE_URL`              | PostgreSQL connection string                                  |
| `SECRET_KEY`                | JWT signing secret (long random string)                       |
| `APP_ENV`                   | `development` or `production`                                 |
| `LOG_LEVEL`                 | `DEBUG` / `INFO` / `WARNING` / `ERROR` — log verbosity (default `INFO`) |
| `CORS_ORIGINS`              | Comma-separated allowed frontend origins, or `*`. Set to your frontend URL in production |
| `PLATFORM_FEE_WALLET`       | BEP-20 wallet that receives the pack-purchase platform fee (**set before go-live**); also the fallback for the four wallets below |
| `STREAM_POOL_WALLET`        | Receives the Stream 30% pool (falls back to `PLATFORM_FEE_WALLET`)             |
| `BOOST_POOL_WALLET`         | Receives the Boost 9% pool (falls back to `PLATFORM_FEE_WALLET`)               |
| `ADMIN_INCOME_WALLET`       | Receives the 1% Boost-allocation admin cut (falls back to `PLATFORM_FEE_WALLET`) |
| `REPURCHASE_RESERVE_WALLET` | Receives the 20% repurchase reserve (falls back to `PLATFORM_FEE_WALLET`)      |
| `USDT_CONTRACT`             | USDT token contract on the active chain (returned by `pack/purchase`)         |
| `USDT_DECIMALS`             | USDT token decimals (e.g. 18)                                                  |
| `PAYOUT_CURRENCY` / `PAYOUT_NETWORK` | Currency / network labels returned by `pack/purchase` (USDT / BEP-20) |
| `VERIFY_ONCHAIN_TX`         | If true, `pack/status` verifies the tx_hash on-chain before recording success (off by default) |
| `FRONTEND_URL`              | Public URL of **frontend** — used in payment redirects + email links |
| `SMTP_SERVER`               | SMTP host (e.g. `smtp.gmail.com`)                             |
| `SMTP_PORT`                 | SMTP port (587 for TLS)                                       |
| `SMTP_USERNAME`             | SMTP login username                                           |
| `SMTP_PASSWORD`             | Gmail App Password or SMTP password                           |
| `SENDER_EMAIL`              | From address for outgoing emails                              |
| `ADMIN_EMAIL`               | Admin account email (used by `seed_admin.py`)                 |
| `ADMIN_USERNAME`            | Admin account username                                        |
| `ADMIN_PASSWORD`            | Admin account password                                        |
| `ADMIN_REFERRAL_CODE`       | Admin's own referral code (root sponsor for first users)      |

### Frontend (Vite, build-time)

| Variable                   | Description                                                                 |
|----------------------------|-----------------------------------------------------------------------------|
| `VITE_API_URL`             | Backend API base URL. **Leave unset for local dev** (uses `/api` + Vite proxy) and for same-domain hosting behind a reverse proxy. **Set it only when the frontend and backend are on different domains** (e.g. `https://api.yourdomain.com`). Place in `frontend/.env.production` or `.env.local`. |
| `VITE_REOWN_PROJECT_ID`    | WalletConnect / Reown AppKit project ID (free at [cloud.reown.com](https://cloud.reown.com)) — required for wallet connection. |
| `VITE_MULTISENDER_ADDRESS` | MultiSender contract that batches the on-chain pack-purchase payout. |
| `VITE_USDT_ADDRESS`        | USDT token contract for the on-chain rail. **Must match the backend `USDT_CONTRACT`** so the live "Wallet Balance" card reads the same token used for purchases (a mismatch shows `$0`). |
| `VITE_USDT_DECIMALS`       | USDT token decimals fallback (the balance hook also reads decimals on-chain). |

> **Hosting note:** the backend's `FRONTEND_URL` / `CORS_ORIGINS` point at the frontend; the frontend's `VITE_API_URL` (if needed) points at the backend. Same-domain deploys behind a reverse proxy that routes `/api → backend` need no `VITE_API_URL`.

> **Vite reads `.env` only at startup** — restart `npm run dev` after editing any `VITE_*` variable.

---

## Key Notes

- `APP_ENV=development` always hits the NOWPayments sandbox — no real funds used.
- **Logging:** all logs use a single timestamped format (`time | LEVEL | logger | message`), configured in `app/logging_config.py` and controlled by `LOG_LEVEL`. A request-logging middleware records every call with its **duration** (4xx/5xx at WARNING), and unhandled errors are logged with a full traceback. Use `LOG_LEVEL=DEBUG` temporarily to trace an issue, then switch back to `INFO`.
- **NOWPayments payouts (withdrawals)** require the payout API's JWT auth (`/v1/auth`) **+ 2FA** in production — the API key alone (sufficient for deposits) will be rejected for outgoing payouts. Sandbox is more lenient; verify against the live payout API before go-live.
- All financial amounts use Python `Decimal` — no float precision errors.
- Matrix concurrency uses PostgreSQL `SELECT FOR UPDATE` on `MatrixCounter`.
- Celery tasks retry up to 3× on failure (60s delay for purchases, 300s for withdrawals).
- **bcrypt is pinned to 4.0.1** — bcrypt 5.x breaks passlib; do not upgrade.
- `POST /agents/purchase/{id}/confirm` is **dev-only** — remove before production.
- **Login is by username + password** — for both users and admin.
- Each agent tier can be purchased **once**, and tiers must be bought in order **1 → 2 → 3 → 4** (auto-repurchase is the only exception).
- Sponsor is identified by **username** at registration (not a referral code).
- Username availability is checked in real-time during registration; the **sponsor username is also validated live** (must exist) and a **BEP-20 wallet address** is collected and format-validated on the register form — both block submission when invalid. Transfer forms (user + admin) validate the recipient username live (must exist).
- **`GET /distribution/wallet-map`** is the single consolidated, read-only endpoint for the TokenPocket / MultiSender integration — returns a user + their downline with each one's wallet address and profit. Distribute against `profit.withdrawable`; skip rows with `has_wallet_address: false`. See [TokenPocket Distribution Endpoint](#tokenpocket-distribution-endpoint).
- The user's BEP-20 address comes from `User.wallet_address` (collected at registration, optional on the backend) and falls back to a verified withdrawal address. Existing DBs: run `cd backend && python migrate_v14.py` (idempotent — adds the nullable `users.wallet_address` column). Fresh installs are covered by `create_tables.py`.
- Minimum withdrawal is **$10**; it draws from the user's **combined balance** (account balance + all earnings). Minimum transfer is **$1**.
- Withdrawal addresses must be OTP-verified before a withdrawal can be submitted.
- Transfer fee is **1%** — sender is debited the full amount; recipient receives 99%.
- First transfer to a new recipient requires email OTP confirmation.
- **Admin Treasury** (*Send to User*) and the **global freeze** kill switch are admin-only and separate from user flows. *(The Treasury *Generate* feature + dashboard "Treasury Balance" card were removed; `POST /admin/generate` no longer exists, though the `admin_generate` ledger type stays for historical data.)*
- **All timestamps are displayed in IST (`Asia/Kolkata`).** The backend stores naive UTC; the frontend converts via `frontend/src/utils/datetime.js` (`formatDateTimeIST` / `formatDateIST` / `formatTimeIST`). Storage stays UTC — only the display is localized to Indian time.
- **Transaction types are lowercase enum values** (`agent_purchase`, `deposit`, `core_sent`, …). Transaction views (`Transactions.jsx`, `Wallet.jsx`, `admin/AdminTransactions.jsx`) classify them into Income / Expense / System groups using **lowercase** keys; `core_sent` is an audit record of the Core split sent upline at purchase and is **not** counted as income. `withdrawal_refund` (a failed-payout reversal) is also classified as System, not income. *(`Wallet.jsx` previously used UPPERCASE keys, which matched nothing and rendered every row as a green "+" — fixed to lowercase.)*
- **On-chain "Wallet Balance"** shown on the Dashboard, Wallet, and Buy Agents pages is the connected wallet's **live on-chain USDT** (`frontend/src/hooks/useUsdtBalance.js`), not an internal balance. Set `VITE_USDT_ADDRESS` to match the backend `USDT_CONTRACT`, connect a wallet, and restart the Vite dev server. On-chain purchases **do** populate internal wallets: on `pack/status` success each Core commission is credited 70/20/10 (`mirror_onchain_earning_split`) and the Stream/Boost matrix payouts credit via `credit_wallet`, so main / repurchase-reserve balances fill and on-chain activity also shows in transaction history and the income chart.
