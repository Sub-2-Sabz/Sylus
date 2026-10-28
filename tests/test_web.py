import pytest
from aiohttp.test_utils import TestClient, TestServer
from sylus.web.server import create_app
from sylus.config import config

@pytest.mark.asyncio
async def test_health_check_get():
    app = create_app()
    client = TestClient(TestServer(app))
    await client.start_server()

    response = await client.get("/health")
    assert response.status == 200
    json_data = await response.json()
    assert "status" in json_data
    assert json_data["status"] == "ok"
    assert "turn" in json_data
    assert "discord" in json_data

    await client.close()

@pytest.mark.asyncio
async def test_health_check_head():
    app = create_app()
    client = TestClient(TestServer(app))
    await client.start_server()

    response = await client.head("/health")
    assert response.status == 200
    text = await response.text()
    assert text == ""

    await client.close()

@pytest.mark.asyncio
async def test_root_get():
    app = create_app()
    client = TestClient(TestServer(app))
    await client.start_server()

    response = await client.get("/")
    assert response.status == 200
    text = await response.text()
    assert "Sylus is running" in text

    await client.close()

@pytest.mark.asyncio
async def test_internal_turn_auth():
    app = create_app()
    client = TestClient(TestServer(app))
    await client.start_server()

    # Unauthorized request without header
    response = await client.post("/internal/turn")
    assert response.status == 401

    await client.close()
