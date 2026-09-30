import os


class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "./data/erp.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me-please-use-32-bytes-min")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
    smtp_host: str = os.getenv("SMTP_HOST", "localhost")
    smtp_port: int = int(os.getenv("SMTP_PORT", "1025"))
    mailpit_url: str = os.getenv("MAILPIT_URL", "http://localhost:8025")
    smtp_from: str = os.getenv("SMTP_FROM", "erp-copilot@example.com")
    email_enabled: bool = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
    cors_origins: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    # Also allow browsers on private networks (localhost, 10.x, 172.16-31.x, 192.168.x) on any port.
    # Set CORS_ORIGIN_REGEX to an empty string to disable, or tighten it for production.
    cors_origin_regex: str = os.getenv(
        "CORS_ORIGIN_REGEX",
        r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$",
    )
    # Bootstrap admin (created at startup if missing). Demo data adds admin@demo.com regardless.
    admin_email: str = os.getenv("ADMIN_EMAIL", "")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    seed_demo_data: bool = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"
    # Which ERP connector backs inventory/vendors: "sap" or "infor"
    erp_backend: str = os.getenv("ERP_BACKEND", "sap")
    # How often the background job checks quote deadlines (reminders / "quotes closed"). 0 disables it.
    deadline_check_seconds: int = int(os.getenv("DEADLINE_CHECK_SECONDS", "60"))


settings = Settings()
