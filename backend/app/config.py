from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    DATABASE_URL: str = "postgresql://luxus:dhanush@localhost/luxus"
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
    USDT_CONTRACT: str = "0xb2681F1CA80e080827d5f275648D2d2e2684f0C8"
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
    # RPC endpoint used to broadcast the settlement transfer below. Defaults to
    # BSC TESTNET's public endpoint, matching the mock USDT_CONTRACT this project
    # ships with (0xb268... / 6 decimals is a testnet token, not real mainnet
    # USDT) — override to a mainnet RPC only once USDT_CONTRACT is the real
    # mainnet token and the signer wallet holds real funds.
    BSC_RPC_URL: str = "https://data-seed-prebsc-1-s1.binance.org:8545/"
    # Private key of the wallet that signs the auto-repurchase settlement
    # transfer — this must be REPURCHASE_RESERVE_WALLET's own key, since the
    # ERC20 transfer is sent FROM whichever address this key controls, and that
    # same wallet also pays its own BNB gas for the transaction — fund that
    # address with BNB directly (manually; there is no automated top-up). Left
    # empty by default: auto-repurchase then stays internal-ledger-only
    # (today's behavior), no transaction is ever attempted. THIS IS A LIVE
    # PRIVATE KEY — never commit a real one; treat this exactly like SECRET_KEY.
    REPURCHASE_SIGNER_PRIVATE_KEY: str = ""

    @property
    def admin_income_wallet(self) -> str:
        return self.ADMIN_INCOME_WALLET or self.PLATFORM_FEE_WALLET

    @property
    def repurchase_reserve_wallet(self) -> str:
        return self.REPURCHASE_RESERVE_WALLET or self.PLATFORM_FEE_WALLET
    # When true, API 2 (mark status) verifies the tx_hash on-chain before recording
    # success. Left off by default — wire up an RPC check before enabling.
    VERIFY_ONCHAIN_TX: bool = False

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

    model_config = {
        # Looks for .env one level up (project root) when running from backend/
        "env_file": ("../.env", ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
