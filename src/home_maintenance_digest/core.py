from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import secrets
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*$", re.IGNORECASE)
_OPERATORS = {"lt", "lte", "gt", "gte", "eq", "ne"}


def parse_duration(value: str | int | float) -> timedelta:
    """Parse an explicit duration such as 90m, 2h, 1d, or 1w."""
    if isinstance(value, bool):
        raise ValueError("duration must use a number plus s, m, h, d, or w")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        match = _DURATION_RE.fullmatch(value)
        if not match:
            raise ValueError("duration must use a number plus s, m, h, d, or w")
        amount = float(match.group(1))
        seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[match.group(2).lower()]
    else:
        raise ValueError("duration must use a number plus s, m, h, d, or w")
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("duration must be greater than zero")
    return timedelta(seconds=seconds)


@dataclass(frozen=True)
class UnavailableRule:
    entity_id: str
    threshold: timedelta
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_id.strip():
            raise ValueError("unavailable entity_id must not be empty")
        if self.threshold.total_seconds() <= 0:
            raise ValueError(f"unavailable threshold for {self.entity_id!r} must be positive")


@dataclass(frozen=True)
class BackupRule:
    entity_id: str
    name: str | None = None
    failure_states: frozenset[str] = field(default_factory=frozenset)
    max_age: timedelta | None = None
    timestamp_attribute: str | None = None
    timestamp_timezone: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_id.strip():
            raise ValueError("backup entity_id must not be empty")
        if not self.failure_states and self.max_age is None:
            raise ValueError(f"backup rule for {self.entity_id!r} needs failure_states and/or max_age")
        if self.max_age is not None and self.max_age.total_seconds() <= 0:
            raise ValueError(f"backup max_age for {self.entity_id!r} must be positive")
        if self.timestamp_attribute is not None and not self.timestamp_attribute.strip():
            raise ValueError(f"backup timestamp_attribute for {self.entity_id!r} must not be empty")
        if self.timestamp_timezone:
            try:
                ZoneInfo(self.timestamp_timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"backup timestamp_timezone for {self.entity_id!r} is invalid") from exc


@dataclass(frozen=True)
class IndicatorRule:
    entity_id: str
    name: str | None = None
    problem_states: frozenset[str] = field(default_factory=frozenset)
    operator: str | None = None
    threshold: float | None = None
    unit: str | None = None
    value_attribute: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_id.strip():
            raise ValueError("maintenance indicator entity_id must not be empty")
        state_mode = bool(self.problem_states)
        numeric_mode = self.operator is not None or self.threshold is not None
        if state_mode == numeric_mode:
            raise ValueError(f"indicator {self.entity_id!r} must use exactly one of problem_states or operator+threshold")
        if numeric_mode:
            if self.operator not in _OPERATORS or self.threshold is None or not math.isfinite(float(self.threshold)):
                raise ValueError(f"indicator {self.entity_id!r} has an invalid operator or threshold")
        if self.value_attribute is not None and not self.value_attribute.strip():
            raise ValueError(f"indicator value_attribute for {self.entity_id!r} must not be empty")


@dataclass(frozen=True)
class DigestConfig:
    reminder_list: str
    low_battery_threshold: float = 25.0
    special_battery_thresholds: Mapping[str, float] = field(default_factory=dict)
    special_battery_names: Mapping[str, str] = field(default_factory=dict)
    ignored_battery_entities: frozenset[str] = field(default_factory=frozenset)
    ignored_update_entities: frozenset[str] = field(default_factory=frozenset)
    unavailable_rules: tuple[UnavailableRule, ...] = ()
    backup_rules: tuple[BackupRule, ...] = ()
    indicator_rules: tuple[IndicatorRule, ...] = ()
    max_updates_in_title: int = 6
    max_batteries_in_title: int = 8
    max_maintenance_in_title: int = 8
    max_title_length: int = 900
    title_prefix: str = "Review Home Assistant"

    def __post_init__(self) -> None:
        if not self.reminder_list.strip():
            raise ValueError("reminder_list must not be empty")
        if self.low_battery_threshold < 0 or self.low_battery_threshold > 100:
            raise ValueError("low_battery_threshold must be between 0 and 100")
        if self.max_updates_in_title < 0 or self.max_batteries_in_title < 0 or self.max_maintenance_in_title < 0:
            raise ValueError("title limits must be non-negative")
        if self.max_title_length < 80:
            raise ValueError("max_title_length must be at least 80")
        for entity_id, threshold in self.special_battery_thresholds.items():
            if not 0 <= float(threshold) <= 100:
                raise ValueError(f"battery threshold for {entity_id!r} must be between 0 and 100")
        for label, rules in (("unavailable", self.unavailable_rules), ("backup", self.backup_rules), ("indicator", self.indicator_rules)):
            ids = [rule.entity_id for rule in rules]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} entity_id mappings are not allowed")


def update_items(states: Sequence[Mapping[str, Any]], config: DigestConfig | None = None) -> list[dict[str, str]]:
    ignored = config.ignored_update_entities if config else frozenset()
    items: list[dict[str, str]] = []
    for state in states:
        entity_id = str(state.get("entity_id", ""))
        attributes = state.get("attributes") or {}
        if entity_id in ignored:
            continue
        if entity_id.startswith("update.") and state.get("state") == "on":
            items.append({"type": "update", "entity_id": entity_id, "name": str(attributes.get("friendly_name") or entity_id), "installed": str(attributes.get("installed_version") or "unknown"), "latest": str(attributes.get("latest_version") or "unknown")})
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
        value = _finite_float(state.get("state"))
        if value is None:
            continue
        threshold = float(config.special_battery_thresholds.get(entity_id, config.low_battery_threshold))
        if 0 <= value <= 100 and value <= threshold:
            items.append({"type": "battery", "entity_id": entity_id, "name": str(config.special_battery_names.get(entity_id) or attributes.get("friendly_name") or entity_id), "percent": f"{value:g}"})
    return sorted(items, key=lambda item: (float(item["percent"]), item["name"].lower()))


def unavailable_items(states: Sequence[Mapping[str, Any]], histories: Mapping[str, Sequence[Mapping[str, Any]]], config: DigestConfig, now: datetime) -> list[dict[str, str]]:
    by_id = {str(item.get("entity_id", "")): item for item in states}
    now_aware = _aware_now(now)
    items: list[dict[str, str]] = []
    for rule in config.unavailable_rules:
        current = by_id.get(rule.entity_id)
        if not current or str(current.get("state", "")).casefold() != "unavailable":
            continue
        cutoff = now_aware - rule.threshold
        # /api/states carries the actual state transition time when available.
        # History may instead synthesize a start-of-window row whose timestamp
        # advances on every request, so never use that row as episode identity.
        episode_started = _parse_timestamp(current.get("last_changed"))
        if episode_started is not None and episode_started > cutoff:
            continue
        records = list(histories.get(rule.entity_id, ()))
        proof: list[tuple[datetime, str]] = []
        for record in records:
            changed = _parse_timestamp(record.get("last_changed") or record.get("last_updated"))
            if changed is not None:
                proof.append((changed, str(record.get("state", "")).casefold()))
        proof.sort(key=lambda pair: pair[0])
        # Home Assistant history normally includes the state active at start_time.
        # Require a state at/before this rule's cutoff, then inspect only its window.
        baseline = [pair for pair in proof if pair[0] <= cutoff]
        if not baseline:
            continue
        relevant = [baseline[-1], *(pair for pair in proof if pair[0] > cutoff)]
        if any(state != "unavailable" for _, state in relevant):
            continue
        attributes = current.get("attributes") or {}
        item = {
            "type": "unavailable",
            "entity_id": rule.entity_id,
            "name": str(rule.name or attributes.get("friendly_name") or rule.entity_id),
            "duration": _format_duration(rule.threshold),
            # A stable fallback deliberately trades episode precision for
            # duplicate suppression when Recorder only supplies a synthetic
            # baseline and current last_changed is absent/malformed.
            "episode_id": episode_started.isoformat() if episode_started is not None else "bounded-history",
        }
        if episode_started is not None:
            item["since"] = episode_started.isoformat()
        items.append(item)
    return sorted(items, key=lambda item: item["name"].lower())


def backup_items(states: Sequence[Mapping[str, Any]], config: DigestConfig, now: datetime) -> list[dict[str, str]]:
    by_id = {str(item.get("entity_id", "")): item for item in states}
    now_aware = _aware_now(now)
    items: list[dict[str, str]] = []
    for rule in config.backup_rules:
        current = by_id.get(rule.entity_id)
        if not current:
            continue
        attributes = current.get("attributes") or {}
        raw_state = str(current.get("state", ""))
        name = str(rule.name or attributes.get("friendly_name") or rule.entity_id)
        if raw_state.casefold() in {value.casefold() for value in rule.failure_states}:
            items.append({"type": "backup", "entity_id": rule.entity_id, "name": name, "status": "failed", "detail": raw_state})
            continue
        if rule.max_age is None:
            continue
        raw_timestamp = attributes.get(rule.timestamp_attribute) if rule.timestamp_attribute else current.get("state")
        completed = _parse_timestamp(raw_timestamp, rule.timestamp_timezone)
        # Unknown/malformed timestamps are deliberately not called stale.
        if completed is None:
            continue
        age = now_aware - completed
        if age > rule.max_age:
            items.append({"type": "backup", "entity_id": rule.entity_id, "name": name, "status": "stale", "detail": completed.isoformat(), "age": _format_duration(age)})
    return sorted(items, key=lambda item: item["name"].lower())


def indicator_items(states: Sequence[Mapping[str, Any]], config: DigestConfig) -> list[dict[str, str]]:
    by_id = {str(item.get("entity_id", "")): item for item in states}
    items: list[dict[str, str]] = []
    for rule in config.indicator_rules:
        current = by_id.get(rule.entity_id)
        if not current:
            continue
        attributes = current.get("attributes") or {}
        raw = attributes.get(rule.value_attribute) if rule.value_attribute else current.get("state")
        problem = False
        detail = str(raw)
        if rule.problem_states:
            problem = detail.casefold() in {value.casefold() for value in rule.problem_states}
        else:
            if rule.unit is not None and str(attributes.get("unit_of_measurement", "")) != rule.unit:
                continue
            value = _finite_float(raw)
            if value is None:
                continue
            problem = _compare(value, rule.operator or "", float(rule.threshold))
            detail = f"{value:g}{rule.unit or ''}"
        if problem:
            items.append({"type": "indicator", "entity_id": rule.entity_id, "name": str(rule.name or attributes.get("friendly_name") or rule.entity_id), "detail": detail})
    return sorted(items, key=lambda item: item["name"].lower())


def deduplicate_new_categories(unavailable: list[dict[str, str]], backups: list[dict[str, str]], indicators: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Keep one finding per entity across opt-in categories, in severity order."""
    seen: set[str] = set()
    output: list[list[dict[str, str]]] = []
    for category in (unavailable, backups, indicators):
        kept = []
        for item in category:
            if item["entity_id"] not in seen:
                kept.append(item)
                seen.add(item["entity_id"])
        output.append(kept)
    return output[0], output[1], output[2]


def issue_fingerprint(updates: Sequence[Mapping[str, str]], batteries: Sequence[Mapping[str, str]], reminder_list: str, unavailable: Sequence[Mapping[str, str]] = (), backups: Sequence[Mapping[str, str]] = (), indicators: Sequence[Mapping[str, str]] = ()) -> str:
    # Keep the original payload byte-for-byte when optional categories have no
    # findings. Existing installs must not redeliver a legacy battery/update
    # digest merely because they upgraded to a version with default-off keys.
    data: dict[str, Any] = {
        "reminder_list": reminder_list,
        "updates": [(item["entity_id"], item["installed"], item["latest"]) for item in updates],
        "batteries": [(item["entity_id"], item["percent"]) for item in batteries],
    }
    if unavailable or backups or indicators:
        data.update({
            "unavailable": [(item["entity_id"], item.get("episode_id", "bounded-history")) for item in unavailable],
            "backups": [(item["entity_id"], item["status"], item["detail"]) for item in backups],
            "indicators": [(item["entity_id"], item["detail"]) for item in indicators],
        })
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def delivery_marker(fingerprint: str, nonce: str | None = None) -> str:
    attempt_nonce = nonce or secrets.token_hex(8)
    return f"[home-assistant-maintenance:{fingerprint}:{attempt_nonce}]"


def _bounded(items: list[str], total: int, limit: int) -> str:
    rendered = "; ".join(items[:limit])
    if total > limit:
        rendered += f"; +{total - limit} more"
    return rendered


def build_title(updates: Sequence[Mapping[str, str]], batteries: Sequence[Mapping[str, str]], config: DigestConfig, unavailable: Sequence[Mapping[str, str]] = (), backups: Sequence[Mapping[str, str]] = (), indicators: Sequence[Mapping[str, str]] = ()) -> str:
    parts: list[str] = []
    if updates:
        parts.append(f"updates ({len(updates)}): " + _bounded([f"{item['name']} {item['installed']}→{item['latest']}" for item in updates], len(updates), config.max_updates_in_title))
    if batteries:
        parts.append(f"low batteries ({len(batteries)}): " + _bounded([f"{item['name']} {item['percent']}%" for item in batteries], len(batteries), config.max_batteries_in_title))
    maintenance = [f"{item['name']} unavailable {item['duration']}" for item in unavailable]
    maintenance += [f"{item['name']} backup {item['status']}" for item in backups]
    maintenance += [f"{item['name']} {item['detail']}" for item in indicators]
    if maintenance:
        parts.append(f"maintenance ({len(maintenance)}): " + _bounded(maintenance, len(maintenance), config.max_maintenance_in_title))
    title = config.title_prefix + ": " + " | ".join(parts)
    if len(title) > config.max_title_length:
        title = title[: config.max_title_length - 1].rstrip() + "…"
    return title


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_timestamp(value: Any, naive_timezone: str | None = None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if not naive_timezone:
            return None
        try:
            zone = ZoneInfo(naive_timezone)
        except ZoneInfoNotFoundError:
            return None
        candidates = []
        for fold in (0, 1):
            candidate = parsed.replace(tzinfo=zone, fold=fold)
            # Round-tripping detects nonexistent wall times. Two valid folds
            # with different offsets are ambiguous and must fail closed.
            if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == parsed:
                candidates.append(candidate)
        if not candidates:
            return None
        if len(candidates) == 2 and candidates[0].utcoffset() != candidates[1].utcoffset():
            return None
        parsed = candidates[0]
    return parsed.astimezone(timezone.utc)


def _aware_now(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.astimezone()
    return value.astimezone(timezone.utc)


def _compare(value: float, operator: str, threshold: float) -> bool:
    return {"lt": value < threshold, "lte": value <= threshold, "gt": value > threshold, "gte": value >= threshold, "eq": value == threshold, "ne": value != threshold}[operator]


def _format_duration(value: timedelta) -> str:
    seconds = max(0, int(value.total_seconds()))
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"
