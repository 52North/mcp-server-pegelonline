"""Typed tool responses; FastMCP publishes them as each tool's output schema.

The server validates every response against that schema, so a field taken
from upstream is nullable: the APIs omit e.g. coordinates, river kilometer or
district for some stations, and a stricter type would fail the whole call.
Only fields computed here or echoing an argument are not.
"""

from typing import Literal, NotRequired, TypedDict


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


class SearchValue(TypedDict):
    """Value of a search_stations filter."""

    value: str
    # Only where value is a short name (gewaesser, parameter): the names behind it
    longnames: NotRequired[list[str]]
    stations: int


class SearchValues(TypedDict):
    """Values of one search_stations filter."""

    field: str
    values: list[SearchValue]


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


class CharacteristicValue(TypedDict):
    """Characteristic value of a timeseries, e.g. mean high water (MHW)."""

    shortname: str | None
    longname: str | None
    value: float | None
    unit: str | None
    # Fixed values such as HSW or the flood marks apply from a date on
    valid_from: str | None
    # Statistics such as MNW, MW and MHW cover a period of years
    timespan_start: str | None
    timespan_end: str | None
    # Extremes such as NNW and HHW: the dates, or only years, they occurred on
    occurrences: list[str] | None


class CurrentMeasurement(TypedDict):
    """Current measurement of one parameter with its two states."""

    timestamp: str | None
    value: float | None
    state_mnw_mhw: str | None
    state_nsw_hsw: str | None


class CharacteristicValues(TypedDict):
    """Characteristic values of one parameter, with its current measurement."""

    uuid: str
    parameter: str
    unit: str | None
    comment: str | None
    current: CurrentMeasurement | None
    characteristic_values: list[CharacteristicValue]


class ComparedStation(TypedDict):
    """Current measurement of one parameter at one of the compared stations."""

    uuid: str | None
    station: str | None
    water: str | None
    km: float | None
    unit: str | None
    gaugeZero: GaugeZero | None
    comment: str | None
    current: CurrentMeasurement | None
    # Short name to value, e.g. {"MNW": 114.0, "MW": 297.0}
    characteristic_values: dict[str, float | None]


class StationComparison(TypedDict):
    """Current measurements of one parameter at several stations."""

    parameter: str
    stations: list[ComparedStation]
    # Requested ids the API did not return
    not_found: list[str]


class Measurement(TypedDict):
    """Single measurement as the official API returns it."""

    timestamp: str | None
    value: float | None


class RecentMeasurements(TypedDict):
    """Recent measurements of one parameter, most recent first."""

    uuid: str
    parameter: str
    unit: str | None
    comment: str | None
    measurements: list[Measurement]


class HistorySummary(TypedDict):
    """Statistics of all values in a time span; without values, all but count are None."""

    count: int
    # None if the interval is unknown or values lie off its grid
    missing: int | None
    first: Measurement | None
    last: Measurement | None
    min: Measurement | None
    max: Measurement | None
    mean: float | None


class HistoryRows(TypedDict):
    """Values of a time span in rows, oldest first."""

    resolution: Literal["raw", "hour", "day"]
    truncated: bool
    columns: list[str]
    rows: dict[str, list[float | None]]


class MeasurementHistory(HistoryRows):
    """Measurements of one parameter over a time span."""

    uuid: str
    parameter: str
    unit: str | None
    comment: str | None
    interval_minutes: int | None
    summary: HistorySummary
