"""Smoke tests for the MCP resources against mocked upstream APIs."""

from conftest import SEARCH_URL, WATERS_URL, load_fixture
from server import MAP_UI_URI


def all_stations() -> dict:
    """Unfiltered /search response spanning several federal states."""
    rhein = load_fixture("search_rhein")
    hamburg = load_fixture("search_hamburg")
    return {
        key: rhein[key] + hamburg[key]
        for key in ("mqtttopics", "pegelonlinelinks", "stations")
    }


async def read_text(client, uri: str) -> str:
    contents = await client.read_resource(uri)
    return contents[0].text


async def test_list_water_bodies(client, respx_mock, snapshot_json):
    route = respx_mock.get(WATERS_URL).respond(json=load_fixture("waters"))

    text = await read_text(client, "water-bodies://list")
    assert text == snapshot_json

    # The second read is served from the cache
    assert await read_text(client, "water-bodies://list") == text
    assert route.call_count == 1


async def test_list_states(client, respx_mock, snapshot_json):
    route = respx_mock.get(SEARCH_URL).respond(json=all_stations())

    text = await read_text(client, "states://list")

    assert text.splitlines() == ["Hamburg", "Nordrhein-Westfalen"]
    assert text == snapshot_json

    await read_text(client, "states://list")
    assert route.call_count == 1


async def test_list_stations_in_state(client, respx_mock, snapshot_json):
    route = respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_hamburg"))

    text = await read_text(client, "states://Hamburg/stations")

    assert route.calls.last.request.url.params["land"] == "Hamburg"
    assert text == snapshot_json


async def test_list_stations_in_state_without_water(client, respx_mock):
    data = load_fixture("search_hamburg")
    del data["stations"][0]["water"]
    respx_mock.get(SEARCH_URL).respond(json=data)

    text = await read_text(client, "states://Hamburg/stations")

    lines = text.splitlines()
    assert len(lines) == 3
    assert lines[0] == "ALTENGAMME (UUID: 2ee12b9a-f7fd-4856-82b9-6bdd850c2bba)"


async def test_stations_map_ui(client):
    text = await read_text(client, MAP_UI_URI)

    assert "<html" in text.lower()
    assert "leaflet" in text.lower()
