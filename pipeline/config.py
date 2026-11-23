from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Settings:
    shopify_base_url: str = "http://127.0.0.1:8100/shopify"
    shopify_token: str = "shpat_mock_token"
    stripe_base_url: str = "http://127.0.0.1:8100/stripe"
    stripe_key: str = "sk_test_mock_key"
    target: str = "duckdb"
    duckdb_path: str = "data/warehouse.duckdb"
    database_url: str = ""
    page_size: int = 250
    max_retries: int = 6
    backoff_base: float = 0.5
    lookback_seconds: int = 120
    landing_dir: str = "data/landing"
    report_dir: str = "reports"
    slack_webhook_url: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        e = os.environ.get
        return cls(
            shopify_base_url=e("SHOPIFY_BASE_URL", cls.shopify_base_url),
            shopify_token=e("SHOPIFY_ACCESS_TOKEN", cls.shopify_token),
            stripe_base_url=e("STRIPE_BASE_URL", cls.stripe_base_url),
            stripe_key=e("STRIPE_API_KEY", cls.stripe_key),
            target=e("WAREHOUSE_TARGET", cls.target),
            duckdb_path=e("DUCKDB_PATH", cls.duckdb_path),
            database_url=e("DATABASE_URL", cls.database_url),
            page_size=int(e("PAGE_SIZE", cls.page_size)),
            max_retries=int(e("MAX_RETRIES", cls.max_retries)),
            backoff_base=float(e("BACKOFF_BASE_SECONDS", cls.backoff_base)),
            lookback_seconds=int(e("LOOKBACK_SECONDS", cls.lookback_seconds)),
            landing_dir=e("LANDING_DIR", cls.landing_dir),
            report_dir=e("REPORT_DIR", cls.report_dir),
            slack_webhook_url=e("SLACK_WEBHOOK_URL", ""),
        )

    def path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else ROOT / p
