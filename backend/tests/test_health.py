"""Health endpoint contract test."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app.main import create_app


async def request_health() -> Response:
    """Send an HTTP request directly to the ASGI application."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/health")


def test_health() -> None:
    """The application serves the expected health response as JSON."""
    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
