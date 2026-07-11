import os
from enum import Enum

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Evo2Mode(str, Enum):
    LOCAL = "local"
    NIM_API = "nim_api"
    MOCK = "mock"


class StructureMode(str, Enum):
    ALPHAFOLD_API = "alphafold_api"
    COLABFOLD = "colabfold"
    ESMFOLD = "esmfold"
    MOCK = "mock"


class SessionStoreMode(str, Enum):
    MEMORY = "memory"
    REDIS = "redis"


class Settings(BaseSettings):
    # Evo2 sequence model
    evo2_mode: Evo2Mode = Evo2Mode.MOCK
    evo2_nim_api_key: str = ""
    evo2_key: str = ""
    evo2_nim_api_url: str = "https://health.api.nvidia.com/v1/biology/arc/evo2-40b/generate"
    evo2_model_path: str = "arcinstitute/evo2_7b"

    # Structure prediction
    structure_mode: StructureMode = StructureMode.MOCK
    alphafold_api_key: str = ""

    # NCBI E-utilities
    ncbi_api_key: str = ""
    ncbi_email: str = ""
    ncbi_tool: str = "evo"

    # --- LLM layer (OpenRouter — single gateway for every model call) ---
    # All intent parsing, explanation, and agent reasoning route through
    # OpenRouter's OpenAI-compatible API. Swap providers by changing LLM_MODEL.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"
    llm_fast_model: str = "openai/gpt-4o-mini"

    # Legacy provider keys are still read (so existing .env files keep working)
    # but are no longer used for live calls — OpenRouter supersedes them.
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Infrastructure
    redis_url: str = "redis://localhost:6379/0"
    session_store_mode: SessionStoreMode = SessionStoreMode.MEMORY
    session_ttl_seconds: int = 7200
    session_key_prefix: str = "evo:session"
    celery_broker: str = "redis://localhost:6379/1"
    frontend_url: str = "http://localhost:3000"
    port: int = 8000

    # Hugging Face
    hugging_face_token: str = ""

    # Allow extra env vars (teammates may add keys we don't own)
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Convenience aliases
OPENROUTER_API_KEY = settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")

NCBI_API_KEY = settings.ncbi_api_key
if not NCBI_API_KEY:
    NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

NCBI_EMAIL = settings.ncbi_email
if not NCBI_EMAIL:
    NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "")

NCBI_TOOL = settings.ncbi_tool or os.environ.get("NCBI_TOOL", "evo")
