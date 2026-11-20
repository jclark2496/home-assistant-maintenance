from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .core import (
    DigestConfig,
    backup_items,
    battery_items,
    build_title,
    deduplicate_new_categories,
    delivery_marker,
    indicator_items,
    issue_fingerprint,
    unavailable_items,
    update_items,
)


class StateSource(Protocol):
    def states(self) -> Sequence[Mapping[str, Any]]: ...
    def history(self, entity_ids: Sequence[str], *, start: datetime, end: datetime) -> Mapping[str, Sequence[Mapping[str, Any]]]: ...


class ReminderAdapter(Protocol):
    def add(self, *, title: str, list_name: str, due, marker: str) -> None: ...
    def find_by_marker(self, *, list_name: str, marker: str) -> list[Mapping[str, Any]]: ...


class WorkflowError(RuntimeError):
    pass


class CorruptStateError(WorkflowError):
    pass


class LockBusyError(WorkflowError):
    pass


class UncertainDeliveryError(WorkflowError):
    pass


@dataclass(frozen=True)
class Preview:
    title: str | None
    updates: list[dict[str, str]]
    batteries: list[dict[str, str]]
    unavailable: list[dict[str, str]]
    backups: list[dict[str, str]]
    indicators: list[dict[str, str]]
    fingerprint: str

    @property
    def total(self) -> int:
        return sum(map(len, (self.updates, self.batteries, self.unavailable, self.backups, self.indicators)))


@dataclass(frozen=True)
class RunResult:
    outcome: str
    update_count: int
    battery_count: int
    unavailable_count: int
    backup_count: int
    indicator_count: int
    fingerprint: str


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")

    @contextmanager
    def lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LockBusyError("another maintenance run holds the state lock") from exc
            yield
        finally:
            os.close(descriptor)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CorruptStateError("state is unreadable or invalid JSON; sends are blocked") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise CorruptStateError("state has an unsupported structure; sends are blocked")
        return value

    def save(self, value: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(dict(value), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def reset_with_backup(self, now: datetime) -> Path | None:
        backup = None
        if self.path.exists():
            backup = self.path.with_name(f"{self.path.name}.backup-{now.strftime('%Y%m%dT%H%M%S')}")
            os.replace(self.path, backup)
            os.chmod(backup, 0o600)
        self.save({"schema_version": 1, "reset_at": now.isoformat()})
        return backup


def history_window(config: DigestConfig, now: datetime) -> tuple[datetime, datetime] | None:
    if not config.unavailable_rules:
        return None
    longest = max(rule.threshold for rule in config.unavailable_rules)
    return now - longest, now


def make_preview(states: Sequence[Mapping[str, Any]], config: DigestConfig, *, histories: Mapping[str, Sequence[Mapping[str, Any]]] | None = None, now: datetime | None = None) -> Preview:
    current_time = now or datetime.now().astimezone()
    updates = update_items(states, config)
    batteries = battery_items(states, config)
    unavailable = unavailable_items(states, histories or {}, config, current_time)
    backups = backup_items(states, config, current_time)
    indicators = indicator_items(states, config)
    unavailable, backups, indicators = deduplicate_new_categories(unavailable, backups, indicators)
    fingerprint = issue_fingerprint(updates, batteries, config.reminder_list, unavailable, backups, indicators)
    title = build_title(updates, batteries, config, unavailable, backups, indicators) if any((updates, batteries, unavailable, backups, indicators)) else None
    return Preview(title, updates, batteries, unavailable, backups, indicators, fingerprint)


def preview_from_source(source: StateSource, config: DigestConfig, now: datetime | None = None) -> Preview:
    current_time = now or datetime.now().astimezone()
    states = list(source.states())
    histories: Mapping[str, Sequence[Mapping[str, Any]]] = {}
    window = history_window(config, current_time)
    if window:
        histories = source.history([rule.entity_id for rule in config.unavailable_rules], start=window[0], end=window[1])
    return make_preview(states, config, histories=histories, now=current_time)


def run_once(*, source: StateSource, reminder: ReminderAdapter, state_store: StateStore, config: DigestConfig, now: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> RunResult:
    with state_store.lock():
        state = state_store.load()
        pending = state.get("pending_delivery")
        if isinstance(pending, dict):
            counts = _pending_counts(pending)
            fingerprint = str(pending.get("fingerprint", ""))
            marker = str(pending.get("marker", ""))
            pending_list = str(pending.get("list") or config.reminder_list)
            matches = reminder.find_by_marker(list_name=pending_list, marker=marker)
            if matches:
                state.pop("pending_delivery", None)
                state.update(_confirmed_state(fingerprint, counts, now(), "reconciled"))
                state_store.save(state)
                return _result("delivery_reconciled", counts, fingerprint)
            raise UncertainDeliveryError("a prior delivery is unresolved; no reminder was written. Inspect Reminders, then use 'resolve'")

        current_time = now()
        preview = preview_from_source(source, config, current_time)
        counts = _preview_counts(preview)
        if preview.total == 0:
            state.update(_confirmed_state(preview.fingerprint, counts, current_time, "clean"))
            state_store.save(state)
            return _result("clean", counts, preview.fingerprint)
        if state.get("last_confirmed_fingerprint") == preview.fingerprint:
            return _result("duplicate_suppressed", counts, preview.fingerprint)

        marker = delivery_marker(preview.fingerprint)
        state["pending_delivery"] = {
            "fingerprint": preview.fingerprint,
            "marker": marker,
            "list": config.reminder_list,
            **counts,
            "started_at": current_time.isoformat(),
        }
        state_store.save(state)
        try:
            reminder.add(title=preview.title or "", list_name=config.reminder_list, due=current_time.date(), marker=marker)
        except Exception as exc:
            try:
                matches = reminder.find_by_marker(list_name=config.reminder_list, marker=marker)
            except Exception:
                matches = []
            if matches:
                state.pop("pending_delivery", None)
                state.update(_confirmed_state(preview.fingerprint, counts, now(), "readback_after_error"))
                state_store.save(state)
                return _result("reminder_added_readback", counts, preview.fingerprint)
            raise UncertainDeliveryError("reminder command failed and readback found no marker; state remains pending and no automatic retry will occur") from exc

        matches = reminder.find_by_marker(list_name=config.reminder_list, marker=marker)
        if not matches:
            raise UncertainDeliveryError("reminder command returned success but readback found no marker; state remains pending")
        state.pop("pending_delivery", None)
        state.update(_confirmed_state(preview.fingerprint, counts, now(), "readback_confirmed"))
        state_store.save(state)
        return _result("reminder_added", counts, preview.fingerprint)


def resolve_pending(*, state_store: StateStore, outcome: str, now: datetime) -> None:
    if outcome not in {"delivered", "not-delivered"}:
        raise ValueError("invalid resolution")
    with state_store.lock():
        state = state_store.load()
        pending = state.get("pending_delivery")
        if not isinstance(pending, dict):
            raise WorkflowError("there is no pending delivery to resolve")
        state.pop("pending_delivery", None)
        if outcome == "delivered":
            state.update(_confirmed_state(str(pending["fingerprint"]), _pending_counts(pending), now, "operator_confirmed"))
        else:
            state["last_resolution"] = {"outcome": outcome, "at": now.isoformat()}
        state_store.save(state)


def _preview_counts(preview: Preview) -> dict[str, int]:
    return {"update_count": len(preview.updates), "battery_count": len(preview.batteries), "unavailable_count": len(preview.unavailable), "backup_count": len(preview.backups), "indicator_count": len(preview.indicators)}


def _pending_counts(pending: Mapping[str, Any]) -> dict[str, int]:
    return {key: int(pending.get(key, 0)) for key in ("update_count", "battery_count", "unavailable_count", "backup_count", "indicator_count")}


def _result(outcome: str, counts: Mapping[str, int], fingerprint: str) -> RunResult:
    return RunResult(outcome, counts["update_count"], counts["battery_count"], counts["unavailable_count"], counts["backup_count"], counts["indicator_count"], fingerprint)


def _confirmed_state(fingerprint: str, counts: Mapping[str, int], now: datetime, evidence: str) -> dict[str, Any]:
    return {"schema_version": 1, "last_confirmed_fingerprint": fingerprint, "last_update_count": counts["update_count"], "last_battery_count": counts["battery_count"], "last_unavailable_count": counts["unavailable_count"], "last_backup_count": counts["backup_count"], "last_indicator_count": counts["indicator_count"], "last_confirmed_at": now.isoformat(), "last_confirmation_evidence": evidence}
