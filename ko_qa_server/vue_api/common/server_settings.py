import os
from dataclasses import dataclass
from typing import Mapping, Optional


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _read_bool(value: Optional[str], *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean environment value: {value!r}")


def _read_port(value: Optional[str], *, default: int) -> int:
    if value is None or not str(value).strip():
        return default
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"Port must be between 1 and 65535: {port}")
    return port


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
    debug: bool
    reload: bool


def load_server_settings(
    environment: Optional[Mapping[str, str]] = None,
) -> ServerSettings:
    env = os.environ if environment is None else environment
    return ServerSettings(
        host=str(env.get("KO_QA_HOST", "0.0.0.0")).strip() or "0.0.0.0",
        port=_read_port(env.get("KO_QA_PORT"), default=8989),
        debug=_read_bool(env.get("KO_QA_DEBUG"), default=False),
        reload=_read_bool(env.get("KO_QA_RELOAD"), default=False),
    )
