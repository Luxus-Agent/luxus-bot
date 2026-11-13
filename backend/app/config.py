from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    DATABASE_URL: str = "postgresql://luxus:CHANGE_ME@localhost/luxus"
    SECRET_KEY: str = "changeme-use-a-real-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Environment — "development" | "production"
    APP_ENV: str = "development"

    # Logging verbosity: DEBUG | INFO | WARNING | ERROR
    LOG_LEVEL: str = "INFO"

    # CORS — comma-separated list of allowed frontend origins, or "*" for any.
    # In production set this to your hosted frontend URL, e.g.
    #   CORS_ORIGINS=https://app.yourdomain.com
    CORS_ORIGINS: str = "*"

    # On-chain pack-purchase payout (TokenPocket / MultiSender, BEP-20 USDT).
    # These describe WHERE the frontend sends funds; the backend only computes the
    # split and records the result. Override in .env for the live chain/token.
    PAYOUT_CURRENCY: str = "USDT"
    PAYOUT_NETWORK: str = "BEP-20"
    # USDT token contract on the active chain (decimals as given by the client).
    # Default = BSC MAINNET's official BSC-USD (USDT), 18 decimals. A testnet/dev
    # setup must override BOTH in .env (the old mock token used 6 decimals).
    USDT_CONTRACT: str = "0x55d398326f99059fF775485246999027B3197955"
    USDT_DECIMALS: int = 18
    # Wallet that receives the platform-fee portion of each pack purchase — the flat
    # per-tier fee, the 10% Core software fee, and the Stream (30%) + Boost-pool (9%)
    # shares (those matrix pools are tracked internally, not held in a separate
    # on-chain wallet). Set this in .env before go-live; when empty the platform_fee
    # recipient address is null.
    PLATFORM_FEE_WALLET: str = ""
    # Admin income wallet — receives the 1% Boost-allocation admin cut on each
    # purchase. When empty it falls back to PLATFORM_FEE_WALLET.
    ADMIN_INCOME_WALLET: str = ""
    # Platform reserve wallet — receives the 20% repurchase reserve skimmed from
    # each Core commission. Held per-user (tracked internally) to fund auto-
    # repurchase. When empty it falls back to PLATFORM_FEE_WALLET.
    REPURCHASE_RESERVE_WALLET: str = ""

    # ── Auto-repurchase on-chain broadcast ───────────────────────────────────
    # RPC endpoint used to broadcast the settlement transfers below. Defaults to
    # BSC MAINNET's public endpoint (chain 56), matching the default USDT_CONTRACT.
    # The public endpoint is rate-limited — use a dedicated provider (QuickNode,
    # Ankr, NodeReal, …) in production. For testnet set BSC_RPC_URL to
    # https://data-seed-prebsc-1-s1.binance.org:8545/ AND override USDT_CONTRACT.
    BSC_RPC_URL: str = "https://bsc-dataseed.binance.org/"
    # Private key of the wallet that signs the auto-repurchase settlement
    # transfer — this must be REPURCHASE_RESERVE_WALLET's own key, since the
    # ERC20 transfer is sent FROM whichever address this key controls, and that
    # same wallet also pays its own BNB gas for the transaction — fund that
    # address with BNB directly (manually; there is no automated top-up). Left
    # empty by default: auto-repurchase then stays internal-ledger-only
    # (today's behavior), no transaction is ever attempted. THIS IS A LIVE
    # PRIVATE KEY — never commit a real one; treat this exactly like SECRET_KEY.
    REPURCHASE_SIGNER_PRIVATE_KEY: str = ""
    # Private key that signs Stream/Boost matrix payout settlements (and their
    # sponsor-share bonus) — this must be PLATFORM_FEE_WALLET's own key, since
    # that's already where Stream's 30% + Boost's 9% shares land on-chain at
    # purchase time, and the ERC20 transfer is sent FROM whichever address this
    # key controls. That wallet needs its own BNB for gas (no automated top-up,
    # same requirement as REPURCHASE_SIGNER_PRIVATE_KEY above). Left empty by
    # default: Stream/Boost payouts stay internal-ledger-only (today's
    # behavior, credited via credit_wallet/credit_main_wallet_direct), no
    # transaction is ever attempted. THIS IS A LIVE PRIVATE KEY — never commit
    # a real one; treat this exactly like SECRET_KEY.
    PLATFORM_FEE_SIGNER_PRIVATE_KEY: str = ""
    # How long a settlement broadcast waits for its receipt (so a reverted tx is
    # never recorded as paid). On timeout it is treated as paid-but-pending.
    # Each broadcast blocks its request for up to this long (BSC blocks ~3s).
    SETTLEMENT_RECEIPT_TIMEOUT_SECONDS: int = 20

    @property
    def admin_income_wallet(self) -> str:
        return self.ADMIN_INCOME_WALLET or self.PLATFORM_FEE_WALLET

    @property
    def repurchase_reserve_wallet(self) -> str:
        return self.REPURCHASE_RESERVE_WALLET or self.PLATFORM_FEE_WALLET
    # When true (default), API 2 (pack/status) verifies the tx_hash on-chain —
    # mined, succeeded, and the USDT Transfer to every recipient in the order —
    # before recording success. Only turn off for local dev without an RPC.
    VERIFY_ONCHAIN_TX: bool = True

    # Rate limiting + OTP attempt limits on the auth endpoints (core/rate_limit.py).
    # Leave on; only disable for automated tests.
    RATE_LIMIT_ENABLED: bool = True

    # Public URL of the frontend (used in emails / links).
    FRONTEND_URL: str = "http://localhost:3000"

    # SMTP (email)
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SENDER_EMAIL: str = ""

    # Admin seed
    ADMIN_EMAIL: str = "admin@luxus.io"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme"
    ADMIN_REFERRAL_CODE: str = "ADMIN001"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS into a list. '*' → allow any origin."""
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() == "production"

    def production_problems(self) -> list[str]:
        """Insecure/leftover-dev settings that must not reach a live deployment."""
        problems: list[str] = []
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY.lower().startswith("change"):
            problems.append("SECRET_KEY is a default/short value (use 32+ random chars)")
        if self.ADMIN_PASSWORD.lower().startswith("change") or len(self.ADMIN_PASSWORD) < 12:
            problems.append("ADMIN_PASSWORD is a default/short value (use 12+ chars)")
        if ":dhanush@" in self.DATABASE_URL or ":CHANGE_ME@" in self.DATABASE_URL:
            problems.append("DATABASE_URL still uses a default/placeholder DB password")
        if self.CORS_ORIGINS.strip() == "*":
            problems.append("CORS_ORIGINS is '*' (set it to the frontend origin)")
        if "localhost" in self.FRONTEND_URL or "127.0.0.1" in self.FRONTEND_URL:
            problems.append("FRONTEND_URL points at localhost")
        if not self.VERIFY_ONCHAIN_TX:
            problems.append("VERIFY_ONCHAIN_TX is off (purchases would not be verified on-chain)")
        for name in ("PLATFORM_FEE_WALLET", "ADMIN_INCOME_WALLET", "REPURCHASE_RESERVE_WALLET"):
            if not getattr(self, name).strip():
                problems.append(f"{name} is empty")
        wallets = {
            getattr(self, n).strip().lower()
            for n in ("PLATFORM_FEE_WALLET", "ADMIN_INCOME_WALLET", "REPURCHASE_RESERVE_WALLET")
            if getattr(self, n).strip()
        }
        if len(wallets) < 3:
            problems.append("PLATFORM_FEE/ADMIN_INCOME/REPURCHASE_RESERVE wallets are not 3 distinct addresses")
        return problems

    model_config = {
        # Looks for .env one level up (project root) when running from backend/
        "env_file": ("../.env", ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()

# Refuse to boot a production deployment with leftover dev defaults.
if settings.is_production:
    _problems = settings.production_problems()
    if _problems:
        raise RuntimeError(
            "APP_ENV=production but the configuration is not production-safe:\n  - "
            + "\n  - ".join(_problems)
        )
