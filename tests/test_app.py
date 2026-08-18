from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


def test_health_returns_strict_ok_response_without_extra_routes() -> None:
    from neontof.app import HealthResponse, create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == b'{"status":"ok"}'
    assert response.json() == {"status": "ok"}
    assert HealthResponse(status="ok").model_dump() == {"status": "ok"}

    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    assert [(route.path, tuple(route.methods or ())) for route in routes] == [("/health", ("GET",))]
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
