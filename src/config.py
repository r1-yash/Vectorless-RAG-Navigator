"""Application configuration loaded dynamically from environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "navigator.db"))
DATABASE_URL = f"sqlite:///{DATABASE_PATH.resolve()}"


# Explicitly load .env file from project root
env_file = BASE_DIR / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=env_file, override=True)
else:
    load_dotenv(override=True)


def get_groq_api_key() -> str:
    """Dynamically fetch GROQ_API_KEY from environment."""
    return os.getenv("GROQ_API_KEY", "").strip()


def get_groq_model() -> str:
    """Dynamically fetch GROQ_MODEL from environment."""
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip().strip('"').strip("'")
    if not model:
        return "openai/gpt-oss-120b"
    return model


GROQ_API_KEY = get_groq_api_key()
GROQ_MODEL = get_groq_model()

# Throttling to respect Groq rate limits during burst tree construction
BATCH_INGESTION_DELAY_SECONDS = float(os.getenv("BATCH_INGESTION_DELAY_SECONDS", "0.5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
