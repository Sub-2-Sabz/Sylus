import pytest
from aiohttp.test_utils import TestClient, TestServer
from sylus.web.server import create_app

@pytest.mark.asyncio
async def test_health_check_get():
    app = create_app()
    client = TestClient(TestServer(app))
    await client.start_server()

    response = await client.get("/health")
    assert response.status == 200
    json_data = await response.json()
    assert json_data == {"status": "ok"}

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
    json_data = await response.json()
    assert json_data == {"status": "ok", "app": "sylus"}

    await client.close()
