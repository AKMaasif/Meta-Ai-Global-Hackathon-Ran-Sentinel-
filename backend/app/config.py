import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


EFFORTS = ("minimal", "low", "medium", "high", "max")


def _efforts(raw: str) -> dict:
    out = {}
    for part in raw.split(","):
        agent, _, level = part.partition("=")
        if agent.strip() and level.strip().lower() in EFFORTS:
            out[agent.strip()] = level.strip().lower()
    return out


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    api_key: str = field(default_factory=lambda: os.environ.get("MODEL_API_KEY", "").strip())
    base_url: str = field(default_factory=lambda: os.environ.get("META_BASE_URL", "https://api.meta.ai/v1"))
    primary_model: str = field(default_factory=lambda: os.environ.get("PRIMARY_MODEL", "muse-spark-1.3"))
    fallback_model: str = field(default_factory=lambda: os.environ.get("FALLBACK_MODEL", "muse-spark-1.2"))
    reviewer_model: str = field(default_factory=lambda: os.environ.get("REVIEWER_MODEL", "muse-spark-1.2"))
    last_resort_model: str = field(default_factory=lambda: os.environ.get("LAST_RESORT_MODEL", "muse-spark-1.1"))
    wonder_model: str = field(default_factory=lambda: os.environ.get("WONDER_MODEL", "muse-wonder-1.0"))
    vision_model: str = field(default_factory=lambda: os.environ.get("VISION_MODEL", "muse-spark-1.3"))
    sam_model: str = field(default_factory=lambda: os.environ.get("SAM_MODEL", "sam-3.1"))
    voice_model: str = field(default_factory=lambda: os.environ.get("VOICE_MODEL", "muse-voice-transcribe-1.0"))
    reasoning_effort: str = field(default_factory=lambda: os.environ.get("REASONING_EFFORT", "").strip().lower())
    agent_effort: dict = field(default_factory=lambda: _efforts(os.environ.get("AGENT_EFFORT", "")))
    fireworks_api_key: str = field(default_factory=lambda: os.environ.get("FIREWORKS_API_KEY", "").strip())
    fireworks_base_url: str = field(default_factory=lambda: os.environ.get("FIREWORKS_BASE_URL", "https://us.api.fireworks.ai/inference/v1"))
    fireworks_model: str = field(default_factory=lambda: os.environ.get("FIREWORKS_MODEL", "accounts/fireworks/models/muse-spark-open"))
    assistant_model: str = field(default_factory=lambda: os.environ.get("ASSISTANT_MODEL", "muse-spark-1.3"))
    max_tokens: int = field(default_factory=lambda: _int("MODEL_MAX_TOKENS", 4000))
    model_timeout: float = field(default_factory=lambda: _float("MODEL_TIMEOUT_SECONDS", 60))
    maveric_url: str = field(default_factory=lambda: os.environ.get("MAVERIC_URL", "").strip())
    maveric_model: str = field(default_factory=lambda: os.environ.get("MAVERIC_MODEL", "ran-sentinel-seattle").strip())
    maveric_timeout: float = field(default_factory=lambda: _float("MAVERIC_TIMEOUT_SECONDS", 90))
    tick_seconds: float = field(default_factory=lambda: _float("SIM_TICK_SECONDS", 3))
    ops_email: str = field(default_factory=lambda: os.environ.get("OPS_EMAIL", "ops@northstar.demo"))
    ops_password: str = field(default_factory=lambda: os.environ.get("OPS_PASSWORD", ""))
    customer_email: str = field(default_factory=lambda: os.environ.get("CUSTOMER_EMAIL", "customer@northstar.demo"))
    customer_password: str = field(default_factory=lambda: os.environ.get("CUSTOMER_PASSWORD", ""))
    fcc_users_per_site: int = field(default_factory=lambda: _int("FCC_USERS_PER_SITE", 1500))
    db_path: Path = ROOT / "data" / "sentinel.db"

    max_tool_calls: int = 12
    max_evidence_rounds: int = 2
    max_plan_retries: int = 2
    max_verify_refusals: int = 3
    one_tool_per_turn: bool = field(default_factory=lambda: os.environ.get("ONE_TOOL_PER_TURN", "1") != "0")
    max_repair_attempts: int = 1
    max_reopen: int = 1
    monitor_ticks: int = 4

    @property
    def meta_enabled(self) -> bool:
        return bool(self.api_key)

    def effort_for(self, agent: str) -> str | None:
        e = self.agent_effort.get(agent) or self.reasoning_effort
        return e if e in EFFORTS else None


settings = Settings()
