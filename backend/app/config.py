import os
import re


def _public_url(raw: str) -> str:
    """PUBLIC_APP_URL as a clean origin: erp.example.com -> https://erp.example.com, 192.168.1.44:3000 -> http://192.168.1.44:3000."""
    raw = raw.strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = (
            "http://"
            if re.match(r"^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?$", raw, re.I)
            else "https://"
        ) + raw
    return raw


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
    # Frontend URL for "Open in the portal" links in notification emails.
    portal_url: str = os.getenv("PORTAL_BASE_URL", "http://localhost:3000")
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

    # Unit-by-unit inspection: accuracy (OK units / received units, in percent) at or above which approving is suggested,
    # and the most units one shipment may track individually.
    inspection_accept_threshold: float = float(os.getenv("INSPECTION_ACCEPT_THRESHOLD", "95"))
    inspection_max_units: int = int(os.getenv("INSPECTION_MAX_UNITS", "2000"))
    # Address of the web app as other devices reach it (for example https://erp.example.com). QR labels encode
    # {public_app_url}/units/{code}, so scanning one with a phone camera opens the unit page. Set it to your domain
    # (https://erp.example.com) or, on a local network, to this computer's address (http://192.168.1.44:3000).
    # Empty = the labels fall back to the address the supplier's browser is on.
    public_app_url: str = _public_url(os.getenv("PUBLIC_APP_URL", ""))

    # In-app assistant: natural-language form filling uses OpenAI structured outputs. Without a key only the numbered menus work.
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")


settings = Settings()
