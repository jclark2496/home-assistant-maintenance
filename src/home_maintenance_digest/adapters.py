from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class AdapterError(RuntimeError):
    pass


class HomeAssistantHttpSource:
    """Read-only Home Assistant source using states and bounded history GETs."""

    def __init__(self, *, base_url: str, token: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    def _get_json(self, path: str) -> Any:
        request = Request(
            self.base_url + path,
            headers={"Authorization": "Bearer " + self._token, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            raise AdapterError(f"Home Assistant returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise AdapterError(f"Home Assistant read failed ({type(exc).__name__})") from exc

    def states(self) -> Sequence[dict[str, Any]]:
        payload = self._get_json("/api/states")
        if not isinstance(payload, list):
            raise AdapterError("Home Assistant /api/states did not return a list")
        return payload

    def history(self, entity_ids: Sequence[str], *, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
        """Read bounded history for explicitly configured entities only."""
        if not entity_ids:
            return {}
        start_text = _utc_iso(start)
        query = urlencode({
            "filter_entity_id": ",".join(entity_ids),
            "end_time": _utc_iso(end),
            "minimal_response": "",
            "no_attributes": "",
        })
        payload = self._get_json(f"/api/history/period/{quote(start_text, safe='')}?{query}")
        if not isinstance(payload, list):
            raise AdapterError("Home Assistant history API did not return a list")
        result = {entity_id: [] for entity_id in entity_ids}
        for series in payload:
            if not isinstance(series, list):
                continue
            series_entity = next((str(record.get("entity_id")) for record in series if isinstance(record, dict) and record.get("entity_id")), "")
            if series_entity not in result:
                continue
            for record in series:
                if isinstance(record, dict):
                    normalized = dict(record)
                    normalized.setdefault("entity_id", series_entity)
                    result[series_entity].append(normalized)
        return result

    def check(self) -> None:
        self._get_json("/api/")


class RemindctlAdapter:
    """Apple Reminders adapter with marker-based post-write readback."""

    def __init__(self, binary: Path = Path("/opt/homebrew/bin/remindctl"), timeout: float = 30.0):
        self.binary = binary
        self.timeout = timeout

    def _run(self, arguments: list[str]) -> str:
        try:
            completed = subprocess.run(
                [str(self.binary), *arguments, "--json", "--no-input", "--no-color"],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError("remindctl timed out; delivery is uncertain") from exc
        except subprocess.CalledProcessError as exc:
            raise AdapterError(f"remindctl failed with exit code {exc.returncode}; delivery is uncertain") from exc
        except OSError as exc:
            raise AdapterError(f"remindctl could not start ({type(exc).__name__})") from exc
        return completed.stdout

    def status(self) -> Any:
        return _parse_json(self._run(["status"]), "remindctl status")

    def lists(self) -> Any:
        return _parse_json(self._run(["list"]), "remindctl list")

    def list_exists(self, list_name: str) -> bool:
        return _contains_list_name(self.lists(), list_name)

    def add(self, *, title: str, list_name: str, due: date, marker: str) -> None:
        self._run(["add", "--title", title, "--list", list_name, "--due", due.isoformat(), "--notes", marker])

    def find_by_marker(self, *, list_name: str, marker: str) -> list[dict[str, Any]]:
        payload = _parse_json(self._run(["show", "all", "--list", list_name]), "remindctl show")
        matches: list[dict[str, Any]] = []
        for record in _walk_dicts(payload):
            if any(isinstance(value, str) and marker in value for key, value in record.items() if key.lower() in {"notes", "note"}):
                matches.append(record)
        return matches


def _parse_json(text: str, label: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise AdapterError(f"{label} returned invalid JSON") from exc


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _contains_list_name(payload: Any, list_name: str) -> bool:
    target = list_name.casefold()
    for record in _walk_dicts(payload):
        for key, value in record.items():
            if key.lower() in {"name", "title", "list", "listname", "list_name"} and isinstance(value, str) and value.casefold() == target:
                return True
    if isinstance(payload, list):
        return any(isinstance(item, str) and item.casefold() == target for item in payload)
    return False


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat()
