# Pack Purchase — On-Chain Payout API Spec

## Context

The platform is **MLM-based** (the "AI agent" naming is cosmetic — there is no AI
logic). When a user buys a pack, the pack amount is paid **on-chain in USDT
(BEP-20, BNB Smart Chain)** and split between the buyer's upline:

- **Upline levels (Level A → … → N)** — a **dynamic number of levels** going up
  the referral chain: Level A (direct sponsor), Level B (sponsor's sponsor), and
  so on. The **number of levels and each level's amount are decided by the
  backend** per purchase — the frontend does **not** assume a fixed count and
  simply pays out whatever recipients are returned.
- **Platform fee** — optional cut to a platform wallet

The **frontend executes the actual blockchain transfer** from the buyer's
connected wallet. So the backend's job is to (1) resolve and return the
validated destination wallet addresses + amounts, and (2) record the outcome
once the transfer is done.

Two POST APIs are required.

---

## API 1 — Create purchase & return payout split (POST)

Called when the user clicks "Purchase". The frontend sends the pack and amount;
the backend returns the recipients, each with a **validated BEP-20 address** and
the **amount** to send.

**Request (frontend → backend)**

```json
{
  "pack_name": "Agent 1",
  "amount": 10
}
```

(The buyer is identified by the auth token / session.)

**Response (backend → frontend)**

```json
{
  "purchase_id": "ord_123456",
  "currency": "USDT",
  "network": "BEP-20",
  "token_contract": "0x...",   // USDT contract on the active chain (optional but useful)
  "decimals": 18,
  "recipients": [
    { "role": "buyer",        "level": 0,    "wallet_address": "0x...", "amount": 0 },
    { "role": "upline",       "level": 1,    "wallet_address": "0x...", "amount": 5 },
    { "role": "upline",       "level": 2,    "wallet_address": "0x...", "amount": 3 },
    { "role": "upline",       "level": 3,    "wallet_address": "0x...", "amount": 1 },
    { "role": "platform_fee", "level": null, "wallet_address": "0x...", "amount": 1 }
  ]
}
```

Notes for the backend:

- `buyer` address is returned for **validation** (the frontend confirms it
  matches the connected wallet). Amount can be `0` / informational.
- `upline` entries represent the referral chain, `level: 1` = direct sponsor
  (Level A), `level: 2` = sponsor's sponsor (Level B), and so on. The **number
  of upline entries is dynamic** (1 to N) and decided by the backend — the
  frontend just pays whatever list is returned. Order by `level` ascending.
- Amounts are determined by the **backend's MLM split rules** — the values shown
  above are only an example.
- The split amounts should sum to the pack amount.
- All addresses must be validated as proper BEP-20 (`0x` + 40 hex). Each user's
  address comes from their registered `wallet_address`.
- Define the fallback when an upline is missing (e.g. buyer has no Level B): does
  that share go to the platform, roll to the next level, or get skipped?
- `platform_fee` is included **only if** a fee applies.
- `purchase_id` must be returned so it can be referenced by API 2.

---

## API 2 — Mark payment status (POST)

Called after the frontend completes (or fails) the on-chain transfer. Marks the
purchase **done** or **failed**.

**Request (frontend → backend)**

```json
{
  "purchase_id": "ord_123456",
  "status": "success",          // "success" | "failed"
  "tx_hash": "0x...",           // blockchain transaction hash (on success)
  "failure_reason": null         // optional, when status = "failed"
}
```

**Response (backend → frontend)**

```json
{
  "purchase_id": "ord_123456",
  "status": "success",
  "recorded_at": "2026-06-22T10:00:00Z"
}
```

Notes for the backend:

- On `success`: record the purchase as active, store the `tx_hash`, and update
  any ledger/wallet records. Ideally **verify the `tx_hash` on-chain** (amount,
  recipients, confirmations) before marking it complete.
- On `failed`: mark the purchase failed; no payout is recorded.

---

## Summary

1. **POST (create purchase)** → backend returns `purchase_id` + the list of
   validated recipient addresses (buyer, a dynamic number of upline levels
   Level A → N, and an optional platform fee) with amounts. Frontend uses this
   to run the on-chain USDT transfer (a single batched multi-sender call).
2. **POST (mark status)** → frontend reports `success`/`failed` with the
   `tx_hash`; backend records the result.
