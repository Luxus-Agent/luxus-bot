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
  hooks/useUsdtBalance.js # live on-chain USDT balance (wagmi balanceOf), silently repolls every 20s while connected
  components/CoreRoutingViz.jsx # shared Core explainer diagram + routing-chain UI (admin + user)
  components/EarningsBreakdown.jsx # shared Completed/Pending/Fee breakdown rows — user Dashboard "Total Earnings"
                          # card + Transactions "Total In" tile (both click-to-expand); always foots to the total
  pages/RevenueEngine.jsx # user: self-scoped Core routing preview (no Stream/Boost — platform-wide)
  pages/ + pages/admin/   # user + admin dashboards (admin: AdminRevenueEngines.jsx — Core/Stream/Boost viz)
                          # NOTE: no standalone Wallet page — balances/history live in Dashboard + Transactions
backend/app/
  api/auth.py            # register (sponsor_username), verify-email, login (username), reset — usernames case-insensitive
  api/wallet.py          # balances / transactions (+ tx_hash) / earnings (+ Completed/Pending split) / repurchase / BEP-20 address / core-preview
  api/agents.py          # GET /agents/purchases (read-only ownership)
  api/admin.py           # users, freeze/unfreeze, treasury transfer, platform freeze, manual credit, matrix/core viz, live on-chain wallet balances
  api/distribution.py    # wallet-map + on-chain pack rail (/pack/purchase, /pack/status)
  core/onchain.py        # auto-repurchase on-chain settlement + read-only USDT/BNB balance lookups for admin's 3 platform wallets
  core/pack_payout.py    # Core 60% split (compression + odd/even); also Stream/Boost/admin rates
  core/proactive.py      # Core eligibility/compression helpers
  core/core_preview.py   # read-only Core routing simulator (upline) + downline odd/even table, shared admin + user
  core/matrix_engine.py + matrix_runtime.py  # Stream + Boost 3x3 matrices (LIVE)
  core/matrix_flow.py    # read-only queue-flow reconstruction (position stack + re-entry spawn pairing) for admin viz
  core/repurchase.py     # auto-repurchase sweep (LIVE)
  core/wallet_ops.py     # credit_wallet (70/20/10), mirror_onchain_earning_split, ledger earnings, tx_hash resolver
  core/user_lookup.py    # case-insensitive username lookup/equality — use for ALL username matching, never User.username ==
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
  Core uses `mirror_onchain_earning_split`; Stream/Boost matrix payouts use `credit_wallet`. The ledger income
  `Transaction` row itself (`CORE_INCOME`/`STREAM_PAYOUT`/`BOOST_PAYOUT`/`SPONSOR_MILESTONE_INCOME`) always records
  the **full gross commission**, not the 70% net — see Total Earnings convention below. Any aggregate that
  estimates "money credited to internal wallets" (e.g. `/admin/metrics`'s `total_credited_to_wallets`) must
  apply the 70% rate to Stream/Boost/Sponsor **only** — Core's 70% is never credited to an internal wallet at all.
- **Auto-repurchase:** when a tier's reserve hits **threshold = price + platform fee** ($11 / $22 / $55 / $111),
  the platform auto re-buys that same tier, unbounded — re-runs Core + matrices (compounding). The flat fee → platform profit.
  Boost reserve accrues in tier-1. Frozen/inactive reserves are held. See `core/repurchase.py`.

> Payout schedules per tier/level are in @README.md (Revenue Mechanics).

## Earnings Transparency — Completed vs Pending

`GET /wallet/earnings` returns `total_earned` (unchanged gross ledger sum) plus a
breakdown: **`completed`** (Core's 70% — already paid on-chain to the recipient's own
wallet at purchase time) + **`pending_reserve`** (live REPURCHASE wallet sum, all
tiers — building toward the next auto-repurchase) + **`pending_payout`** (live MAIN
wallet sum — Stream/Boost's 70% share, internal-only until an admin payout run pays
it out). These three **always foot exactly to `total_earned`**; the frontend derives
a 4th "platform software fee" line as the remainder so nothing is ever silently
unaccounted for. Shared UI: `components/EarningsBreakdown.jsx`, used by the user
Dashboard's "Total Earnings" card, the Transactions "Total In" tile, and mirrored
(same `PENDING` type list — `repurchase_hold` + `stream_payout`/`boost_payout`/
`sponsor_milestone_income`, NOT `core_income`) as a Completed/Pending Status column +
filter on both `Transactions.jsx` and `AdminTransactions.jsx` — keep them in sync.

## Revenue Engine Visualization (read-only)

- **Admin** `/admin/revenue-engines`: Core compression/odd-even simulator for **any** username
  (`GET /admin/core/simulate`) + a sponsor's direct-downline odd/even table, split left/odd vs
  right/even by join order (`GET /admin/core/downline`, `core.core_preview.get_downline_odd_even`,
  uses `User.sponsor_position`) + Stream/Boost matrix queue fill-state and contents
  (`GET /admin/matrix/overview`, `GET /admin/matrix/queue-slots`) + a full "queue-flow" diagram —
  every position in true arrival order with re-entries linked back to the position that spawned
  them (`GET /admin/matrix/queue-flow`, `core/matrix_flow.py`; "Flow View" toggle per level card).
  Spawn pairing is reconstructed (not stored) from `MatrixQueueSlot.is_reentry` + arrival order —
  see that module's docstring for why the reconstruction is exact, not heuristic.
- **User** `/revenue-engine`: same Core simulator, **self-scoped only** (`GET /wallet/core-preview`,
  no username param) — no Stream/Boost tab (those queues are platform-wide, not per-user).
- Core simulator/downline endpoints only **peek** at `core_route_count` (never persist) — safe to
  run repeatedly. Shared logic: `core/core_preview.py`; shared UI: `frontend/src/components/CoreRoutingViz.jsx`.

## Conventions — YOU MUST

- **All money uses Python `Decimal`** — never float.
- **Transaction types are lowercase enum *values*** (`agent_purchase`, `core_income`, …). Frontend classifies with **lowercase** Income/Expense/System sets — NEVER uppercase keys (past bug: summed every row).
- **Timestamps stored naive UTC, displayed IST** (`Asia/Kolkata`). Use `frontend/src/utils/datetime.js` (`formatDateTimeIST` etc.) — never `new Date(x).toLocaleString()` on backend timestamps.
- **Sponsor identified by username** at registration (`sponsor_username`, required). Root/admin has no sponsor (`seed_admin.py`).
- **Login is username + password** (not email) for users AND admin. Login blocked until email verified (403).
- **Usernames are case-insensitive, passwords are case-sensitive.** ALL username lookups (login, register dup-check,
  sponsor lookup, admin transfer/search, wallet-map, core-simulate) go through `core/user_lookup.get_user_by_username`
  / `usernames_equal` — never `User.username == ...` directly. Passwords are untouched (bcrypt hashes the exact string).
- **Total Earnings = ledger, not wallets, and is GROSS (before the platform fee)** — `GET /wallet/earnings`
  (`get_ledger_earnings`). Income `Transaction` rows record the full commission, not the 70% net wallet credit
  (see Wallet rule above). The earnings fetch is non-fatal (falls back to $0).
- **One purchase per tier, sequential 1→2→3→4.** Enforced in BOTH frontend AND backend (`pack/purchase` gate). Auto-repurchase is the only re-buy path and bypasses the gate.
- **`get_account_balance` (the ACCOUNT wallet) is always $0 on the on-chain rail** — there's no deposit path
  left to fund it (see Removed below). Don't surface it as a meaningful per-user figure (e.g. admin's
  `user_summary` shows `wallet_address` there instead — the actual thing worth showing an admin).
- **Admin Income (`ADMIN_INCOME` transactions, the 1% Boost cut) is tracked separately from Platform Profit**
  (`SOFTWARE_FEE` + `PLATFORM_PROFIT`) — different wallet, different `/admin/treasury/summary` field
  (`admin_income`), don't fold one into the other.
- **Don't commit credentials.** `.env` is gitignored; `.env.example` is the template.

## On-chain Pack Rail (the only purchase path)

- `POST /distribution/pack/purchase` (JWT, `require_platform_active`) → returns recipient split (sums to price). Roles: `buyer`, `upline` (70% + `gross_amount`), `repurchase_reserve`, `software_fee`, `admin`, `platform_fee` (the latter also carries the Stream 30% + Boost-pool 9% shares — tracked internally, no separate on-chain wallet).
- `POST /distribution/pack/status` → records success(tx_hash)/failed; on success runs ownership + ledger + matrices + repurchase (idempotent, PENDING-guarded).
  Both Transactions pages (user + admin) show a **Tx Hash** column (resolved via `wallet_ops.resolve_tx_hashes`,
  joining `Transaction.reference_id` → `PackPurchase.order_id` / `PayoutBatch.batch_id`) linking to BscScan —
  only rows tied to a settled on-chain event have one; pure ledger-only types (e.g. `stream_payout`) show `—`.
- `GET /distribution/wallet-map` → read-only user+downline wallet/profit map for MultiSender. Distribute against `profit.withdrawable`.
- Wallet config (`.env`): `PLATFORM_FEE_WALLET`, `ADMIN_INCOME_WALLET` / `REPURCHASE_RESERVE_WALLET` (each falls back to `PLATFORM_FEE_WALLET`). **Set distinct addresses before go-live**, and fund `REPURCHASE_RESERVE_WALLET` with BNB directly — it pays its own gas for its automated send (no separate gas wallet). `PLATFORM_FEE_WALLET` is receive-only (no signer key) — it's only ever a recipient address, never sends on-chain itself.
- `POST /distribution/payout/create` + `/payout/status` (admin-only) — runs the same MultiSender contract in reverse (platform wallet -> every member with a positive withdrawable balance) to actually pay out accumulated internal earnings. Mirrors `pack/purchase`/`pack/status`'s PENDING-guarded lifecycle; on success debits each recipient via `debit_withdrawable` so the money isn't offered again. This is the only member-payout rail — no automatic/unattended sweep.
- Auto-repurchase's on-chain settlement (`app/core/onchain.py`) is unattended by design (no admin approval step) — set `REPURCHASE_SIGNER_PRIVATE_KEY` (**live private key, treat like `SECRET_KEY`, never commit**) + `BSC_RPC_URL` to enable; empty key keeps it internal-ledger-only, today's default. Best-effort: any broadcast failure is logged and swallowed, never blocks a purchase.
- `GET /admin/treasury/onchain-wallets` (admin-only, read-only) — live USDT + native BNB balance for all
  three platform wallets (`core/onchain.get_wallet_onchain_balances`, a plain `balanceOf` + `eth_getBalance`
  read, no signing). Surfaced on Admin Overview's "Platform Wallets" section, polling every 20s while the
  tab is visible (paused via `document.visibilityState` otherwise). Watch the Repurchase Reserve wallet's
  BNB specifically — it's the only one of the three that ever broadcasts its own tx (the auto-repurchase
  settlement above) and thus the only one that needs gas; the other two are receive-only.

## Removed (do not reintroduce without asking)

- NOWPayments deposit-first rail: `/deposit`, user-to-user `/deposit/transfer`, `/wallet/withdraw`, account-balance `/agents/purchase`.
- Celery/Redis + `app/workers/`. Admin treasury *Generate* / mint feature.
- Automatic (unattended) member-payout sweep (`app/core/member_payout.py`, `PLATFORM_FEE_SIGNER_PRIVATE_KEY`, `MULTISENDER_ADDRESS` backend config) — never wired to a funded key, so it never actually ran. The admin-triggered `payout/create`/`payout/status` pair is the only member-payout rail now.
- Legacy tables (`deposits`, `withdrawal_requests`, `webhook_events`, `transfer_verifications`) left in DB, no longer read.
- Standalone user `/wallet` page (`pages/Wallet.jsx`) — balances/reserve + transaction history were redundant with Dashboard + Transactions; nav entry, route, and file all removed.
- User Dashboard's "Quick Actions" card and Admin Overview's "Recent Transactions" / "Transaction Breakdown"
  sections — low-value once dedicated Transactions pages (with Status filtering) covered the same ground.

## Workflow

```bash
# Backend
conda activate luxus && cd backend && uvicorn app.main:app --reload   # :8000, /docs
# Frontend
cd frontend && npm run dev                                            # :3000
# Fresh DB: python create_tables.py && python seed_admin.py
# Existing DB migrations: migrate_v14/v15/v17/v18/v19/v20/v21/v22.py; backfill_repurchase_reserve.py
```

- **Touch only what you must** — this is a financial system; keep changes scoped.
- Restart Vite after editing any `VITE_*` env. `VITE_USDT_ADDRESS` MUST match backend `USDT_CONTRACT` (else balance card shows $0).
- `LOG_LEVEL=DEBUG` to trace (request middleware logs method/path/status/duration), then revert to INFO.
- **Platform freeze** (admin kill switch) is a full stop on money movement, HTTP 423 while frozen: `pack/purchase` + `pack/status` (buyer-facing settlement — admins bypass, via `require_platform_active`) and `payout/create` / `payout/status` / `admin/transfer` / `admin/wallet/credit` / `admin/wallet/debit` (admin-triggered — **no** bypass, via `ensure_platform_active`, since these move money regardless of who calls them). See `app/core/platform_state.py`.
- **Per-user freeze** (`User.is_active=False`) blocks login (clear 403, not a generic error) and everything downstream of `get_current_user`; Core, sponsor-share, and Stream/Boost matrix payouts to a frozen user are retained as platform profit instead of credited. Admins can't be frozen or deleted (guards in `admin.py`). `DELETE /admin/users/{id}` is a hard delete — re-parents the downline, preserves realized profit (SOFTWARE_FEE/PLATFORM_PROFIT rows re-attributed to the admin; any unconsumed REPURCHASE reserve is booked as a new PLATFORM_PROFIT row too, per spec — it must not just vanish with the deleted Wallet rows), and cleans up matrix/pack-purchase rows so it doesn't fail on FK constraints.
