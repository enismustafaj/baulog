import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-05-20")
PROPERTIES_DIR: str = os.getenv("BAULOG_PROPERTIES_DIR", "data/properties")
