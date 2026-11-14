"""App settings, read once from the repo-root .env (pydantic-settings).

Every process (API, agent, Celery, scripts) imports `settings` from here.
Relative paths in .env (data files, service-account JSON) are resolved from the repo root.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]   # .../backend
REPO_ROOT = BACKEND_DIR.parent                       # .../Voice-Agent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # LiveKit
    LIVEKIT_URL: str
    LIVEKIT_API_KEY: str
    LIVEKIT_API_SECRET: str
    AGENT_NAME: str = "amrutha"

    # Sarvam
    SARVAM_API_KEY: str
    STT_MODEL: str = "saaras:v4"
    STT_CLASS: str = "classic"            # classic | realtime
    STT_MODE: str = "transcribe"
    TTS_MODEL: str = "bulbul:v4-flash"
    TTS_SAMPLE_RATE: int = 16000
    SARVAM_DICT_ID: str = ""
    LIVE_LLM: str = "sarvam-105b-conversations"
    LIVE_LLM_REASONING: str = ""          # empty = do not send (conversations model rejects "none")
    LIVE_LLM_MAX_TOKENS: int = 250
    LIVE_LLM_FALLBACK: str = ""
    TRANSLATE_MODEL: str = "sarvam-translate:v1"

    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_JWT_SECRET: str = ""
    DATABASE_URL: str
    KB_BUCKET: str = "kb-docs"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Post-call + evals
    GEMINI_API_KEY: str = ""
    EXTRACT_LLM: str = "gemini-3.8-flash"
    GROQ_API_KEY: str = ""
    JUDGE_LLM: str = ""
    SIM_LLM: str = ""

    # Embeddings / search
    EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBED_DIM: int = 384
    SEARCH_MODE: str = "hybrid"           # hybrid | keyword

    # Google
    GOOGLE_SERVICE_ACCOUNT_JSON: str = "./secrets/google-service-account.json"
    GOOGLE_SHEET_ID: str = ""
    GOOGLE_CALENDAR_ID: str = ""

    # App
    TENANT_ID: str = "00000000-0000-0000-0000-000000000001"
    TIMEZONE: str = "Asia/Kolkata"
    PROMPT_VERSION: str = "v1"
    FRONTEND_URL: str = "http://localhost:5173"
    PRICING_FILE: str = "./backend/data/amrith_sagar_pricing.json"
    AREAS_FILE: str = "./backend/data/areas.json"
    CAMPAIGN_TYPES_FILE: str = "./backend/data/campaign_types.json"

    # Call guardrails / limits
    RING_TIMEOUT_SECONDS: int = 30
    RETRY_DELAY_MINUTES: int = 30
    WAIT_FOR_PARTICIPANT_SECONDS: int = 45
    INBOUND_RATE_LIMIT_PER_IP: int = 3
    INBOUND_MAX_CONCURRENT: int = 2

    # Razorpay (test mode)
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # ---- helpers -------------------------------------------------------------
    def path(self, value: str) -> Path:
        """Resolve a path from .env relative to the repo root."""
        p = Path(value)
        if p.is_absolute():
            return p
        for base in (REPO_ROOT, BACKEND_DIR):   # tolerate old ./data/... paths
            candidate = (base / p).resolve()
            if candidate.exists():
                return candidate
        return (REPO_ROOT / p).resolve()

    @property
    def pricing_path(self) -> Path:
        return self.path(self.PRICING_FILE)

    @property
    def areas_path(self) -> Path:
        return self.path(self.AREAS_FILE)

    @property
    def campaign_types_path(self) -> Path:
        return self.path(self.CAMPAIGN_TYPES_FILE)

    @property
    def google_sa_path(self) -> Path:
        return self.path(self.GOOGLE_SERVICE_ACCOUNT_JSON)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.FRONTEND_URL.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
