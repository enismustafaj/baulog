import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Absolute path to the project root (one level above this file's directory)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-05-20")
PROPERTIES_DIR: str = os.getenv(
    "BAULOG_PROPERTIES_DIR",
    str(PROJECT_ROOT / "data" / "properties"),
)
ADJUSTMENTS_DB: Path = PROJECT_ROOT / "data" / "adjustments.db"
SESSIONS_DIR: Path = PROJECT_ROOT / ".baulog" / "entire-sessions"
