import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Single source of truth for secrets: the repo-root .env (one dir above backend/).
# Fall back to a backend-local .env if someone keeps one there, then to the
# process environment (used by Docker / CI). Root wins so keys live in one place.
_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"
_BACKEND_ENV = Path(__file__).resolve().parent / ".env"
_ENV_FILE = _ROOT_ENV if _ROOT_ENV.exists() else _BACKEND_ENV
load_dotenv(_ENV_FILE)


class Evo2Mode(str, Enum):
    LOCAL = "local"
    NIM_API = "nim_api"
    MOCK = "mock"


class StructureMode(str, Enum):
    ALPHAFOLD_API = "alphafold_api"
    COLABFOLD = "colabfold"
    ESMFOLD = "esmfold"


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
    structure_mode: StructureMode = StructureMode.ESMFOLD
    alphafold_api_key: str = ""

    # NCBI E-utilities
    ncbi_api_key: str = ""
    ncbi_email: str = ""
    ncbi_tool: str = "evo"

    # --- LLM layer (OpenRouter - single gateway for every model call) ---
    # All intent parsing, explanation, and agent reasoning route through
    # OpenRouter's OpenAI-compatible API. Swap providers by changing LLM_MODEL.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"
    llm_fast_model: str = "openai/gpt-4o-mini"

    # Legacy provider keys are still read (so existing .env files keep working).
    # anthropic_api_key / openai_api_key are no longer used for live calls -
    # OpenRouter supersedes them for chat/reasoning. gemini_api_key IS used,
    # but for a narrower job: services/evidence_synthesis.py's literature
    # detail summaries (not chat/reasoning, so it doesn't go through llm.py).
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
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

    # --- Durable persistence (MongoDB Atlas) ---
    # Redis stays the hot store (fast, TTL'd). Mongo is the durable store for
    # prompt/design-run history so a session survives restarts and the reprompt
    # feature can build on prior runs. Persistence is OPTIONAL: if no URI is set
    # or Atlas is unreachable, the app runs exactly as before (Redis-only) and
    # every persistence call becomes a logged no-op - never a request failure.
    mongodb_uri: str = ""
    mongodb_db_name: str = "evo"
    # Fail-fast connection budget so a bad/blocked URI never hangs startup.
    mongodb_connect_timeout_ms: int = 5000

    # --- Semantic vector search (research literature) ---
    # Powers /api/literature/search. HYBRID embeddings: when an embedding API
    # key is set, real embeddings are used; otherwise a deterministic local
    # feature-hashing embedder keeps search working offline (lower quality).
    # Both backends emit vectors of EMBEDDING_DIM so ONE Atlas vector index
    # fits either - but don't mix backends in one populated index (re-index if
    # you switch). embedding_api_key falls back to the legacy openai_api_key.
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 256
    # Name of the MongoDB Atlas Vector Search index over the `literature`
    # collection. Provision it on the cluster to enable $vectorSearch; without
    # it, search transparently falls back to in-memory cosine similarity.
    vector_index_name: str = "literature_vector_index"

    # Hugging Face
    hugging_face_token: str = ""

    # Allow extra env vars (teammates may add keys we don't own)
    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}


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
