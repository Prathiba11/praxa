"""Application settings, loaded once from the environment.

Everything configurable lives here. No other module reads os.environ.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from career_copilot.core.errors import ConfigError

__all__ = ["MODEL_PRICES_USD_PER_1K", "Settings", "get_settings"]

# Rough OpenRouter prices, (prompt, completion) USD per 1k tokens.
# ESTIMATES ONLY - prices change. OpenRouter exposes the real cost per
# generation at /api/v1/generation?id=<id>.
MODEL_PRICES_USD_PER_1K: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.00015, 0.0006),
    "google/gemini-2.0-flash-001": (0.0001, 0.0004),
}

#: The repository root, found from this file rather than from wherever the
#: process happened to start.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    #: Two env files, checked in order, later winning. The absolute one is the
    #: repository's own `.env`; the bare name is whatever directory the process
    #: was started in, kept so a deployment can override without editing files.
    #:
    #: The absolute path is the important half, and it is here because a bare
    #: `".env"` is resolved against the *working directory*. Starting the server
    #: from `frontend/` therefore found no file and pydantic reported
    #: "OPENROUTER_API_KEY field required" - an error that points at a missing
    #: key when the key is present and the directory is wrong. Anchoring the
    #: path to this file means the application starts the same way from
    #: anywhere.
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- LLM ----
    openrouter_api_key: SecretStr = Field(validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL"
    )
    chat_model: str = Field(validation_alias="CC_MODEL")
    fallback_model: str = Field(default="", validation_alias="CC_FALLBACK_MODEL")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, validation_alias="CC_TEMPERATURE")
    max_tokens: int = Field(default=1500, gt=0, validation_alias="CC_MAX_TOKENS")
    request_timeout: int = Field(default=60, gt=0, validation_alias="CC_REQUEST_TIMEOUT")
    max_retries: int = Field(default=3, ge=0, validation_alias="CC_MAX_RETRIES")

    # How long an idle HTTP connection to the provider is kept. httpx's own
    # default is five seconds, which is shorter than a single reranking pass -
    # so on a slow-to-connect machine every call that follows the cross-encoder
    # pays to build a new connection. Sixty seconds covers the gap and stays
    # well inside the idle timeout a server would impose anyway.
    http_keepalive_seconds: float = Field(
        default=60.0, gt=0.0, validation_alias="CC_HTTP_KEEPALIVE_SECONDS"
    )
    # Connect over IPv4 only. Off by default, because a machine on an IPv6-only
    # network needs the opposite. Turn it on when the host resolves to both
    # families and the IPv6 route goes nowhere: Python tries the addresses in
    # order and waits out a TCP timeout on each, where curl races them and
    # never notices. `scripts/diagnose_latency.py --connect` says which case
    # this machine is in.
    force_ipv4: bool = Field(default=False, validation_alias="CC_FORCE_IPV4")

    app_title: str = Field(default="Career Copilot", validation_alias="CC_APP_TITLE")
    app_url: str = Field(default="", validation_alias="CC_APP_URL")

    # ---- embeddings (Phase 1) ----
    embed_provider: str = Field(default="hf", validation_alias="CC_EMBED_PROVIDER")
    embed_model: str = Field(
        default="intfloat/multilingual-e5-base", validation_alias="CC_EMBED_MODEL"
    )

    # Load the embedder and reranker at startup rather than inside the first
    # question. Off for tests and one-shot commands, which must not pay for a
    # transformer they will never call.
    warm_models: bool = Field(default=True, validation_alias="CC_WARM_MODELS")

    # Load the two transformer models from the local cache and never ask the
    # Hugging Face Hub about them. The weights come off disk in about a second;
    # it is the Hub's metadata requests that are slow, and on a machine where
    # outbound HTTPS is inspected they can cost minutes per model. Off by
    # default, because a machine that has never downloaded them must be able
    # to - turn it on once the first run has populated the cache.
    hf_offline: bool = Field(default=False, validation_alias="CC_HF_OFFLINE")

    # ---- reranking (Phase 2) ----
    rerank_enabled: bool = Field(default=True, validation_alias="CC_RERANK_ENABLED")
    rerank_model: str = Field(
        default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", validation_alias="CC_RERANK_MODEL"
    )
    rerank_top_k: int = Field(default=5, gt=0, validation_alias="CC_RERANK_TOP_K")

    # ---- memory ----
    # Durable facts the user states about their own search, extracted after a
    # turn has already been answered and injected into later ones.
    memory_enabled: bool = Field(default=True, validation_alias="CC_MEMORY_ENABLED")

    # ---- retrieval grading ----
    # The grader judges whether what was retrieved can support an answer, and
    # proposes a different query when it cannot.
    grading_enabled: bool = Field(default=True, validation_alias="CC_GRADING_ENABLED")
    # Shared with the memory extractor: both are small classification jobs that
    # run on every turn, and both fail open when the model does not answer.
    #
    # That fail-open behaviour is why this default is a model known to work
    # rather than the cheapest one available. `google/gemini-2.0-flash-001` was
    # the default here and returned 404 for the account actually running this,
    # which silently disabled retrieval grading and memory extraction on every
    # turn for days - the app kept answering, so nothing looked wrong.
    # `scripts/check_models.py` exists to make that visible in one command.
    #
    # A cheaper id can still be set through `CC_GRADER_MODEL`; check it first.
    grader_model: str = Field(default="openai/gpt-4o-mini", validation_alias="CC_GRADER_MODEL")
    # Total retrieval attempts per question, not extra ones. 2 means "search,
    # and if the evidence is poor, search once more" - the loop the agent needs
    # to demonstrate, without a bad question turning into a long wait.
    max_retrieval_rounds: int = Field(
        default=2, ge=1, le=4, validation_alias="CC_MAX_RETRIEVAL_ROUNDS"
    )

    # ---- storage ----
    data_dir: Path = Field(default=Path("./data"), validation_alias="CC_DATA_DIR")
    chroma_dir: Path = Field(default=Path("./data/chroma"), validation_alias="CC_CHROMA_DIR")
    db_path: Path = Field(default=Path("./data/career_copilot.db"), validation_alias="CC_DB_PATH")

    # ---- observability ----
    tracing_enabled: bool = Field(default=False, validation_alias="CC_TRACING_ENABLED")
    langsmith_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="LANGSMITH_API_KEY"
    )
    langsmith_project: str = Field(default="praxa", validation_alias="LANGSMITH_PROJECT")
    # Empty means the SDK's default, which is the US region. EU workspaces
    # (smith.langchain.com URLs beginning "eu.") must set this or every trace
    # is rejected.
    langsmith_endpoint: str = Field(default="", validation_alias="LANGSMITH_ENDPOINT")

    log_level: str = Field(default="INFO", validation_alias="CC_LOG_LEVEL")
    log_json: bool = Field(default=True, validation_alias="CC_LOG_JSON")
    trace_redact_pii: bool = Field(default=True, validation_alias="CC_TRACE_REDACT_PII")

    # ---- cost control ----
    monthly_budget_usd: float = Field(
        default=10.0, ge=0.0, validation_alias="CC_MONTHLY_BUDGET_USD"
    )
    session_budget_usd: float = Field(default=1.0, ge=0.0, validation_alias="CC_SESSION_BUDGET_USD")

    # ---- input limits ----
    max_input_chars: int = Field(default=8000, gt=0, validation_alias="CC_MAX_INPUT_CHARS")
    max_upload_mb: int = Field(default=10, gt=0, validation_alias="CC_MAX_UPLOAD_MB")

    def model_post_init(self, __context: object) -> None:
        """Sanity-check values and make sure the data directories exist."""
        key = self.openrouter_api_key.get_secret_value()
        if not key or key.endswith("replace-me"):
            raise ConfigError("OPENROUTER_API_KEY is missing or still the placeholder")
        if not self.chat_model.strip():
            raise ConfigError("CC_MODEL is empty")
        if self.embed_provider not in {"hf", "openrouter"}:
            raise ConfigError(f"unknown CC_EMBED_PROVIDER {self.embed_provider!r}")

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once. Raises ConfigError with a readable message on failure."""
    try:
        return Settings()  # type: ignore[call-arg]  # values come from the environment
    except PydanticValidationError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc
