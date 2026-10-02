from dataclasses import dataclass
import os
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path.cwd() / ".env"
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("\"'")
            if key.startswith("AURA_"): os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    ollama_url: str = os.getenv("AURA_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("AURA_OLLAMA_MODEL", "qwen3:8b")
    ollama_keep_alive: str = os.getenv("AURA_OLLAMA_KEEP_ALIVE", "15m")
    ollama_num_ctx: int = int(os.getenv("AURA_OLLAMA_NUM_CTX", "4096"))
    ollama_num_predict: int = int(os.getenv("AURA_OLLAMA_NUM_PREDICT", "256"))
    min_confidence: float = float(os.getenv("AURA_MIN_CONFIDENCE", "0.70"))
    debug: bool = os.getenv("AURA_DEBUG", "0").lower() in {"1", "true", "yes"}

    @property
    def db_path(self) -> Path:
        configured = os.getenv("AURA_DB_PATH")
        if configured:
            return Path(configured).expanduser()
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData/Local"))
        return base / "AURA" / "aura.sqlite3"
