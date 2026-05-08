import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
    GROQ_API_KEY: str = os.getenv("TELEGRAM_BOT_GROQ", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    DB_PATH: str = os.getenv("DB_PATH", "/data/langbot.db")
    DAILY_SEND_TIME: str = os.getenv("DAILY_SEND_TIME", "07:00")  # UTC
    MYMEMORY_API_KEY: str = os.getenv("MYMEMORY_API_KEY", "")  # Optional, increases rate limit
    YOUTUBE_COOKIES: str = os.getenv("YOUTUBE_COOKIES", "")  # Path to cookies.txt
    YOUTUBE_PROXIES: str = os.getenv("YOUTUBE_PROXIES", "")  # JSON string of proxies
    USE_LLM_EXTRACTION: bool = os.getenv("USE_LLM_EXTRACTION", "false").lower() == "true"
