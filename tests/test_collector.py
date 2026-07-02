from src.collector.collect import build_provider, collect_route, load_routes_config
from src.collector.providers import GoogleDistanceMatrixProvider, RouteTravelTime, TomTomRoutingProvider


class FakeProvider:
    provider_name = "fake"

    def get_travel_time(self, route):
        return RouteTravelTime(
            duration_seconds=1234,
            distance_meters=5678,
            provider=self.provider_name,
            status="OK",
            raw_response={},
        )


class FakeTomTomProvider(TomTomRoutingProvider):
    def _request(self, origin, destination, query):
        self.last_origin = origin
        self.last_destination = destination
        self.last_query = query
        return {
            "routes": [
                {
                    "summary": {
                        "lengthInMeters": 9800,
                        "travelTimeInSeconds": 1440,
                    }
                }
            ]
        }


def test_load_routes_config_reads_tomtom_mvp_route():
    config = load_routes_config(__import__("pathlib").Path("config/routes.yml"))

    assert config["routes"][0]["id"] == "home_to_work"
    assert config["routes"][0]["provider"]["name"] == "tomtom_routing"


def test_build_provider_keeps_google_support():
    provider = build_provider("google_maps_distance_matrix", api_key="google-key")

    assert isinstance(provider, GoogleDistanceMatrixProvider)


def test_collect_route_returns_minimal_observation_shape():
    route = {
        "id": "route-a",
        "origin": {"latitude": 52.1, "longitude": 21.1},
        "destination": {"latitude": 52.2, "longitude": 21.2},
    }

    observation = collect_route(route, FakeProvider())

    assert observation["route_id"] == "route-a"
    assert observation["duration_seconds"] == 1234
    assert observation["distance_meters"] == 5678
    assert observation["provider"] == "fake"
    assert observation["status"] == "OK"
    assert observation["observed_at_utc"].endswith("Z")


def test_tomtom_provider_normalizes_route_summary():
    route = {
        "id": "route-a",
        "origin": {"latitude": 52.1, "longitude": 21.1},
        "destination": {"latitude": 52.2, "longitude": 21.2},
        "travel_mode": "driving",
        "provider": {"options": {"traffic": True}},
    }
    provider = FakeTomTomProvider(api_key="tomtom-key")

    travel_time = provider.get_travel_time(route)

    assert provider.last_origin.as_coordinate_pair() == "52.1,21.1"
    assert provider.last_destination.as_coordinate_pair() == "52.2,21.2"
    assert provider.last_query["traffic"] == "true"
    assert provider.last_query["travelMode"] == "car"
    assert travel_time.duration_seconds == 1440
    assert travel_time.distance_meters == 9800
    assert travel_time.provider == "tomtom_routing"
