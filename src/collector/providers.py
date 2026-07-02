"""Routing provider clients used by the RouteStats collector."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode
from urllib.request import urlopen


class RoutingProviderError(RuntimeError):
    """Raised when a routing provider cannot return a usable travel time."""


@dataclass(frozen=True)
class RoutePoint:
    """A geographic point used as a route origin or destination."""

    latitude: float
    longitude: float

    @classmethod
    def from_config(cls, value: Mapping[str, Any]) -> "RoutePoint":
        return cls(latitude=float(value["latitude"]), longitude=float(value["longitude"]))

    def as_coordinate_pair(self) -> str:
        return f"{self.latitude},{self.longitude}"


@dataclass(frozen=True)
class RouteTravelTime:
    """Normalized travel-time response from a routing provider."""

    duration_seconds: int
    distance_meters: int
    provider: str
    status: str
    raw_response: Mapping[str, Any]


class RoutingProvider(Protocol):
    """Protocol implemented by routing providers."""

    provider_name: str

    def get_travel_time(self, route: Mapping[str, Any]) -> RouteTravelTime:
        """Return a normalized travel-time estimate for a configured route."""


def _read_json_url(url: str, timeout_seconds: int) -> Mapping[str, Any]:
    with urlopen(url, timeout=timeout_seconds) as response:  # nosec: provider URLs are fixed
        payload = response.read().decode("utf-8")
    return json.loads(payload)


class TomTomRoutingProvider:
    """TomTom Routing API client for one origin-destination route."""

    provider_name = "tomtom_routing"
    endpoint = "https://api.tomtom.com/routing/1/calculateRoute"

    def __init__(self, api_key: str, timeout_seconds: int = 30) -> None:
        if not api_key:
            raise RoutingProviderError("TomTom Routing API key is required.")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def get_travel_time(self, route: Mapping[str, Any]) -> RouteTravelTime:
        origin = RoutePoint.from_config(route["origin"])
        destination = RoutePoint.from_config(route["destination"])
        provider_options = dict(route.get("provider", {}).get("options", {}) or {})

        query = {
            "key": self.api_key,
            "traffic": "true",
            "routeType": "fastest",
            "travelMode": _tomtom_travel_mode(route.get("travel_mode", "driving")),
        }
        query.update(provider_options)

        response = self._request(origin, destination, _normalize_query_values(query))
        try:
            summary = response["routes"][0]["summary"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RoutingProviderError("TomTom Routing API response has no route summary.") from exc

        try:
            duration_seconds = int(summary["travelTimeInSeconds"])
            distance_meters = int(summary["lengthInMeters"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RoutingProviderError("TomTom Routing API response is missing duration or distance.") from exc

        return RouteTravelTime(
            duration_seconds=duration_seconds,
            distance_meters=distance_meters,
            provider=self.provider_name,
            status="OK",
            raw_response=response,
        )

    def _request(
        self,
        origin: RoutePoint,
        destination: RoutePoint,
        query: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        locations = f"{origin.as_coordinate_pair()}:{destination.as_coordinate_pair()}"
        url = f"{self.endpoint}/{locations}/json?{urlencode(query)}"
        return _read_json_url(url, self.timeout_seconds)


class GoogleDistanceMatrixProvider:
    """Google Distance Matrix API client for one origin-destination route."""

    provider_name = "google_maps_distance_matrix"
    endpoint = "https://maps.googleapis.com/maps/api/distancematrix/json"

    def __init__(self, api_key: str, timeout_seconds: int = 30) -> None:
        if not api_key:
            raise RoutingProviderError("Google Distance Matrix API key is required.")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def get_travel_time(self, route: Mapping[str, Any]) -> RouteTravelTime:
        origin = RoutePoint.from_config(route["origin"])
        destination = RoutePoint.from_config(route["destination"])
        provider_options = route.get("provider", {}).get("options", {}) or {}

        query = {
            "origins": origin.as_coordinate_pair(),
            "destinations": destination.as_coordinate_pair(),
            "mode": route.get("travel_mode", "driving"),
            "key": self.api_key,
        }
        query.update(provider_options)

        response = self._request(_normalize_query_values(query))
        if response.get("status") != "OK":
            raise RoutingProviderError(
                f"Google Distance Matrix API returned status {response.get('status')!r}."
            )

        try:
            element = response["rows"][0]["elements"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise RoutingProviderError("Google Distance Matrix API response has no route element.") from exc

        element_status = element.get("status", "UNKNOWN")
        if element_status != "OK":
            raise RoutingProviderError(
                f"Google Distance Matrix API route element returned status {element_status!r}."
            )

        duration = element.get("duration_in_traffic") or element.get("duration")
        distance = element.get("distance")
        if not duration or not distance:
            raise RoutingProviderError("Google Distance Matrix API response is missing duration or distance.")

        return RouteTravelTime(
            duration_seconds=int(duration["value"]),
            distance_meters=int(distance["value"]),
            provider=self.provider_name,
            status=element_status,
            raw_response=response,
        )

    def _request(self, query: Mapping[str, Any]) -> Mapping[str, Any]:
        url = f"{self.endpoint}?{urlencode(query)}"
        return _read_json_url(url, self.timeout_seconds)


def _tomtom_travel_mode(travel_mode: str) -> str:
    if travel_mode == "driving":
        return "car"
    return travel_mode


def _normalize_query_values(query: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in query.items():
        if isinstance(value, bool):
            normalized[key] = str(value).lower()
        else:
            normalized[key] = value
    return normalized
