from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class DigestConfig:
    reminder_list: str
    low_battery_threshold: float = 25.0
    special_battery_thresholds: Mapping[str, float] = field(default_factory=dict)
    special_battery_names: Mapping[str, str] = field(default_factory=dict)
    ignored_battery_entities: frozenset[str] = field(default_factory=frozenset)
    ignored_update_entities: frozenset[str] = field(default_factory=frozenset)
    max_updates_in_title: int = 6
    max_batteries_in_title: int = 8
    max_title_length: int = 900
    title_prefix: str = "Review Home Assistant"

    def __post_init__(self) -> None:
        if not self.reminder_list.strip():
            raise ValueError("reminder_list must not be empty")
        if self.low_battery_threshold < 0 or self.low_battery_threshold > 100:
            raise ValueError("low_battery_threshold must be between 0 and 100")
        if self.max_updates_in_title < 0 or self.max_batteries_in_title < 0:
            raise ValueError("title limits must be non-negative")
        if self.max_title_length < 80:
            raise ValueError("max_title_length must be at least 80")
        for entity_id, threshold in self.special_battery_thresholds.items():
            if not 0 <= float(threshold) <= 100:
                raise ValueError(f"battery threshold for {entity_id!r} must be between 0 and 100")


def update_items(states: Sequence[Mapping[str, Any]], config: DigestConfig | None = None) -> list[dict[str, str]]:
    ignored = config.ignored_update_entities if config else frozenset()
    items: list[dict[str, str]] = []
    for state in states:
        entity_id = str(state.get("entity_id", ""))
        attributes = state.get("attributes") or {}
        if entity_id in ignored:
            continue
        if entity_id.startswith("update.") and state.get("state") == "on":
            items.append({
                "type": "update",
                "entity_id": entity_id,
                "name": str(attributes.get("friendly_name") or entity_id),
                "installed": str(attributes.get("installed_version") or "unknown"),
                "latest": str(attributes.get("latest_version") or "unknown"),
            })
    return sorted(items, key=lambda item: item["name"].lower())


def battery_items(states: Sequence[Mapping[str, Any]], config: DigestConfig) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for state in states:
        entity_id = str(state.get("entity_id", ""))
        if entity_id in config.ignored_battery_entities:
            continue
        attributes = state.get("attributes") or {}
        if attributes.get("unit_of_measurement") != "%":
            continue
        if not (attributes.get("device_class") == "battery" or "battery" in entity_id.lower()):
            continue
        try:
            value = float(state.get("state"))
        except (TypeError, ValueError):
            continue
        threshold = float(config.special_battery_thresholds.get(entity_id, config.low_battery_threshold))
        if value <= threshold:
            items.append({
                "type": "battery",
                "entity_id": entity_id,
                "name": str(config.special_battery_names.get(entity_id) or attributes.get("friendly_name") or entity_id),
                "percent": f"{value:g}",
            })
    return sorted(items, key=lambda item: (float(item["percent"]), item["name"].lower()))


def issue_fingerprint(updates: Sequence[Mapping[str, str]], batteries: Sequence[Mapping[str, str]], reminder_list: str) -> str:
    payload = json.dumps({
        "reminder_list": reminder_list,
        "updates": [(item["entity_id"], item["installed"], item["latest"]) for item in updates],
        "batteries": [(item["entity_id"], item["percent"]) for item in batteries],
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def delivery_marker(fingerprint: str) -> str:
    return f"[home-assistant-maintenance:{fingerprint}]"


def _bounded(items: list[str], total: int, limit: int) -> str:
    rendered = "; ".join(items[:limit])
    if total > limit:
        rendered += f"; +{total - limit} more"
    return rendered


def build_title(updates: Sequence[Mapping[str, str]], batteries: Sequence[Mapping[str, str]], config: DigestConfig) -> str:
    parts: list[str] = []
    if updates:
        names = [f"{item['name']} {item['installed']}→{item['latest']}" for item in updates]
        parts.append(f"updates ({len(updates)}): " + _bounded(names, len(updates), config.max_updates_in_title))
    if batteries:
        names = [f"{item['name']} {item['percent']}%" for item in batteries]
        parts.append(f"low batteries ({len(batteries)}): " + _bounded(names, len(batteries), config.max_batteries_in_title))
    title = config.title_prefix + ": " + " | ".join(parts)
    if len(title) > config.max_title_length:
        title = title[: config.max_title_length - 1].rstrip() + "…"
    return title
