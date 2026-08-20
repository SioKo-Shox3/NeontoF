"""起動設定の検証済み契約を提供する。秘密・DB・外部モデル実装は扱わない。"""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field

from neontof.contracts.base import ContractModel

__all__ = ("ContractModel", "ServerOptions", "load_server_options")


class ServerOptions(ContractModel):
    """Uvicornへ渡す、single-worker起動設定。"""

    host: Annotated[str, Field(min_length=1)]
    port: Annotated[int, Field(ge=1, le=65535)]
    workers: Literal[1] = 1


def _parse_integer(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key, str(default))
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{key} must be an integer") from error


def load_server_options(env: Mapping[str, str]) -> ServerOptions:
    """許可された環境変数だけを読み、検証済みの起動設定を返す。"""

    host = env.get("NEONTOF_HOST", "127.0.0.1")
    port = _parse_integer(env, "NEONTOF_PORT", 8765)
    workers = _parse_integer(env, "NEONTOF_WORKERS", 1)
    if workers != 1:
        raise ValueError("NEONTOF_WORKERS must be 1")
    return ServerOptions(host=host, port=port, workers=1)
