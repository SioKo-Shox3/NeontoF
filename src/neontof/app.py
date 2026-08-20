"""ゲーム状態を所有しない、最小のFastAPI HTTP adapterを提供する。"""

from typing import Literal

from fastapi import FastAPI

from neontof.contracts.base import ContractModel

__all__ = ("ContractModel", "HealthResponse", "create_app")


class HealthResponse(ContractModel):
    """プロセスがHTTP応答可能であることだけを表す。"""

    status: Literal["ok"]


def create_app() -> FastAPI:
    """GET /healthだけを公開するFastAPI applicationを生成する。"""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app
