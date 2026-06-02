from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    DATABASE_URL: str = "postgresql://luxus:dhanush@localhost/luxus"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "changeme-use-a-real-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Environment — "development" uses NOWPayments sandbox, "production" uses live
    APP_ENV: str = "development"

    # Logging verbosity: DEBUG | INFO | WARNING | ERROR
    LOG_LEVEL: str = "INFO"

    # CORS — comma-separated list of allowed frontend origins, or "*" for any.
    # In production set this to your hosted frontend URL, e.g.
    #   CORS_ORIGINS=https://app.yourdomain.com
    CORS_ORIGINS: str = "*"

    # NOWPayments
    NOWPAYMENTS_API_KEY: str = ""
    NOWPAYMENTS_IPN_SECRET: str = ""
    # Public URL of this backend (NOWPayments will POST the IPN here)
    NOWPAYMENTS_CALLBACK_BASE: str = "https://yourdomain.com"
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
