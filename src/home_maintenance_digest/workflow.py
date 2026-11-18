from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .core import DigestConfig, battery_items, build_title, delivery_marker, issue_fingerprint, update_items


class StateSource(Protocol):
    def states(self) -> Sequence[Mapping[str, Any]]: ...


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
    fingerprint: str


@dataclass(frozen=True)
class RunResult:
    outcome: str
    update_count: int
    battery_count: int
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


def make_preview(states: Sequence[Mapping[str, Any]], config: DigestConfig) -> Preview:
    updates = update_items(states, config)
    batteries = battery_items(states, config)
    fingerprint = issue_fingerprint(updates, batteries, config.reminder_list)
    title = build_title(updates, batteries, config) if updates or batteries else None
    return Preview(title, updates, batteries, fingerprint)


def run_once(*, source: StateSource, reminder: ReminderAdapter, state_store: StateStore, config: DigestConfig, now: Callable[[], datetime] = datetime.now) -> RunResult:
    with state_store.lock():
        state = state_store.load()
        pending = state.get("pending_delivery")
        if isinstance(pending, dict):
            fingerprint = str(pending.get("fingerprint", ""))
            marker = str(pending.get("marker", ""))
            pending_list = str(pending.get("list") or config.reminder_list)
            matches = reminder.find_by_marker(list_name=pending_list, marker=marker)
            if matches:
                state.pop("pending_delivery", None)
                state.update(_confirmed_state(fingerprint, int(pending.get("update_count", 0)), int(pending.get("battery_count", 0)), now(), "reconciled"))
                state_store.save(state)
                return RunResult("delivery_reconciled", int(pending.get("update_count", 0)), int(pending.get("battery_count", 0)), fingerprint)
            raise UncertainDeliveryError("a prior delivery is unresolved; no reminder was written. Inspect Reminders, then use 'resolve'")

        preview = make_preview(list(source.states()), config)
        current_time = now()
        if not preview.updates and not preview.batteries:
            state.update(_confirmed_state(preview.fingerprint, 0, 0, current_time, "clean"))
            state_store.save(state)
            return RunResult("clean", 0, 0, preview.fingerprint)
        if state.get("last_confirmed_fingerprint") == preview.fingerprint:
            return RunResult("duplicate_suppressed", len(preview.updates), len(preview.batteries), preview.fingerprint)

        marker = delivery_marker(preview.fingerprint)
        state["pending_delivery"] = {
            "fingerprint": preview.fingerprint,
            "marker": marker,
            "list": config.reminder_list,
            "update_count": len(preview.updates),
            "battery_count": len(preview.batteries),
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
                state.update(_confirmed_state(preview.fingerprint, len(preview.updates), len(preview.batteries), now(), "readback_after_error"))
                state_store.save(state)
                return RunResult("reminder_added_readback", len(preview.updates), len(preview.batteries), preview.fingerprint)
            raise UncertainDeliveryError("reminder command failed and readback found no marker; state remains pending and no automatic retry will occur") from exc

        matches = reminder.find_by_marker(list_name=config.reminder_list, marker=marker)
        if not matches:
            raise UncertainDeliveryError("reminder command returned success but readback found no marker; state remains pending")
        state.pop("pending_delivery", None)
        state.update(_confirmed_state(preview.fingerprint, len(preview.updates), len(preview.batteries), now(), "readback_confirmed"))
        state_store.save(state)
        return RunResult("reminder_added", len(preview.updates), len(preview.batteries), preview.fingerprint)


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
            state.update(_confirmed_state(str(pending["fingerprint"]), int(pending.get("update_count", 0)), int(pending.get("battery_count", 0)), now, "operator_confirmed"))
        else:
            state["last_resolution"] = {"outcome": outcome, "at": now.isoformat()}
        state_store.save(state)


def _confirmed_state(fingerprint: str, updates: int, batteries: int, now: datetime, evidence: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "last_confirmed_fingerprint": fingerprint,
        "last_update_count": updates,
        "last_battery_count": batteries,
        "last_confirmed_at": now.isoformat(),
        "last_confirmation_evidence": evidence,
    }
