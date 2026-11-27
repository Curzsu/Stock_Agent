"""Keep the provider settings consistent across all agents in one research task."""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NamedTuple


API_ENV_KEYS = (
    "OPENAI_COMPATIBLE_API_KEY",
    "OPENAI_COMPATIBLE_BASE_URL",
    "OPENAI_COMPATIBLE_MODEL",
)


class ApiSettings(NamedTuple):
    api_key: str
    base_url: str
    model: str


_analysis_settings: ContextVar[ApiSettings | None] = ContextVar("analysis_api_settings", default=None)
_summary_mode: ContextVar[str | None] = ContextVar("analysis_summary_mode", default=None)


def current_api_settings() -> ApiSettings:
    settings = _analysis_settings.get()
    if settings is not None:
        return settings
    return ApiSettings(*(os.getenv(key, "") for key in API_ENV_KEYS))


def current_summary_mode() -> str:
    return _summary_mode.get() or os.getenv("USE_LOCAL_MODEL", "api").lower()


@contextmanager
def use_api_settings(settings: ApiSettings, *, summary_mode: str | None = None):
    token = _analysis_settings.set(settings)
    mode_token = _summary_mode.set(summary_mode)
    try:
        yield
    finally:
        _summary_mode.reset(mode_token)
        _analysis_settings.reset(token)
