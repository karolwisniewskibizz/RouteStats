"""CLI entry point for collecting current route travel-time estimates."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised when dependency is unavailable
    yaml = None

from src.collector.providers import (
    GoogleDistanceMatrixProvider,
    TomTomRoutingProvider,
    RoutingProvider,
    RoutingProviderError,
)


PROVIDERS = {
    TomTomRoutingProvider.provider_name: TomTomRoutingProvider,
    GoogleDistanceMatrixProvider.provider_name: GoogleDistanceMatrixProvider,
}

PROVIDER_API_KEY_ENV = {
    TomTomRoutingProvider.provider_name: ("TOMTOM_API_KEY", "ROUTING_API_KEY"),
    GoogleDistanceMatrixProvider.provider_name: ("GOOGLE_MAPS_API_KEY", "ROUTING_API_KEY"),
}


def load_routes_config(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        content = handle.read()
    if yaml is not None:
        config = yaml.safe_load(content) or {}
    else:
        config = _load_routes_config_without_pyyaml(content)
    if "routes" not in config or not isinstance(config["routes"], list):
        raise ValueError("Route configuration must contain a 'routes' list.")
    return config


def _load_routes_config_without_pyyaml(content: str) -> Mapping[str, Any]:
    """Parse the small RouteStats YAML subset when PyYAML is not installed."""

    config: dict[str, Any] = {"routes": []}
    current_route: dict[str, Any] | None = None
    section_stack: list[tuple[int, dict[str, Any]]] = []
    current_list_key: str | None = None
    current_list: list[Any] | None = None

    for raw_line in content.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        line = line_without_comment.strip()

        if indent == 0 and line.startswith("version:"):
            config["version"] = _parse_scalar(line.split(":", 1)[1].strip())
            continue
        if indent == 0 and line == "routes:":
            continue
        if line.startswith("- ") and indent == 2:
            current_route = {}
            config["routes"].append(current_route)
            section_stack = [(2, current_route)]
            key, value = line[2:].split(":", 1)
            current_route[key.strip()] = _parse_scalar(value.strip())
            current_list_key = None
            current_list = None
            continue
        if current_route is None:
            continue

        while section_stack and section_stack[-1][0] >= indent:
            section_stack.pop()
        parent = section_stack[-1][1] if section_stack else current_route

        if line.startswith("- "):
            if current_list_key is None or current_list is None:
                raise ValueError(f"List item without list key in routes config: {raw_line}")
            item = line[2:].strip()
            if ":" in item:
                key, value = item.split(":", 1)
                entry = {key.strip(): _parse_scalar(value.strip())}
                current_list.append(entry)
                section_stack.append((indent, entry))
            else:
                current_list.append(_parse_scalar(item))
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            if key in {"active_days", "active_time_windows"}:
                current_list_key = key
                current_list = []
                parent[key] = current_list
                continue
            next_container: dict[str, Any] = {}
            parent[key] = next_container
            section_stack.append((indent, next_container))
            current_list_key = None
            current_list = None
            continue
        parent[key] = _parse_scalar(value)

    return config


def _parse_scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(item.strip()) for item in value[1:-1].split(",") if item.strip()]
    if value.startswith(('"', "'")) and value.endswith(('"', "'")):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def build_provider(provider_name: str, api_key: str | None = None) -> RoutingProvider:
    provider_class = PROVIDERS.get(provider_name)
    if provider_class is None:
        raise ValueError(f"Unsupported routing provider: {provider_name}")
    resolved_api_key = api_key or _api_key_from_environment(provider_name)
    return provider_class(api_key=resolved_api_key or "")


def _api_key_from_environment(provider_name: str) -> str | None:
    for environment_variable in PROVIDER_API_KEY_ENV.get(provider_name, ("ROUTING_API_KEY",)):
        if value := os.getenv(environment_variable):
            return value
    return None


def collect_route(route: Mapping[str, Any], provider: RoutingProvider) -> Mapping[str, Any]:
    observed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    travel_time = provider.get_travel_time(route)
    return {
        "observed_at_utc": observed_at,
        "route_id": route["id"],
        "origin_lat": route["origin"]["latitude"],
        "origin_lon": route["origin"]["longitude"],
        "destination_lat": route["destination"]["latitude"],
        "destination_lon": route["destination"]["longitude"],
        "duration_seconds": travel_time.duration_seconds,
        "distance_meters": travel_time.distance_meters,
        "provider": travel_time.provider,
        "status": travel_time.status,
    }


def collect_enabled_routes(config: Mapping[str, Any], api_key: str | None = None) -> list[Mapping[str, Any]]:
    observations: list[Mapping[str, Any]] = []
    provider_cache: dict[str, RoutingProvider] = {}
    for route in config["routes"]:
        if not route.get("enabled", True):
            continue
        provider_name = route.get("provider", {}).get("name")
        if not provider_name:
            raise ValueError(f"Route {route.get('id', '<unknown>')} is missing provider.name.")
        if provider_name not in provider_cache:
            provider_cache[provider_name] = build_provider(provider_name, api_key=api_key)
        provider = provider_cache[provider_name]
        observations.append(collect_route(route, provider))
    return observations


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect current travel-time estimates for enabled routes.")
    parser.add_argument("--routes", type=Path, default=Path("config/routes.yml"), help="Path to routes YAML.")
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "Routing provider API key. Defaults to TOMTOM_API_KEY, "
            "GOOGLE_MAPS_API_KEY, or ROUTING_API_KEY."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_routes_config(args.routes)
        observations = collect_enabled_routes(config, api_key=args.api_key)
    except (OSError, ValueError, RoutingProviderError) as exc:
        raise SystemExit(f"collector error: {exc}") from exc

    for observation in observations:
        print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
