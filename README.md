# Luxus — AI Agent Revenue Sharing Platform

A multi-tier passive income platform where users purchase AI agent tiers and earn revenue through three parallel systems: ProActive income, Proportion matrix, and Speculation matrix.

---

## Table of Contents

- [Architecture](#architecture)
- [Revenue Flow](#revenue-flow)
- [User Journey](#user-journey)
- [Auth Flow](#auth-flow)
- [Deposit & Purchase Flow](#deposit--purchase-flow)
- [Matrix System](#matrix-system)
- [Withdrawal Flow](#withdrawal-flow)
- [Tech Stack](#tech-stack)
- [Setup & Installation](#setup--installation)
- [Running the Project](#running-the-project)
- [Admin Setup](#admin-setup)
- [Environment Variables](#environment-variables)

---

## Architecture

```mermaid
graph TB
    subgraph Frontend["Frontend (Vite + React)"]
        UI[React SPA<br/>port 3000]
    end

    subgraph Backend["Backend (FastAPI)"]
        API[FastAPI<br/>port 8000]
        CELERY[Celery Worker]
    end

    subgraph Data["Data Layer"]
        PG[(PostgreSQL 18)]
        REDIS[(Redis)]
    end

    subgraph External["External Services"]
        NOW[NOWPayments<br/>USDT BEP-20]
        SMTP[SMTP Email]
    end

    UI -- "/api/* proxy" --> API
    API --> PG
    API --> REDIS
    CELERY --> REDIS
    CELERY --> PG
    API --> NOW
    CELERY --> NOW
    CELERY --> SMTP
    NOW -- "IPN webhook" --> API
```

---

## Revenue Flow

Every confirmed agent purchase triggers a **60/30/10 split** that runs three parallel income systems.

```mermaid
flowchart TD
    PURCHASE["Agent Purchase ($10 / $20 / $50 / $100)"]
    PURCHASE --> SPLIT["Revenue Split Engine"]

    SPLIT -->|"60%"| PROACTIVE["ProActive System"]
    SPLIT -->|"30%"| PROPORTION["Proportion Matrix (3x3)"]
    SPLIT -->|"10%"| SPECULATION["Speculation Matrix (3x3)"]

    PROACTIVE -->|"30% → direct sponsor"| SP1["Sponsor Wallet<br/>(odd/even routing)"]
    PROACTIVE -->|"30% → sponsor's sponsor"| SP2["Supreme Sponsor Wallet<br/>(odd/even routing)"]

    PROPORTION --> PM["BFS queue placement<br/>L1 (3) → L2 (9) → L3 (27)"]
    PM -->|"L1 fills"| PL1["$2 wallet + 1 re-entry"]
    PM -->|"L2 fills"| PL2["$7 wallet + 2 re-entries"]
    PM -->|"L3 fills"| PL3["$26 wallet + 3 re-entries"]

    SPECULATION --> SM["BFS queue placement<br/>L1 (3) → L2 (9) → L3 (27)"]
    SM -->|"L1 fills"| SL1["$0.60 wallet + 1 re-entry"]
    SM -->|"L2 fills"| SL2["$2.10 wallet + 2 re-entries"]
    SM -->|"L3 fills"| SL3["$7.20 wallet + 3 re-entries"]

    PL1 & PL2 & PL3 & SL1 & SL2 & SL3 -->|"all re-entries"| REENTRY["New SPECULATION position<br/>(dummy — fills for others)"]

    PL1 & PL2 & PL3 & SL1 & SL2 & SL3 --> WALLET_SPLIT["Wallet Credit"]
    WALLET_SPLIT -->|"90%"| MAIN["Main Wallet<br/>(withdrawable)"]
    WALLET_SPLIT -->|"10%"| REPURCHASE["Repurchase Reserve<br/>(auto-hold)"]

    REPURCHASE -->|"balance >= tier price"| AUTO["Auto-repurchase<br/>new agent purchase"]
```

### ProActive Odd/Even Rule

```mermaid
flowchart LR
    BUYER["New Purchase"]
    BUYER -->|"30%"| SPONSOR["Sponsor"]
    BUYER -->|"30%"| SUPREME["Supreme Sponsor"]

    SPONSOR --> ODD_CHECK{"Proactive TX count<br/>for sponsor"}
    ODD_CHECK -->|"next is ODD"| KEEP["Credit sponsor's wallet"]
    ODD_CHECK -->|"next is EVEN"| PASSUP["Pass up to<br/>sponsor's sponsor"]

    SUPREME --> ODD_CHECK2{"Proactive TX count<br/>for supreme sponsor"}
    ODD_CHECK2 -->|"next is ODD"| KEEP2["Credit supreme<br/>sponsor's wallet"]
    ODD_CHECK2 -->|"next is EVEN"| PASSUP2["Pass up to<br/>their sponsor"]
```

---

## User Journey

```mermaid
journey
    title User Journey on Luxus
    section Onboarding
      Register with sponsor code: 5: User
      Verify email via OTP: 4: User
      Login to dashboard: 5: User
    section Funding
      Deposit USDT via NOWPayments: 3: User
      Account balance credited: 5: System
    section Agent Purchase
      Browse agent tiers: 5: User
      Purchase agent from balance: 5: User
      Revenue systems activated: 5: System
    section Earning
      Receive ProActive income: 5: System
      Matrix positions fill up: 4: System
      Auto-repurchase triggers: 4: System
    section Withdrawal
      Register BEP-20 address: 3: User
      Request withdrawal (min $10): 4: User
      USDT sent via NOWPayments: 5: System
```

---

## Auth Flow

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant API as FastAPI
    participant DB as PostgreSQL
    participant EMAIL as SMTP

    U->>FE: Fill register form (email, username, password, sponsor code)
    FE->>API: POST /auth/register
    API->>DB: Create user (is_email_verified=false)
    API->>EMAIL: Send 6-digit OTP
    FE->>U: Redirect to verify-email page

    U->>FE: Enter OTP
    FE->>API: POST /auth/verify-email
    API->>DB: Mark is_email_verified=true
    FE->>U: Redirect to login

    U->>FE: Enter email + password
    FE->>API: POST /auth/login
    API->>FE: JWT access token
    FE->>API: GET /auth/me
    API->>FE: Full profile (is_admin, username, referral_code...)
    
    alt is_admin = true
        FE->>U: Redirect to /admin (Admin Dashboard)
    else is_admin = false
        FE->>U: Redirect to /dashboard (User Dashboard)
    end
```

---

## Deposit & Purchase Flow

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant API as FastAPI
    participant NOW as NOWPayments
    participant CELERY as Celery
    participant DB as PostgreSQL

    Note over U,DB: Deposit Flow
    U->>FE: Enter deposit amount
    FE->>API: POST /deposit
    API->>NOW: Create invoice (USDT BEP-20)
    NOW->>FE: invoice_url
    FE->>U: Show payment link
    U->>NOW: Send USDT
    NOW->>API: POST /webhooks/nowpayments/ipn (HMAC verified)
    API->>DB: Credit ACCOUNT wallet balance

    Note over U,DB: Purchase Flow
    U->>FE: Select agent tier ($10/$20/$50/$100)
    FE->>API: POST /agents/purchase
    API->>DB: Deduct from ACCOUNT balance
    API->>CELERY: Queue activate_purchase task
    CELERY->>DB: Revenue split (60/30/10)
    CELERY->>DB: ProActive payouts (odd/even routing)
    CELERY->>DB: Matrix placement (BFS)
    CELERY->>DB: Matrix payouts + re-entries
```

---

## Matrix System

```mermaid
graph TD
    subgraph "3x3 Forced Matrix (BFS)"
        P1["Position #1 (you)"]
        P1 --> P2["Slot 1"]
        P1 --> P3["Slot 2"]
        P1 --> P4["Slot 3"]
        P2 --> P5["Slot 4"] & P6["Slot 5"] & P7["Slot 6"]
        P3 --> P8["Slot 7"] & P9["Slot 8"] & P10["Slot 9"]
        P4 --> P11["Slot 10"] & P12["Slot 11"] & P13["Slot 12"]
    end

    P2 & P3 & P4 -->|"L1 = 3 filled"| L1PAY["L1 Payout"]
    P5 & P6 & P7 & P8 & P9 & P10 & P11 & P12 & P13 -->|"L2 = 9 filled"| L2PAY["L2 Payout"]

    subgraph "Payout (Agent 1 / $10)"
        L1PAY --> L1A["Proportion: $2.00 + 1 re-entry"]
        L1PAY --> L1B["Speculation: $0.60 + 1 re-entry"]
        L2PAY --> L2A["Proportion: $7.00 + 2 re-entries"]
        L2PAY --> L2B["Speculation: $2.10 + 2 re-entries"]
    end
```

---

## Withdrawal Flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant DB as PostgreSQL
    participant CELERY as Celery
    participant NOW as NOWPayments
    participant EMAIL as SMTP

    U->>API: POST /wallet/address (BEP-20 address)
    API->>EMAIL: Send OTP
    U->>API: POST /wallet/address/verify (OTP)
    API->>DB: Mark address as verified

    U->>API: POST /wallet/withdraw (amount >= $10)
    API->>DB: Deduct from MAIN wallet, create WithdrawalRequest
    API->>EMAIL: "Withdrawal scheduled" email
    API->>CELERY: Queue process_withdrawal (immediate)

    CELERY->>NOW: POST /v1/payout (USDT BEP-20)
    alt Success
        NOW->>CELERY: Payout confirmed
        CELERY->>DB: status = sent
        CELERY->>EMAIL: "Withdrawal dispatched" email
    else Failure (retry x3)
        NOW->>CELERY: Error
        CELERY->>DB: status = failed, refund to MAIN wallet
        CELERY->>EMAIL: "Withdrawal failed + refunded" email
    end
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vite + React 18 + Tailwind CSS |
| Backend | FastAPI (Python 3.11+) |
| Database | PostgreSQL 18 |
| Task Queue | Celery + Redis |
| Auth | JWT — python-jose + passlib/bcrypt 4.0.1 |
| Payments | NOWPayments (USDT on BEP-20) |
| Email | SMTP (configurable — Gmail, Mailer91, etc.) |

---

## Setup & Installation

### Prerequisites

- Python 3.11+ with conda env `luxus`
- PostgreSQL 18 running on localhost:5432
- Redis running on localhost:6379
- Node.js 18+ (for frontend)

### 1. Clone & configure environment

```bash
cp .env.example .env
# Edit .env — fill in NOWPAYMENTS keys, SMTP credentials, ADMIN_* fields
```

### 2. Install backend dependencies

```bash
conda activate luxus
pip install -r requirements.txt
```

### 3. Create database tables

```bash
cd backend
python create_tables.py
```

### 4. Run all migrations in order

```bash
python migrate_v2.py   # enum values + deposits table
python migrate_v3.py   # sponsor_milestone_income enum
python migrate_v4.py   # is_admin column
python migrate_v5.py   # dummy re-entries, transfer verifications, wallet addresses
python migrate_v6.py   # fix enum case mismatch (ACCOUNT, DEPOSIT, etc.)
```

### 5. Seed the admin user

```bash
python seed_admin.py
```

Reads `ADMIN_EMAIL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_REFERRAL_CODE` from `.env`. Safe to re-run.

### 6. Install frontend dependencies

```bash
cd ../frontend
npm install
```

---

## Running the Project

Open **4 terminals**:

```bash
# Terminal 1 — Backend API
conda activate luxus
cd backend
uvicorn app.main:app --reload
# → http://localhost:8000
# → Swagger docs: http://localhost:8000/docs

# Terminal 2 — Celery worker (handles async revenue + withdrawals)
conda activate luxus
cd backend
celery -A app.workers.celery_app worker --loglevel=info

# Terminal 3 — Redis (if not running as a service)
redis-server

# Terminal 4 — Frontend
cd frontend
npm run dev
# → http://localhost:3000
```

---

## Admin Setup

The admin cannot self-register. Create via the seed script:

```bash
# Set credentials in .env first:
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=StrongPassword@123
ADMIN_REFERRAL_CODE=ADMIN001

cd backend
python seed_admin.py
```

Login at **http://localhost:3000** with the admin credentials — the system automatically routes admin users to the **Admin Dashboard** (`/admin`).

### Admin capabilities

- Platform-wide stats (users, transactions, withdrawals)
- Freeze / unfreeze user accounts
- Credit or debit any user's wallet directly
- View all withdrawals and transaction history
- Access their own user account pages (wallet, matrix, etc.) from admin sidebar

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `SECRET_KEY` | JWT signing secret (use a long random string in production) |
| `APP_ENV` | `development` (sandbox) or `production` (live NOWPayments) |
| `NOWPAYMENTS_API_KEY` | NOWPayments API key |
| `NOWPAYMENTS_IPN_SECRET` | NOWPayments IPN secret for HMAC verification |
| `NOWPAYMENTS_CALLBACK_BASE` | Public URL of backend for IPN callbacks (use ngrok locally) |
| `FRONTEND_URL` | Frontend URL for payment redirect links |
| `SMTP_SERVER` | SMTP host |
| `SMTP_PORT` | SMTP port (usually 587) |
| `SMTP_USERNAME` | SMTP login username |
| `SMTP_PASSWORD` | SMTP password / app password |
| `SENDER_EMAIL` | From address for outgoing emails |
| `ADMIN_EMAIL` | Admin account email (used by seed_admin.py) |
| `ADMIN_USERNAME` | Admin account username |
| `ADMIN_PASSWORD` | Admin account password |
| `ADMIN_REFERRAL_CODE` | Admin referral code (used as sponsor for first users) |

---

## Agent Tier Pricing & Payouts

| Tier | Price | ProActive (60%) | Proportion L3 | Speculation L3 |
|------|-------|-----------------|---------------|----------------|
| Agent 1 | $10 | $6.00 split between sponsor chain | $26.00 | $7.20 |
| Agent 2 | $20 | $12.00 split | $52.00 | $14.40 |
| Agent 3 | $50 | $30.00 split | $130.00 | $36.00 |
| Agent 4 | $100 | $60.00 split | $260.00 | $72.00 |

All payouts: **90% to main wallet** (withdrawable) + **10% to repurchase reserve** (auto-held).
When repurchase reserve reaches the tier price, a new agent is automatically purchased.
