"""Typed tool responses; FastMCP publishes them as each tool's output schema.

The server validates every response against that schema, so a field taken
from upstream is nullable: the APIs omit e.g. coordinates, river kilometer or
district for some stations, and a stricter type would fail the whole call.
Only fields computed here or echoing an argument are not.
"""

from typing import NotRequired, TypedDict


class ParameterInfo(TypedDict):
    """Observation parameter (timeseries) of a station."""

    shortname: str | None
    longname: str | None
    unit: str | None


class StationSummary(TypedDict):
    """Compact station description."""

    uuid: str | None
    shortname: str | None
    longname: str | None
    agency: str | None
    water: str | None
    latitude: float | None
    longitude: float | None
    mqtttopic: str | None
    parameters: list[ParameterInfo]


class FoundStation(StationSummary):
    """Station found by search_stations."""

    # The fields the text filters match on, so the model can tell which
    # substring matches it actually wanted
    country: str | None
    land: str | None
    kreis: str | None
    einzugsgebiet: str | None


class NearbyStation(StationSummary):
    """Station within the search radius."""

    distance_km: float


class SearchResult(TypedDict):
    """Stations matching the search filters."""

    total_matches: int
    returned: int
    truncated: bool
    stations: list[FoundStation]


class NearbyStations(TypedDict):
    """Stations around a coordinate, nearest first."""

    total_matches: int
    returned: int
    truncated: bool
    stations: list[NearbyStation]


class MapCenter(TypedDict):
    """Center of the search radius."""

    latitude: float
    longitude: float


class StationsMap(NearbyStations):
    """Data the stations map renders."""

    center: MapCenter
    radius_km: float


class GaugeZero(TypedDict):
    """Gauge zero (Pegelnullpunkt) of a water level timeseries."""

    unit: str | None
    value: float | None
    validFrom: str | None


class StationParameter(ParameterInfo):
    """Observation parameter with its metadata."""

    equidistance_minutes: int | None
    gaugeZero: GaugeZero | None
    comment: str | None


class StationInfo(TypedDict):
    """Static metadata of a station."""

    uuid: str | None
    number: str | None
    shortname: str | None
    longname: str | None
    agency: str | None
    longitude: float | None
    latitude: float | None
    km: float | None
    water: str | None
    parameters: list[StationParameter]


class LatestMeasurement(TypedDict):
    """Latest measurement of one parameter."""

    parameter: str | None
    shortname: str | None
    value: float | None
    unit: str | None
    timestamp: str | None
    state_mnw_mhw: str | None
    state_nsw_hsw: str | None
    comment: str | None


class LatestMeasurements(TypedDict):
    """Latest measurement of every parameter of a station."""

    station: str | None
    water: str | None
    measurements: list[LatestMeasurement]


class Measurement(TypedDict):
    """Single measurement as the official API returns it."""

    timestamp: str | None
    value: float | None


class SpanCounts(TypedDict, total=False):
    """How many values a time span held and returned."""

    total_matches: int
    returned: int
    truncated: bool


class RecentMeasurements(TypedDict):
    """Recent measurements of one parameter, most recent first."""

    uuid: str
    parameter: str
    unit: str | None
    comment: str | None
    total_matches: NotRequired[int]
    returned: NotRequired[int]
    truncated: NotRequired[bool]
    measurements: list[Measurement]
