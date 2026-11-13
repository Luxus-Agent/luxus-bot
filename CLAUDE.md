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
  components/Logo.jsx    # brand mark (assets/logo.png) + theme-aware wordmark (assets/logo-text-dark/light.png)
  utils/agentTiers.js    # tier -> display name (Trial/Start/Build/Growth) — display only, backend pack_name unchanged
  components/EarningsBreakdown.jsx # shared Completed/Pending/Fee breakdown rows — user Dashboard "Total Earnings"
                          # card + Transactions "Total In" tile (both click-to-expand); always foots to the total
  pages/RevenueEngine.jsx # user: self-scoped Core preview + downline odd/even table (no Stream/Boost — platform-wide)
  pages/ + pages/admin/   # user + admin dashboards (admin: AdminRevenueEngines.jsx — Core/Stream/Boost viz)
                          # NOTE: no standalone Wallet page — balances/history live in Dashboard + Transactions
  pages/Profile.jsx      # Change Password card reuses the forgot-password/reset-password OTP endpoints
                          # (own email pre-filled) rather than a current-password endpoint; logs out after reset
  pages/Login.jsx, Register.jsx, ForgotPassword.jsx, VerifyEmail.jsx # share one auth-page look: full-bleed
                          # background + overlay behind a `bg-panel` card, Logo inside the card (not above
                          # it) — use the `auth-screen` / `auth-overlay` classes (index.css), never an inline
                          # image: dark = assets/login-bg.png + dark gradient, light = assets/light-bg.jpg
                          # (auth pages ONLY — logged-in screens use solid --bg-page in both themes).
                          # Light theme's accent is the same green as dark.
backend/app/
  api/auth.py            # register/verify-email/login/reset, usernames case-insensitive; forgot-password 404s an unregistered email (deliberate disclosure)
  api/wallet.py          # balances / transactions (+ tx_hash) / earnings (+ Completed/Pending split) / repurchase / BEP-20 address / core-preview
  api/agents.py          # GET /agents/purchases (read-only ownership)
  api/admin.py           # users, freeze/unfreeze, treasury transfer, platform freeze, manual credit, matrix/core viz, live on-chain wallet balances
  api/distribution.py    # wallet-map + on-chain pack rail (/pack/purchase, /pack/status)
  core/onchain.py        # on-chain settlement: auto-repurchase + Stream/Boost instant matrix payouts + read-only USDT/BNB lookups
  core/pack_payout.py    # Core 60% split (compression + odd/even); also Stream/Boost/admin rates
  core/proactive.py      # Core eligibility/compression helpers
  core/core_preview.py   # read-only Core routing simulator (upline) + downline odd/even table, shared admin + user
  core/matrix_engine.py + matrix_runtime.py  # Stream + Boost 3x3 matrices (LIVE)
  core/matrix_flow.py    # read-only queue-flow reconstruction (position stack + re-entry spawn pairing) for admin viz
  core/repurchase.py     # auto-repurchase sweep (LIVE)
  core/wallet_ops.py     # credit_wallet (70/20/10 fallback), credit_main_wallet_direct (100% fallback), mirror_onchain_earning_split, resolve_payout_address, tx_hash resolver
  core/user_lookup.py    # case-insensitive username lookup/equality — use for ALL username matching, never User.username ==
  services/email_service.py # OTP emails (verify/resend/reset/address). Every template renders through
                          # `_card()`, which embeds the Luxus logo as inline CID images (not a hosted URL —
                          # works even when a client blocks remote images) from `app/assets/email/` — a
                          # backend-local copy of `frontend/src/assets/logo.png` + `logo-text-light.png`.
                          # Update both copies together if the logo changes.
  models/                # user, agent, wallet, wallet_address, transaction, pack_purchase, matrix, platform_setting
```

## Revenue Model (LIVE — runs on the on-chain rail)

Every pack purchase applies a **60 / 30 / 10 split** (executed inside `POST /distribution/pack/status` on success):

- **Core 60%** → two 30% halves, each resolved by **one continuous walk** up the sponsor chain
  (`_walk_core_half` in `pack_payout.py`, mirrored peek-only by `_walk_core_half_peek` in
  `core_preview.py`) combining compression + odd/even in a single pass — replaced an earlier
  two-independent-slots design that could double-pay one recipient both halves (see
  `pack_payout.py`'s docstring for the before/after). Per half: skip ineligible uplines (highest
  active tier < buyer's, inactive/frozen — **Admin exempt from tier ownership**, `_is_eligible` in
  `proactive.py`, since `seed_admin.py` gives admin no `AgentPurchase`) *and* even-turn ones
  (`User.core_route_count_tierN` still advances) until an odd turn keeps it, or the chain runs out
  (last eligible seen keeps it). **Second half's walk starts one level above wherever the first
  half actually landed** — not back at the direct sponsor or the first half's pre-parity candidate.
  No one found there → the sole eligible upline absorbs both halves via its own fresh targeting.
  Counter only advances on `pack/status` **success**, never at `pack/purchase` order-creation.
  No eligible upline at all / no valid BEP-20 address → folds into platform fee.
- **Stream 30%** → per-tier 3×3 matrix. Re-entries are **dummy** (no payout). 10% sponsor share at L2/L3. **A purchase only places the buyer in L1** — they **graduate** into L2/L3 only once their own position has ALSO granted all of that level's re-entry milestones (client-confirmed correction, 2026-08-06; previously all 3 levels filled at once) — see `matrix_engine.place_graduation` / README's Matrix System section. **Re-entries are progressive, not a lump sum** — a head's `reentry_count` re-entries are granted ONE AT A TIME, during its own cycle, every `threshold/reentry_count` (always 3) total slot-fills since it became head (a released re-entry itself counts toward the next milestone, so only the 1st needs 3 fresh real joins — later ones need 2); the FINAL milestone always coincides with the head's own completion (client-confirmed correction, 2026-08-06: "d1,d2,d3 → re-entry, d4,d5 → re-entry, d6,d7 → re-entry, then dhanush graduates") — see `MatrixLevelQueue.reentries_released_this_cycle` / `_append_to_level`'s "re-entry milestone" section.
- **Boost 10%** = **9% matrix + 1% admin income**. **Single shared queue for placement** (`agent_tier` pinned to 1 in `matrix_runtime.BOOST_TIER`), but **each real join's own credit scales by that joiner's own purchased tier** (`contribution_tier` in `matrix_engine._append_to_level`, distinct from the queue's fixed tier — fixed 2026-08-06, previously flat $0.30/$0.60/$1.50/$3.60 regardless of tier); same L1-only-then-graduate placement as Stream. Re-entries are **real**. Level-completion sponsor share/residual now derive from `MatrixLevelQueue.cycle_gross_accumulated`/`cycle_wallet_paid` (actual $ this cycle, since joins can mix tiers) rather than a fixed formula — see that column's docstring. ⚠️ **Unconfirmed with client:** no check for new-joiner == current head, so a member can pay themselves via their own next purchase (or own auto-repurchase — same gap hits Stream too) — flagged 2026-08-05, pending decision (see README's Boost Agent section).
- **Wallet rule — Core/Stream 70/20/10, Boost 90/10 (own payout) or 100% (sponsor share):** every Stream matrix payout and Core commission splits 70% main / 20% repurchase reserve / 10% software fee (`credit_wallet`; Core via `mirror_onchain_earning_split`). **Boost's own position-holder payout** takes only the 10% software fee, no reserve — 90% main (`credit_boost_wallet`, fixed 2026-08-06; previously 100% no-split). **Boost-sourced sponsor share** is unaffected — still credits **100%** straight to MAIN (`credit_main_wallet_direct`), paid in addition, never fee-reduced.
  Stream/Boost payouts are **per-joiner incremental** (credited the instant each contributing member joins, not a lump sum at level completion — see `matrix_engine.py`). Income `Transaction` rows always record the **full gross commission**.
  Aggregates estimating "money credited to wallets" (`/admin/metrics`, `GET /wallet/earnings`) apply 70% to Stream/Core, **90% to Boost's own payout, 100% to Boost's sponsor share** — sponsor share follows its source system (`reference_id`-tagged, since it has no source column).
- **Stream/Boost payouts (+ sponsor share) settle instantly on-chain** the same instant they're decided (`matrix_runtime._settle_or_credit`, mirroring how Core already works) — Stream broadcasts only its **70%** share straight to the recipient's own wallet (20%/10% still booked internally via `mirror_onchain_earning_split`); Boost broadcasts **90%** of its own payout (10% fee stays internal via `mirror_onchain_boost_split`) or the **full 100%** of a sponsor-share bonus. Falls back to the internal-only crediting above whenever settlement isn't possible: `PLATFORM_FEE_SIGNER_PRIVATE_KEY` unset (disabled, today's default), no wallet address on file, or the broadcast fails (best-effort, never raises — `core/onchain.py`). The settled row's `Transaction.tx_hash` is the signal Completed/Pending now keys off of for these types — see Earnings Transparency below.
- **Auto-repurchase:** when a tier's reserve hits **threshold = price + platform fee** ($11 / $22 / $55 / $111), the platform auto re-buys that same tier, unbounded — re-runs Core + matrices (compounding). The flat fee → platform profit. Reserve is fed by Core + Stream only (Boost's own payout takes the 10% fee but still has no repurchase reserve cut — see Wallet rule above). Frozen/inactive reserves are held. See `core/repurchase.py`.

> Payout schedules per tier/level are in @README.md (Revenue Mechanics).

## Earnings Transparency — Completed vs Pending

`GET /wallet/earnings` returns `total_earned` (unchanged gross ledger sum) plus a
breakdown: **`completed`** (Core's 70% on-chain share + any Stream/Boost/sponsor row
that **settled on-chain**, `Transaction.tx_hash IS NOT NULL`) + **`pending_reserve`**
(live REPURCHASE wallet sum, all tiers — building toward the next auto-repurchase) +
**`pending_payout`** (live MAIN wallet sum — only *unsettled* Stream/Boost/sponsor
share, internal-only until an admin payout run pays it out). These three **always
foot exactly to `total_earned`**; the frontend derives a 4th "platform software fee"
line as the remainder so nothing is ever silently unaccounted for. Shared UI:
`components/EarningsBreakdown.jsx`, used by the user Dashboard's "Total Earnings"
card, the Transactions "Total In" tile, and mirrored as a Completed/Pending Status
column + filter on both `Transactions.jsx` and `AdminTransactions.jsx` —
`repurchase_hold` is always Pending; `stream_payout`/`boost_payout`/
`sponsor_milestone_income` are Pending **only when their own `tx_hash` is falsy**
(per-row now, not a flat type list — `isPendingTx` in both files, keep in sync);
`core_income` stays always Completed.

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
- **User** `/revenue-engine`: same Core simulator + downline odd/even table, both **self-scoped only**
  (`GET /wallet/core-preview` / `GET /wallet/core-downline`, no username param) — no Stream/Boost tab (those
  queues are platform-wide, not per-user). No static explainer diagram on either page — `CoreExplainerDiagram` was removed as dead code once nothing rendered it.
- Core simulator/downline endpoints only **peek** at the per-tier `core_route_count_tierN` (never persist) — safe to
  run repeatedly. If the target already **owns** the previewed tier, returns the **actual recorded result** from
  that settled purchase instead (diverges further from history otherwise). Shared logic: `core/core_preview.py`;
  shared UI: `frontend/src/components/CoreRoutingViz.jsx` (`CorePreviewTable` for the simulator, `DownlineColumn`
  for the odd/even table — both used by admin's any-username version and the user's self-scoped version).
- The actual-result path also surfaces recipients whose Core half was decided by routing but never actually
  paid because they had no wallet address on file (folded into `platform_fee` at settlement — see
  `core_unpaid` below) — named by username instead of silently vanishing into "platform profit" with no
  identity, e.g. `@dhanush ($3) + @admin ($3)` rather than omitting admin or showing a generic fallback.

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

- `POST /distribution/pack/purchase` (JWT, `require_platform_active`) → returns recipient split (sums to price). Roles: `buyer`, `upline` (70% + `gross_amount`), `repurchase_reserve`, `software_fee`, `admin`, `platform_fee` (the latter also carries the Stream 30% + Boost-pool 9% shares — tracked internally, no separate on-chain wallet), `core_unpaid` (reporting-only — a Core half whose decided recipient had no wallet address; `amount: 0`, `has_wallet_address: false`, so it's inert on every on-chain/ledger path; the real dollars are already inside `platform_fee`. Exists purely so `core-preview`'s actual-result view can name the intended recipient instead of showing nothing).
- `POST /distribution/pack/status` → records success(tx_hash)/failed; on success runs ownership + ledger + matrices + repurchase (idempotent, PENDING-guarded).
  Both Transactions pages (user + admin) show a **Tx Hash** column — prefers the row's own `Transaction.tx_hash`
  (set when a Stream/Boost/sponsor payout settled instantly on-chain, see below) and falls back to
  `wallet_ops.resolve_tx_hashes` (joining `Transaction.reference_id` → `PackPurchase.order_id` / `PayoutBatch.batch_id`)
  for Core / member-payout rows; anything still fully internal-only shows `—`.
- `GET /distribution/wallet-map` → read-only user+downline wallet/profit map for MultiSender. Distribute against `profit.withdrawable`.
- Wallet config (`.env`): `PLATFORM_FEE_WALLET`, `ADMIN_INCOME_WALLET` / `REPURCHASE_RESERVE_WALLET` (each falls back to `PLATFORM_FEE_WALLET`). **Set distinct addresses before go-live**, and fund `REPURCHASE_RESERVE_WALLET` with BNB directly — it pays its own gas for its automated send (no separate gas wallet). `PLATFORM_FEE_WALLET` receives every purchase's Stream/Boost share on-chain, and — once `PLATFORM_FEE_SIGNER_PRIVATE_KEY` is set — also **sends** from it (instant Stream/Boost payout settlement below); fund it with its own BNB for gas too in that case.
- `POST /distribution/payout/create` + `/payout/status` (admin-only) — runs the same MultiSender contract in reverse (platform wallet -> every member with a positive withdrawable balance) to actually pay out accumulated internal earnings. Mirrors `pack/purchase`/`pack/status`'s PENDING-guarded lifecycle; on success debits each recipient via `debit_withdrawable` so the money isn't offered again. This is the only member-payout rail — no automatic/unattended sweep. Now drains a smaller pool than before: only Stream/Boost payouts that stayed internal (settlement disabled/failed/no address) ever land here.
- Both on-chain settlements are unattended by design (no admin approval step), best-effort (any broadcast failure logged/swallowed, never blocks a purchase), and use `BSC_RPC_URL`: auto-repurchase (`app/core/onchain.py`) via `REPURCHASE_SIGNER_PRIVATE_KEY`, and Stream/Boost matrix payouts + sponsor share (`matrix_runtime._settle_or_credit`) via `PLATFORM_FEE_SIGNER_PRIVATE_KEY`. **Live private keys, treat like `SECRET_KEY`, never commit** — empty key keeps either feature internal-ledger-only, today's default.
- `GET /admin/treasury/onchain-wallets` (admin-only, read-only) — live USDT + native BNB balance for all
  three platform wallets (`core/onchain.get_wallet_onchain_balances`, a plain `balanceOf` + `eth_getBalance`
  read, no signing). Surfaced on Admin Overview's "Platform Wallets" section, polling every 20s while the
  tab is visible (paused via `document.visibilityState` otherwise). Watch **Repurchase Reserve** and
  **Platform Fee** wallets' BNB — both can broadcast their own tx (auto-repurchase / instant Stream-Boost
  settlement, each behind its own signer key above) and need gas; Admin Income stays receive-only. Frontend
  low-gas warning (`AdminDashboard.jsx`'s `NEEDS_GAS_KEYS`) covers both — keep in sync if a third gets a signer.

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
# Schema: create_tables.py builds the full current schema — the old migrate_v*.py upgrade scripts were
# removed (still in git history, last present at commit aed229d). One-off data repair: backfill_*.py
```

- **Touch only what you must** — this is a financial system; keep changes scoped.
- Restart Vite after editing any `VITE_*` env. `VITE_USDT_ADDRESS` MUST match backend `USDT_CONTRACT` (else balance card shows $0).
- `LOG_LEVEL=DEBUG` to trace (request middleware logs method/path/status/duration), then revert to INFO.
- **Platform freeze** (admin kill switch) is a full stop on money movement, HTTP 423 while frozen: `pack/purchase` + `pack/status` (buyer-facing settlement — admins bypass, via `require_platform_active`) and `payout/create` / `payout/status` / `admin/transfer` / `admin/wallet/credit` / `admin/wallet/debit` (admin-triggered — **no** bypass, via `ensure_platform_active`, since these move money regardless of who calls them). See `app/core/platform_state.py`.
- **Per-user freeze** (`User.is_active=False`) blocks login (clear 403, not a generic error) and everything downstream of `get_current_user`; Core, sponsor-share, and Stream/Boost matrix payouts to a frozen user are retained as platform profit instead of credited. Admins can't be frozen or deleted (guards in `admin.py`). `DELETE /admin/users/{id}` is a hard delete — re-parents the downline, preserves realized profit (SOFTWARE_FEE/PLATFORM_PROFIT rows re-attributed to the admin; any unconsumed REPURCHASE reserve is booked as a new PLATFORM_PROFIT row too, per spec — it must not just vanish with the deleted Wallet rows), and cleans up matrix/pack-purchase rows so it doesn't fail on FK constraints.
