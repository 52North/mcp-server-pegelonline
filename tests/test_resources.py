"""Smoke tests for the MCP resources against mocked upstream APIs."""

from html.parser import HTMLParser

import httpx
import pytest

from conftest import SEARCH_URL, WATERS_URL, all_stations, load_fixture
from pegelonline_mcp.resources import CHART_UI_URI, MAP_UI_URI


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


async def test_list_water_bodies_without_shortname(client, respx_mock):
    waters = load_fixture("waters")
    del waters[0]["shortname"]
    respx_mock.get(WATERS_URL).respond(json=waters)

    text = await read_text(client, "water-bodies://list")

    assert text.splitlines()[:2] == ["ALLER", "ALTE MAAS (ALTE_MAAS)"]


async def test_list_states(client, respx_mock, snapshot_json):
    route = respx_mock.get(SEARCH_URL).respond(json=all_stations())

    text = await read_text(client, "states://list")

    assert text.splitlines() == ["Hamburg", "Nordrhein-Westfalen"]
    assert text == snapshot_json

    await read_text(client, "states://list")
    assert route.call_count == 1


async def test_list_states_does_not_cache_empty_response(client, respx_mock):
    route = respx_mock.get(SEARCH_URL).mock(
        side_effect=[
            httpx.Response(200, json={"stations": []}),
            httpx.Response(200, json=all_stations()),
        ]
    )

    assert await read_text(client, "states://list") == ""
    # Once upstream recovers, the next read fetches again instead of
    # serving the empty result from the cache
    text = await read_text(client, "states://list")

    assert text.splitlines() == ["Hamburg", "Nordrhein-Westfalen"]
    assert route.call_count == 2


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (
            "agencies://list",
            [
                "HAMBURG PORT AUTHORITY", "STANDORT DUISBURG", "STANDORT KÖLN",
                "STANDORT LAUENBURG",
            ],
        ),
        ("catchment-areas://list", ["Elbe", "Rhein"]),
    ],
)
async def test_list_station_field_values(client, respx_mock, uri, expected):
    respx_mock.get(SEARCH_URL).respond(json=all_stations())

    text = await read_text(client, uri)

    assert text.splitlines() == expected


async def test_list_catchment_areas_skips_stations_without_one(client, respx_mock):
    # Recorded land=Sachsen response: one station has no einzugsgebiet
    respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_sachsen"))

    text = await read_text(client, "catchment-areas://list")

    assert text.splitlines() == ["Aller", "Elbe"]


async def test_lists_share_one_station_download(client, respx_mock):
    route = respx_mock.get(SEARCH_URL).respond(json=all_stations())

    for uri in ("states://list", "agencies://list", "catchment-areas://list"):
        assert await read_text(client, uri)

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


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Sachsen", ["SCHÖNA", "PIRNA"]),
        ("sachsen", ["SCHÖNA", "PIRNA"]),
        ("Saxony", ["SCHÖNA", "PIRNA"]),
        ("Lower%20Saxony", ["AHLDEN"]),
    ],
)
async def test_list_stations_in_state_keeps_only_that_state(
    client, respx_mock, state, expected
):
    # Recorded land=Sachsen response: the dict API matches substrings, so it
    # also returns stations in Niedersachsen and Sachsen-Anhalt.
    respx_mock.get(SEARCH_URL).respond(json=load_fixture("search_sachsen"))

    text = await read_text(client, f"states://{state}/stations")

    assert [line.split(" (")[0] for line in text.splitlines()] == expected


async def test_stations_map_ui(client):
    text = await read_text(client, MAP_UI_URI)

    assert "<html" in text.lower()
    assert "leaflet" in text.lower()


async def test_measurements_chart_ui(client):
    text = await read_text(client, CHART_UI_URI)

    assert "<html" in text.lower()


async def test_measurements_chart_ui_may_load_from_unpkg_only(client):
    resources = {str(r.uri): r for r in await client.list_resources()}

    assert resources[CHART_UI_URI].meta["ui"]["csp"] == {
        "resourceDomains": ["https://unpkg.com"]
    }


class ExternalAssets(HTMLParser):
    """Collects the attributes of external scripts and stylesheets."""

    def __init__(self) -> None:
        super().__init__()
        self.assets: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        url = attributes.get("src") if tag == "script" else attributes.get("href")
        is_asset = tag == "script" or (
            tag == "link" and attributes.get("rel") == "stylesheet"
        )
        if is_asset and url and url.startswith(("http://", "https://")):
            self.assets.append(attributes)


async def test_stations_map_external_assets_are_pinned(client):
    # Subresource integrity: the browser refuses a CDN file whose hash differs
    parser = ExternalAssets()
    parser.feed(await read_text(client, MAP_UI_URI))

    assert parser.assets
    for asset in parser.assets:
        assert (asset.get("integrity") or "").startswith(
            ("sha256-", "sha384-", "sha512-")
        ), asset
        assert "crossorigin" in asset, asset
