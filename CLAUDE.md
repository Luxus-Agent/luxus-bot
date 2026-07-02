# Luxus Agent Revenue Sharing Platform

Multi-tier passive-income MLM platform. Users buy AI-agent tiers **on-chain** (USDT BEP-20)
for a cost of **base + flat platform fee** — **$11 / $22 / $55 / $111** ($10/$20/$50/$100 base
+ $1/$2/$5/$11 fee → platform profit). The 60/30/10 split runs off the base; each purchase
drives three parallel revenue engines. Prices/fees live in `models/agent.py`
(`AGENT_TIER_PRICES`, `AGENT_TIER_PLATFORM_FEE`, `AGENT_TIER_COST`).

> Full architecture, API shapes, payout schedules, and env reference live in **@README.md** —
> read it for detail. This file is the lightweight rules + map. Keep it **under 200 lines**.

## Stack

- **Frontend:** Vite + React + Tailwind (port 3000, `/api` proxy → `:8000`)
- **Backend:** FastAPI, **fully synchronous** — NO Celery/Redis (removed)
- **DB:** PostgreSQL 18 — `postgresql://luxus:dhanush@localhost/luxus`
- **Auth:** JWT (python-jose + passlib). **bcrypt pinned to 4.0.1** — 5.x breaks passlib, DO NOT upgrade
- **Payments:** On-chain USDT (BEP-20) via TokenPocket / MultiSender DApp. NO internal deposit/withdrawal/transfer money rail

## Architecture / Key Files

```
frontend/src/
  api/client.js          # Axios + JWT interceptor (VITE_API_URL || '/api')
  context/AuthContext.jsx # login (token + /auth/me), logout
  hooks/useUsdtBalance.js # live on-chain USDT balance (wagmi balanceOf)
  pages/ + pages/admin/   # user + admin dashboards
backend/app/
  api/auth.py            # register (sponsor_username), verify-email, login (username), reset
  api/wallet.py          # balances / transactions / earnings / repurchase / BEP-20 address
  api/agents.py          # GET /agents/purchases (read-only ownership)
  api/admin.py           # users, freeze/unfreeze, treasury transfer, platform freeze, manual credit
  api/distribution.py    # wallet-map + on-chain pack rail (/pack/purchase, /pack/status)
  core/pack_payout.py    # Core 60% split (compression + odd/even); also Stream/Boost/admin rates
  core/proactive.py      # Core eligibility/compression helpers
  core/matrix_engine.py + matrix_runtime.py  # Stream + Boost 3x3 matrices (LIVE)
  core/repurchase.py     # auto-repurchase sweep (LIVE)
  core/wallet_ops.py     # credit_wallet (70/20/10), mirror_onchain_earning_split, ledger earnings
  models/                # user, agent, wallet, wallet_address, transaction, pack_purchase, matrix, platform_setting
```

## Revenue Model (LIVE — runs on the on-chain rail)

Every pack purchase applies a **60 / 30 / 10 split** (executed inside `POST /distribution/pack/status` on success):

- **Core 60%** → two 30% halves up the sponsor chain. Two rules **together, Core only**:
  - **Compression:** an upline qualifies only if their highest active tier ≥ buyer's tier; lower/inactive/frozen are skipped (income compresses up).
  - **Odd/even** (`User.core_route_count`, incremented every targeting): odd → keep, even → pass up to next eligible upline.
  - No eligible upline / no valid BEP-20 address → folds into platform fee.
- **Stream 30%** → per-tier 3×3 matrix. Re-entries are **dummy** (no payout). 10% sponsor share at L2/L3.
- **Boost 10%** = **9% matrix + 1% admin income**. **Single global queue** (always tier 1). Re-entries are **real**.
- **Wallet rule (70 / 20 / 10):** every income credit → 70% main + 20% per-tier repurchase reserve + 10% software fee.
  Core uses `mirror_onchain_earning_split`; Stream/Boost matrix payouts use `credit_wallet`.
- **Auto-repurchase:** when a tier's reserve hits **threshold = price + platform fee** ($11 / $22 / $55 / $111),
  the platform auto re-buys that same tier, unbounded — re-runs Core + matrices (compounding). The flat fee → platform profit.
  Boost reserve accrues in tier-1. Frozen/inactive reserves are held. See `core/repurchase.py`.

> Payout schedules per tier/level are in @README.md (Revenue Mechanics).

## Conventions — YOU MUST

- **All money uses Python `Decimal`** — never float.
- **Transaction types are lowercase enum *values*** (`agent_purchase`, `core_income`, …). Frontend classifies with **lowercase** Income/Expense/System sets — NEVER uppercase keys (past bug: summed every row).
- **Timestamps stored naive UTC, displayed IST** (`Asia/Kolkata`). Use `frontend/src/utils/datetime.js` (`formatDateTimeIST` etc.) — never `new Date(x).toLocaleString()` on backend timestamps.
- **Sponsor identified by username** at registration (`sponsor_username`, required). Root/admin has no sponsor (`seed_admin.py`).
- **Login is username + password** (not email) for users AND admin. Login blocked until email verified (403).
- **Total Earnings = ledger, not wallets** — `GET /wallet/earnings` (`get_ledger_earnings`). The earnings fetch is non-fatal (falls back to $0).
- **One purchase per tier, sequential 1→2→3→4.** Enforced in BOTH frontend AND backend (`pack/purchase` gate). Auto-repurchase is the only re-buy path and bypasses the gate.
- **Don't commit credentials.** `.env` is gitignored; `.env.example` is the template.

## On-chain Pack Rail (the only purchase path)

- `POST /distribution/pack/purchase` (JWT, `require_platform_active`) → returns recipient split (sums to price). Roles: `buyer`, `upline` (70% + `gross_amount`), `repurchase_reserve`, `software_fee`, `stream_pool`, `boost_pool`, `admin`, `platform_fee`.
- `POST /distribution/pack/status` → records success(tx_hash)/failed; on success runs ownership + ledger + matrices + repurchase (idempotent, PENDING-guarded).
- `GET /distribution/wallet-map` → read-only user+downline wallet/profit map for MultiSender. Distribute against `profit.withdrawable`.
- Wallet/pool config (`.env`, each falls back to `PLATFORM_FEE_WALLET`): `STREAM_POOL_WALLET`, `BOOST_POOL_WALLET`, `ADMIN_INCOME_WALLET`, `REPURCHASE_RESERVE_WALLET`. **Set distinct addresses before go-live.**

## Removed (do not reintroduce without asking)

- NOWPayments deposit-first rail: `/deposit`, user-to-user `/deposit/transfer`, `/wallet/withdraw`, account-balance `/agents/purchase`.
- Celery/Redis + `app/workers/`. Admin treasury *Generate* / mint feature.
- Legacy tables (`deposits`, `withdrawal_requests`, `webhook_events`, `transfer_verifications`) left in DB, no longer read.

## Workflow

```bash
# Backend
conda activate luxus && cd backend && uvicorn app.main:app --reload   # :8000, /docs
# Frontend
cd frontend && npm run dev                                            # :3000
# Fresh DB: python create_tables.py && python seed_admin.py
# Existing DB migrations: migrate_v14/v15/v17/v18/v19.py; backfill_repurchase_reserve.py
```

- **Touch only what you must** — this is a financial system; keep changes scoped.
- Restart Vite after editing any `VITE_*` env. `VITE_USDT_ADDRESS` MUST match backend `USDT_CONTRACT` (else balance card shows $0).
- `LOG_LEVEL=DEBUG` to trace (request middleware logs method/path/status/duration), then revert to INFO.
- **Platform freeze** (admin kill switch) guards `pack/purchase` → HTTP 423 while frozen; admins bypass.
