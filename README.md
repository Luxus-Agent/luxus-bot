# Luxus — Agent Revenue Sharing Platform

A multi-tier passive income platform where users buy AI Agent tiers **on-chain** (USDT BEP-20) and earn through three parallel revenue engines: **Core Agent**, **Stream Agent**, and **Boost Agent**.

---

## Table of Contents

- [Key Features](#key-features)
- [Architecture](#architecture)
- [Revenue Mechanics](#revenue-mechanics)
- [Earnings Transparency — Completed vs Pending](#earnings-transparency--completed-vs-pending)
- [User Journey](#user-journey)
- [Auth Flow](#auth-flow)
- [Deposit & Purchase Flow](#deposit--purchase-flow)
- [Matrix System](#matrix-system)
- [Revenue Engine Visualization](#revenue-engine-visualization-admin--user)
- [Withdrawal Flow](#withdrawal-flow)
- [TokenPocket Distribution Endpoint](#tokenpocket-distribution-endpoint)
- [On-Chain Pack Purchase](#on-chain-pack-purchase)
- [Member Payout](#member-payout-admin-distribution)
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
- 🌳 **Username-based sponsor tree** — every user registers under a sponsor; live sponsor-existence + wallet-address validation on the register form. Usernames are case-insensitive (passwords stay case-sensitive).
- 🧮 **70 / 20 / 10 wallet rule** — every commission splits into main wallet / repurchase reserve / software fee. Ledger income figures ("Total Earnings") always report the full gross commission, before that split.
- 🛡️ **Admin controls** — per-user freeze/delete, treasury transfer, and a global platform-freeze kill switch that blocks all money movement (purchases, settlement, matrix/repurchase payouts, admin payouts and treasury) with HTTP 423 while frozen.
- 📊 **Real-time earnings & distribution map** — ledger-sourced totals plus a read-only `wallet-map` endpoint that feeds the MultiSender payout. Transaction history (user + admin) links on-chain rows to a BscScan tx hash.
- 🔍 **Revenue engine visualization** — admin sees Core compression/odd-even routing (any user), a sponsor's direct-downline odd/even table, and a full Stream/Boost queue-flow diagram (every position + re-entry spawn links); users get a self-scoped Core routing preview. All read-only. See [Revenue Engine Visualization](#revenue-engine-visualization-admin--user).
- ✅ **Completed vs Pending earnings breakdown** — a click-to-expand card on the Dashboard and Transactions
  pages splits "Total Earnings" into what's already on-chain, what's still building toward the next
  auto-repurchase, and what's awaiting the next admin payout — always reconciling exactly to the headline
  total. See [Earnings Transparency](#earnings-transparency--completed-vs-pending).
- 💰 **Live on-chain platform wallet monitor** — admin sees real-time USDT + BNB gas balances for all three
  platform-controlled wallets (Platform Fee, Admin Income, Repurchase Reserve), auto-refreshing, with a
  low-gas warning on the Repurchase Reserve wallet (the only one that pays its own gas).
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

| Tier    | Display name | Base | Platform fee | Total cost | Core Agent | Stream Agent | Boost Agent |
|---------|-------|------|--------------|-----------|-----------|-------------|------------|
| Agent 1 | Trial  | $10  | $1   | **$11**  | $6.00     | $20.00      | $5.70      |
| Agent 2 | Start  | $20  | $2   | **$22**  | $12.00    | $40.00      | $5.70      |
| Agent 3 | Build  | $50  | $5   | **$55**  | $30.00    | $100.00     | $5.70      |
| Agent 4 | Growth | $100 | $11  | **$111** | $60.00    | $200.00     | $5.70      |

> The buyer pays **Total cost = Base + Platform fee**; the flat platform fee goes straight to the platform profit wallet and is **not** part of the 60/30/10 split (which runs off the **Base**). Applies to repurchase too.
>
> Boost runs a **single global queue** (always tier 1), so its payout does not scale with the purchased tier — the full Boost cycle is $0.60 + $1.50 + $3.60 = **$5.70** wallet for every tier.
>
> **"Agent 1"–"Agent 4"** is the internal identifier — the backend `pack_name`/tier number, unchanged in the
> API and database. **Trial/Start/Build/Growth** are display-only names shown to users everywhere a tier
> appears in the UI (`frontend/src/utils/agentTiers.js`) — nothing else about the tier changed.

---

### 60% — Core Agent (Upline Routing with Compression)

The 60% is split into two equal halves (30% each), each resolved by **one continuous walk**
up the sponsor chain that combines compression and odd/even into a single pass — compression
decides who's even a valid stop, odd/even decides whether that stop keeps the money or the walk
keeps climbing past them.

**The walk, for one half, starting from a given point in the sponsor chain:**
- At each upline going up: if they're **ineligible** (compression — see below), skip them and
  continue to the next upline. No counter change.
- If they're **eligible**, advance their per-tier targeting counter
  (`User.core_route_count_tierN` — see Odd/Even below):
  - **Odd** → they keep the amount. The walk stops here.
  - **Even** → the amount keeps climbing; continue the walk from the next upline above them.
- If the chain runs out before anyone hits odd (nobody left above), the **last eligible upline
  seen** keeps it regardless of parity — "no eligible upline for an even pass-up → recipient
  keeps it."

**First 30%** → the walk starts at the buyer's direct sponsor.
**Second 30%** → the SAME walk, run again, but starting **one level above wherever the first
half's walk actually landed** — not back at the direct sponsor, and not at the first half's
original candidate if that candidate's own turn was even and the money passed further up. If
that second walk finds no one at all, the sole eligible upline absorbs the second half too, via
its own fresh, independent odd/even targeting, rather than forfeiting it to platform profit.
A half only folds into **platform profit** when the first half's walk finds no eligible upline
at all — the buyer has no sponsor, or the entire chain above them is ineligible/frozen (in which
case there's by definition no one for the second half to reach either).

> ⚠️ This replaced an earlier design that picked both halves' target *people* via compression
> alone (first eligible upline, then the next eligible upline **above that original candidate**)
> and only *then* applied odd/even to each independently. That could let one recipient absorb
> both halves purely by coincidence of chain adjacency — e.g. if upline A's turn was even and
> passed up to upline B, and B (compression's independently-computed "second" pick) also
> happened to land on an odd turn, B kept both halves instead of the money reaching whoever was
> above B. The single continuous walk above fixes this: each half's walk only ever stops once,
> at the first odd hit, so a half genuinely can't be "won twice" by the same recipient.

**Compression (tier-qualified eligibility):**
- An upline only **qualifies** for Core income if their own **highest active
  purchased tier ≥ the tier the buyer just purchased**.
- Uplines who bought a lower tier (or own no active agent, or are frozen) are
  **skipped** — the income compresses *past* them up the chain to the next
  eligible upline.
- **Exception: Admin is exempt from the tier-ownership requirement** (still must
  be active). `seed_admin.py` never gives the admin account an `AgentPurchase`,
  so without this exemption admin — the root of every sponsor chain — could
  never actually qualify to receive Core income.

> Example (`Admin $100 → A $100 → B $10 → C $10 → D $20 → E $100`): when **E buys
> $100** (tier 4), uplines **D ($20), C ($10), B ($10) are all skipped** because
> none bought the $100 tier; income lands on **A ($100)** and **Admin ($100)**.

**Odd/Even** (tracked by `User.core_route_count_tierN`, one independent counter per agent tier —
a tier-1 ($11) targeting and a tier-2 ($22) targeting of the same recipient alternate separately,
never sharing parity):
- Each recipient has a per-tier targeting counter, incremented **every time they are
  targeted by a purchase of that tier** — whether they keep the amount or the walk passes them by.
- The counter only advances for real on `pack/status` **success** — `pack/purchase` (order creation) only
  *peeks* the same decision to build the recipient list the buyer's wallet pays on-chain. This matters
  because a failed/abandoned on-chain attempt (wallet rejection, insufficient gas, user cancels) would
  otherwise permanently skew a real recipient's alternation even though no money ever moved.

> The counter increments on every targeting (not only on kept credits) so the alternation never gets stuck on "even" after a recipient's first pass-up. Compression applies to the Core Agent **only** — Stream and Boost matrices are unaffected.

Implemented in `pack_payout.py` via `_walk_core_half` (compression via `proactive.py`'s
`_highest_active_tier` / `_is_eligible`); the read-only preview (`core_preview.py`'s
`_walk_core_half_peek`) mirrors the exact same walk without persisting anything.

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

> **Ledger vs wallet amount:** the headline income `Transaction` row (`core_income` / `stream_payout` /
> `boost_payout` / `sponsor_milestone_income`) always records the **full gross commission**, not the 70%
> that actually lands in the MAIN wallet — the accompanying `software_fee` / `repurchase_hold` rows (same
> `reference_id`) document where the other 30% went. This is deliberate: "Total Earnings" and the admin
> revenue-engine totals must show the amount **before** the platform fee is subtracted, per client spec.

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
- **On-chain settlement** (`app/core/onchain.py`): once `REPURCHASE_SIGNER_PRIVATE_KEY` is set, each repurchase also broadcasts a real ERC20 `transfer` moving the consumed reserve (price + fee) from the reserve wallet to `PLATFORM_FEE_WALLET`, over `BSC_RPC_URL` — best-effort (any failure is logged and swallowed; the internal accounting above always applies regardless, so a broadcast failure never blocks a purchase). Leave the key unset to keep auto-repurchase internal-ledger-only, unchanged from before. This settles the reserve on-chain but does **not** replay the Core/Stream/Boost recipient split — those stay internal, paid out later via the member-payout rail below.
- **Migration:** existing DBs run `cd backend && python migrate_v17.py` once (adds `repurchase_buy` / `repurchase_gas` / `admin_credit` + the matrix pool types to the Postgres `transactiontype` enum); `create_tables.py` covers fresh installs.

---

## Earnings Transparency — Completed vs Pending

"Total Earnings" is a **gross ledger total** (Core + Stream + Boost + Sponsor commissions, before the
70/20/10 split — see [Wallet Credit Split](#wallet-credit-split) above). That number alone doesn't tell a
user or admin **where** the money actually is, which was the source of a real support ticket: a user compared
their on-chain wallet balance to "Total Earnings" and found roughly $100 missing out of $148 — not a bug,
just an unexplained gap. The fix is a breakdown, not a different total:

`GET /wallet/earnings` now returns, alongside the existing `total_earned`:

| Field | What it is | Why it's not in the wallet yet |
|---|---|---|
| `completed` | Core's 70% share | Already paid **directly on-chain**, buyer → upline, at purchase time (`mirror_onchain_earning_split`). It's real money in the recipient's own wallet the instant the purchase settles. |
| `pending_reserve` | Live sum of all `REPURCHASE` wallet balances | Building toward the next auto-repurchase threshold — reinvested into another tier automatically, never paid out as cash. |
| `pending_payout` | Live sum of all `MAIN` wallet balances | Stream/Boost/Sponsor's 70% share, credited internally via `credit_wallet` — stays internal-ledger-only until an admin runs a [member payout](#member-payout-admin-distribution) batch. |

These three **always foot exactly to `total_earned`** — the UI derives a fourth, muted "platform software fee"
line as the remainder (`total_earned − completed − pending_reserve − pending_payout`), so nothing is ever
silently unaccounted for, regardless of how a given account's history looks.

**Where it shows up:**
- User Dashboard's "Total Earnings" stat card — click to expand the breakdown.
- Transactions page's "Total In" tile — same click-to-expand breakdown.
- Both Transactions pages (user `/transactions` and admin `/admin/transactions`) also get a per-row
  **Status** column (`Completed` / `Pending`) and matching filter — `core_income` rows are always
  `Completed`; `repurchase_hold`, `stream_payout`, `boost_payout`, and `sponsor_milestone_income` rows are
  `Pending`.
- Shared component: `frontend/src/components/EarningsBreakdown.jsx` — used by both pages so the math can't
  drift apart between them.

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

**Usernames are case-insensitive; passwords are case-sensitive.** Login, registration's duplicate/sponsor checks,
`check-username`, and every other username lookup (admin transfer/search, wallet-map, core-simulate) go through
`app/core/user_lookup.get_user_by_username` (`func.lower()` comparison) — `"Alice"`, `"alice"`, and `"ALICE"` all
resolve to the same account. The stored username casing is untouched (whatever the user typed at registration is
still what's displayed). Passwords are unaffected — bcrypt hashes the exact string, so they remain case-sensitive.

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

Both Stream and Boost run as **three independent per-level FIFO queues** — one queue each for L1, L2, and L3 — not a single branching tree. Position 1 (the head of a level's queue) is paid once `threshold` **brand-new** members have joined that same level's queue behind them (L1: 3, L2: 9, L3: 27), then pops out and the next member in line becomes head:

```
L1 queue (threshold 3):  [you, A, B, C, D, E, ...]
  you paid once A,B,C join (join #4 overall) → popped
  A paid once D,E,F join (join #7 overall)   → popped
  ...

L2 queue (threshold 9):  same pattern, 9 fresh joiners per payout
L3 queue (threshold 27): same pattern, 27 fresh joiners per payout
```

A real purchase adds **one entry to all three of its tier's level-queues at once** (a member's downline growth counts toward L1, L2, and L3 simultaneously — the "3 x 3" of the spec). The re-entries a level-completion grants feed back **only into that same level's own queue** — never into the other two. That separation is what keeps the system bounded: each level's own re-entries are a contracting 1-in-3 series (Stream/Boost's `L1/L2/L3 ReBirth` counts are exactly 1/3/9 against thresholds 3/9/27) when they can't cross-feed into the other levels. `app/core/matrix_engine.py` implements this (`MatrixLevelQueue` + `MatrixQueueSlot`); `app/core/matrix_runtime.py` drives it per purchase, via a durable `MatrixPendingPayout` backlog so a busy queue never makes a single purchase request hang — any backlog left over after a bounded per-call budget is picked up by the next purchase automatically.

Concurrency is protected via PostgreSQL `SELECT FOR UPDATE` on `MatrixLevelQueue` and `MatrixQueueSlot` rows, preventing race conditions under parallel activations.

---

## Revenue Engine Visualization (Admin & User)

Read-only dashboards that make the Core/Stream/Boost rules above inspectable instead of purely
theoretical — none of the endpoints below mutate any persisted state.

**Admin** — `/admin/revenue-engines` (nav: **Revenue Engines**):

```
GET /admin/matrix/overview              → fill-state snapshot of every Stream (tier 1-4) and
                                           Boost (global, tier 1) level-queue: percent-to-next-
                                           payout, wallet/re-entry amounts, lifetime completions
GET /admin/matrix/queue-slots           → ordered queue contents for one (system, tier, level)
  ?system_type=stream|boost&tier=&level=  starting from the current head position — who's
                                           occupying each position, which are re-entries
GET /admin/matrix/queue-flow            → the FULL queue from position #1 onward, in true
  ?system_type=stream|boost&tier=&level=  arrival order, with each paying position linked to
                                           the re-entry slot(s) it spawned (`spawned_from`) —
                                           the single-stack-with-connectors "Flow View" diagram
GET /admin/core/simulate                → preview of the Core 60% compression + odd/even split
  ?username=&tier=                        if `username` bought `tier` right now — for ANY user
GET /admin/core/downline                 → a sponsor's DIRECT downline split into a left/odd
  ?username=                              and right/even column by join order (1st/3rd/5th
                                           referral left, 2nd/4th right) — the odd/even table
```

**User** — `/revenue-engine` (nav: **Revenue Engine**) — Core only; Stream/Boost are platform-
wide queues, not something an individual routes, so they're omitted here:

```
GET /wallet/core-preview?tier=          → same Core simulation as the admin version, scoped to
                                           the logged-in user only (no username param)
```

The Core simulator **peeks** at the recipient's per-tier `User.core_route_count_tierN`
(`+1`, never persisted) to resolve odd/even the same way
`app/core/pack_payout.compute_pack_split` does at a real purchase, and
additionally reports each hop's compression-skipped uplines (frozen / tier-too-low) for display.
Shared simulation logic lives in `app/core/core_preview.py` (used by both the admin and user
endpoints, so admin's arbitrary-username capability and the user's self-only capability never
drift apart); the shared Core explainer diagram + routing-chain UI lives in
`frontend/src/components/CoreRoutingViz.jsx`.

If the target already **owns** the tier being previewed, the simulator instead returns the
**actual recorded result** from that settled purchase (pulled from the real
`PackPurchase.recipients_json`) rather than a hypothetical peek — a peek of an already-owned tier
would otherwise answer "what if this purchase happened again right now," which diverges further
from what actually happened every time anyone else's purchase advances the same recipients'
counters. That actual-result list also includes any recipient the routing decided on but who was
never actually paid because they had no wallet address on file (`role: "core_unpaid"` in
`recipients_json`, folded into `platform_fee` at settlement — see
[On-Chain Pack Purchase](#on-chain-pack-purchase)) — named by username rather than silently
disappearing into "platform profit." The frontend (`CorePreviewTable` in
`frontend/src/components/CoreRoutingViz.jsx`) renders both the hypothetical and the actual-result
case as the same plain two-column table — `Purchase | Recipients (both halves)` — e.g.
`@dhanush1 buys Agent1 → @dhanush ($3) + @admin ($3)`, merging same-recipient halves into one
`both → @admin ($6, merged)` row, and showing `No eligible upline — retained as platform profit`
only when genuinely nobody (paid or unpaid) was eligible.

The Core **downline odd/even table** (`get_downline_odd_even` in `core/core_preview.py`) is a
different axis from the simulator above: instead of walking UP the sponsor chain to see who
*receives* a purchase's commission, it lists a sponsor's own DIRECT downline (who they personally
referred), ordered by `User.sponsor_position` (falling back to a live-recomputed rank so members
re-parented after an admin deletion still land in a column) and split alternately into a left/odd
and right/even column by join order — admin-only, at `/admin/revenue-engines`'s Core tab.

The **queue-flow diagram** (`core/matrix_flow.py`, admin-only "Flow View" per level card) renders
Stream/Boost's `MatrixQueueSlot` rows as one connected stack instead of the summary level cards —
every position from #1 onward, real joins and re-entries in true arrival order. The spawn pairing
(which re-entry a given position generated) isn't stored directly; it's reconstructed from
`MatrixQueueSlot.is_reentry` + `matrix_runtime.drain_matrix_backlog`'s strict oldest-first
processing order, which guarantees the *k*-th paid position's re-entries are always exactly the
*k*-th contiguous block of `reentry_count` re-entry slots in position order — see that module's
docstring for the full argument. `MatrixQueueSlot.is_reentry` (migration `migrate_v22.py`) exists
because Stream re-entries are already distinguishable via `is_dummy`, but Boost re-entries are
**real** (`is_dummy` stays `False` per spec), so there was previously no signal telling a Boost
re-entry apart from a brand-new member — pre-migration Boost rows can't be backfilled retroactively
and simply won't show the re-entry badge/link in the diagram.

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
Stream 30% + Boost 9% → the platform fee wallet (tracked internally per tier by the matrix engines,
not held in their own on-chain wallet), and 1% → the admin income wallet. Each upline's Core
commission is paid out on-chain under the **70 / 20 / 10
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
(eligible = active **and** highest active tier ≥ buyer's tier; compression + odd/even), Stream 30% +
Boost 9% → the platform fee wallet (tracked internally by the matrix engines), admin 1% → the admin
income wallet. Each Core upline commission is further split **70 / 20 / 10** (upline / repurchase
reserve / software fee). A Core half with no eligible upline (or no valid BEP-20 address) is folded
into the platform fee, so **the split always sums to the pack price**. (Split logic in
`app/core/pack_payout.py`; matrix + repurchase execution on `pack/status` in
`app/core/matrix_runtime.py` + `app/core/repurchase.py`.)

> When a half folds because the decided recipient has no wallet address (not because they're
> ineligible), the response also carries a reporting-only `core_unpaid` recipient — same shape as
> `upline` but `amount: 0` and `has_wallet_address: false`, so it never affects the on-chain payment
> list or the ledger. It exists purely so the Purchase Distribution Preview (and anything else
> reading `recipients_json`) can say who the routing meant to pay instead of that half just
> vanishing into `platform_fee` anonymously.

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
    { "role": "admin",             "level": null, "wallet_address": "0x…", "has_wallet_address": true, "amount": 0.10 },
    { "role": "platform_fee",      "level": null, "wallet_address": "0x…", "has_wallet_address": true, "amount": 3.90 }
  ]
}
```

> $10 pack, two eligible uplines: each upline's $3 Core half is paid 70/20/10 → **$2.10** on-chain
> + **$0.60** reserve + **$0.30** fee (reserve/fee shown summed across uplines). Stream $3 + Boost
> $0.90 land in `platform_fee` (**$3.90**) since those matrix pools are tracked internally rather
> than held in their own on-chain wallet; admin $0.10 completes the $10. Roles and amounts vary
> with eligibility.

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
  `PLATFORM_FEE_WALLET` (**set before go-live** — also receives the Stream 30% + Boost-pool 9%
  shares, which are tracked internally rather than held in their own on-chain wallet),
  `VERIFY_ONCHAIN_TX` (optional tx verification, off by default), plus `ADMIN_INCOME_WALLET` and
  `REPURCHASE_RESERVE_WALLET` (each falls back to `PLATFORM_FEE_WALLET` when unset — set distinct
  addresses before go-live, and fund `REPURCHASE_RESERVE_WALLET` with its own BNB for gas — no
  separate gas wallet), and `BSC_RPC_URL` / `REPURCHASE_SIGNER_PRIVATE_KEY` (auto-repurchase's
  on-chain settlement — see [Auto-Repurchase](#auto-repurchase); leave the key empty to stay
  internal-ledger-only).

---

## Member Payout (admin distribution)

`pack/purchase` + `pack/status` move money buyer → platform (+ uplines) on-chain. This pair runs the
**same MultiSender contract in reverse**: platform wallet → every member with a positive withdrawable
balance (their share of Stream/Boost matrix payouts and Core commissions accumulated internally).
Admin-only; mirrors the pack-purchase lifecycle exactly.

```
POST /distribution/payout/create   → Admin JWT. No body.
   → snapshots every user's withdrawable balance (MAIN + ACCOUNT), returns a batch_id +
     recipient list (address + amount) for the platform wallet to pay out via
     sendERC20DifferentValue. Refuses to create a new batch while one is already
     PENDING (prevents overlapping snapshots from double-debiting the same balance).
POST /distribution/payout/status   → Admin JWT. Body: { batch_id, status, tx_hash?, failure_reason? }
   → records the on-chain result. On success, debits each recipient's withdrawable balance
     (MAIN wallets lowest-tier-first, then ACCOUNT — via `debit_withdrawable`) by exactly the
     snapshotted amount, so the next payout/create won't offer the same money again. PENDING-
     guarded, so a batch can only ever be settled once — this is the step that turns "credited
     internally" into "actually paid."
```

- Users with a positive withdrawable balance but no valid BEP-20 address are skipped and reported
  under `skipped_no_address` (count + amount) in the `payout/create` response, so nothing silently
  vanishes.
- Batch records live in `payout_batches` (`app/models/payout_batch.py`). Run `python migrate_v20.py`
  once on existing DBs; `create_tables.py` covers fresh installs.
- On-chain verification (`VERIFY_ONCHAIN_TX`) is not wired for this rail (same as `pack/status`
  today) — `payout/status` trusts the admin-supplied `tx_hash`.

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
- Platform-wide stats (platform profit, admin income, total invested by users) and transaction history (resolved to usernames, with a Completed/Pending status column + filter — see [Earnings Transparency](#earnings-transparency--completed-vs-pending))
- **Platform Wallets** — live on-chain USDT + native BNB balance for the three platform-controlled wallets (Platform Fee, Admin Income, Repurchase Reserve), auto-refreshing every 20s, with a low-gas warning on the Repurchase Reserve wallet (the only one that broadcasts its own transaction and so the only one that needs gas)
- View per-user details (agents bought, registered wallet address, revenue generated — note: NOT account balance, which is always $0 on the on-chain rail since there's no deposit path to fund it); freeze / unfreeze individual users (blocks login and all money movement to/from them — Core, sponsor-share, and Stream/Boost matrix payouts they'd otherwise receive are retained as platform profit instead); admins can't be frozen or deleted
- **Delete user** — hard delete; re-parents their downline to keep the sponsor tree connected, preserves realized platform profit by re-attributing it to the admin (including forfeiting any unconsumed repurchase reserve as platform profit, per spec — it doesn't just vanish with the deleted wallet rows), and removes their wallets/transactions/purchases/matrix positions so it doesn't fail on a foreign-key constraint
- **Treasury** — *Send to User* by username, instantly and fee-free (kept fully separate from the user deposit/transfer/withdraw flows). *(The *Generate* / fund-minting feature and the "Treasury Balance" dashboard card were removed; the `ADMIN_GENERATE` ledger type is retained only for historical reporting.)*
- **Global freeze (kill switch)** — one click pauses all money movement platform-wide, for admins too: new purchases, purchase settlement (ownership + ledger + matrix cascade + auto-repurchase), the member-payout rail, and admin treasury/wallet-credit/wallet-debit. Only an admin can lift it (freeze/unfreeze itself is never blocked)
- **Revenue Engines page** (`/admin/revenue-engines`) — Core compression/odd-even routing simulator for any username, plus live Stream/Boost matrix queue fill-state and contents. See [Revenue Engine Visualization](#revenue-engine-visualization-admin--user)
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
| `PLATFORM_FEE_WALLET`       | BEP-20 wallet that receives the pack-purchase platform fee, the 10% Core software fee, and the Stream 30% + Boost-pool 9% shares (**set before go-live**); also the fallback for the two wallets below |
| `ADMIN_INCOME_WALLET`       | Receives the 1% Boost-allocation admin cut (falls back to `PLATFORM_FEE_WALLET`) |
| `REPURCHASE_RESERVE_WALLET` | Receives the 20% repurchase reserve (falls back to `PLATFORM_FEE_WALLET`); fund this address with its own BNB for gas — no separate gas wallet |
| `BSC_RPC_URL`               | RPC endpoint for the auto-repurchase settlement broadcast; defaults to BSC testnet, matching the mock `USDT_CONTRACT` this repo ships with |
| `REPURCHASE_SIGNER_PRIVATE_KEY` | Private key that signs the auto-repurchase on-chain settlement (`app/core/onchain.py`). **Live private key — never commit a real one.** Leave empty to keep auto-repurchase internal-ledger-only (default, safe) |
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
- Matrix concurrency uses PostgreSQL `SELECT FOR UPDATE` on `MatrixLevelQueue` / `MatrixQueueSlot` (per-level FIFO queues — see [Matrix System](#matrix-system)).
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
- **Platform freeze scope:** `require_platform_active` (admin bypass) gates the buyer-facing `pack/purchase` + `pack/status`; `ensure_platform_active` (no bypass, applies to admins too) gates `payout/create`, `payout/status`, `admin/transfer`, `admin/wallet/credit`, and `admin/wallet/debit` — see `app/core/platform_state.py`. A `PENDING` pack purchase left over from before a freeze simply waits — `pack/status` re-processes it normally once unfrozen.
- **Per-user freeze** (`User.is_active=False`) is checked at `/auth/login` (clear 403 "account frozen" message, not a token followed by a confusing failure) and by `get_current_user` for every other endpoint. A frozen user's Core, sponsor-share, and Stream/Boost matrix payouts are retained as platform profit rather than credited to them (`app/core/proactive.py`, `app/core/matrix_runtime.py`), and their auto-repurchase reserve is held, not consumed.
- **All timestamps are displayed in IST (`Asia/Kolkata`).** The backend stores naive UTC; the frontend converts via `frontend/src/utils/datetime.js` (`formatDateTimeIST` / `formatDateIST` / `formatTimeIST`). Storage stays UTC — only the display is localized to Indian time.
- **Transaction types are lowercase enum values** (`agent_purchase`, `deposit`, `core_sent`, …). Transaction views (`Transactions.jsx`, `admin/AdminTransactions.jsx`) classify them into Income / Expense / System groups using **lowercase** keys; `core_sent` is an audit record of the Core split sent upline at purchase and is **not** counted as income. `withdrawal_refund` (a failed-payout reversal) is also classified as System, not income. Both pages also carry a separate Completed/Pending **Status** classification (`core_income` is always Completed; `repurchase_hold`/`stream_payout`/`boost_payout`/`sponsor_milestone_income` are Pending) — see [Earnings Transparency](#earnings-transparency--completed-vs-pending).
- **On-chain "Wallet Balance"** shown on the Dashboard and Buy Agents pages is the connected wallet's **live on-chain USDT** (`frontend/src/hooks/useUsdtBalance.js`), not an internal balance — it silently repolls every 20s while a wallet is connected (paused when the tab is backgrounded), not just once on load. Set `VITE_USDT_ADDRESS` to match the backend `USDT_CONTRACT`, connect a wallet, and restart the Vite dev server. On-chain purchases **do** populate internal wallets: on `pack/status` success each Core commission is credited 70/20/10 (`mirror_onchain_earning_split`) and the Stream/Boost matrix payouts credit via `credit_wallet`, so main / repurchase-reserve balances fill and on-chain activity also shows in transaction history and the income chart.
- **There is no standalone user Wallet page.** Its balances/reserve cards and transaction history were redundant with the Dashboard and Transactions pages, so it was removed (`/wallet` route, nav entry, and `pages/Wallet.jsx` all deleted) — don't reintroduce it without asking. Balances live on the Dashboard; full transaction history is on `/transactions`.
- **User Dashboard's "Quick Actions" card and Admin Overview's "Recent Transactions" / "Transaction Breakdown" sections were removed** — low-value once the Completed/Pending breakdown and dedicated Transactions pages covered the same ground. Don't reintroduce without asking.
- **`GET /admin/metrics`'s `total_credited_to_wallets` only counts Stream/Boost/Sponsor's 70% share**, not Core's — Core's 70% is paid directly on-chain and never touches an internal wallet, so including it there would overstate what's actually sitting in user MAIN wallets. (This was a real bug, fixed.)
- **Admin's per-user drill-down (`GET /admin/users/{id}/summary`) shows `wallet_address`, not `account_balance`** — the account wallet is always $0 on the on-chain rail (no deposit path funds it), so it wasn't useful to show. `ADMIN_INCOME` transactions (the 1% Boost cut) are tracked as their own `admin_income` figure in `/admin/treasury/summary`, separate from `platform_profit` (`SOFTWARE_FEE` + `PLATFORM_PROFIT`).
- **Direct Referrals** on the Dashboard is a click-to-expand dropdown (not just a count) listing every direct referral with username + active/frozen status, sourced from the existing `GET /auth/referrals` (`referrals: [...]`) response.
- **Wallet-connect widget** in the topbar (`<appkit-button>`) is hidden for admin accounts — it's only relevant to the on-chain purchase flow, which admins don't use; every admin action is pure backend/JWT logic against backend-configured wallet addresses.
