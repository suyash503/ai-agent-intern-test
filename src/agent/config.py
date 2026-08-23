import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    temperature: float
    top_k: int
    kb_dir: Path
    orders_path: Path
    log_dir: Path
    min_interval: float
    max_history_turns: int
    max_tool_calls: int


def load_settings() -> Settings:
    return Settings(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        model=os.getenv("LLM_MODEL", "gemini-3.6-flash"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        top_k=int(os.getenv("RETRIEVAL_TOP_K", "6")),
        kb_dir=ROOT / "knowledge-base",
        orders_path=ROOT / "data" / "orders.json",
        log_dir=ROOT / os.getenv("LOG_DIR", "logs"),
        min_interval=float(os.getenv("LLM_MIN_INTERVAL_SECONDS", "0")),
        max_history_turns=6,
        max_tool_calls=3,
    )


settings = load_settings()
