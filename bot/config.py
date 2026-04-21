import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
BOOKING_CONTACT_ID = int(os.environ["BOOKING_CONTACT_ID"]) if os.environ.get("BOOKING_CONTACT_ID") else None
BOOKING_CONTACT_FALLBACK_URL = os.environ.get("BOOKING_CONTACT_FALLBACK_URL", "https://t.me/artem_zubr")

DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "bot")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "bot")
DB_NAME = os.environ.get("DB_NAME", "bot")

DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
