from __future__ import annotations

import argparse
from datetime import datetime
import getpass
import json
from pathlib import Path
import sys
from typing import Sequence

from .adapters import AdapterError, HomeAssistantHttpSource, RemindctlAdapter
from .config import ConfigurationError, default_config_dir, load_config, write_configuration
from .workflow import CorruptStateError, LockBusyError, StateStore, UncertainDeliveryError, WorkflowError, preview_from_source, resolve_pending, run_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ha-maintenance", description="Read Home Assistant maintenance signals and explicitly create a verified Apple Reminder.")
    parser.add_argument("--config-dir", type=Path, default=None, help="configuration directory (never accepts credentials)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("configure", help="interactively write local config and credentials with mode 0600")
    subparsers.add_parser("doctor", help="run read-only configuration, Home Assistant, and Reminders checks")
    preview = subparsers.add_parser("preview", help="read Home Assistant and show the digest without writing")
    preview.add_argument("--json", action="store_true", help="emit machine-readable output")
    send = subparsers.add_parser("send", help="create one reminder after deduplication and readback")
    send.add_argument("--yes", action="store_true", help="required explicit write confirmation")
    resolve = subparsers.add_parser("resolve", help="resolve an uncertain prior delivery after manual inspection")
    resolve.add_argument("--outcome", choices=("delivered", "not-delivered"), required=True)
    resolve.add_argument("--yes", action="store_true", help="required explicit state-change confirmation")
    reset = subparsers.add_parser("state-reset", help="back up and replace state after operator review")
    reset.add_argument("--yes", action="store_true", help="required explicit state-change confirmation")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = (args.config_dir or default_config_dir()).expanduser()
    try:
        if args.command == "configure":
            return _configure(directory)
        config = load_config(directory)
        source = HomeAssistantHttpSource(base_url=config.base_url, token=config.token, timeout=config.http_timeout)
        reminder = RemindctlAdapter(config.remindctl_path, timeout=config.reminder_timeout)
        store = StateStore(config.state_path)
        if args.command == "doctor":
            return _doctor(config, source, reminder, store)
        if args.command == "preview":
            preview = preview_from_source(source, config.digest)
            if args.json:
                print(json.dumps({"update_count": len(preview.updates), "battery_count": len(preview.batteries), "unavailable_count": len(preview.unavailable), "backup_count": len(preview.backups), "indicator_count": len(preview.indicators), "title": preview.title, "updates": preview.updates, "batteries": preview.batteries, "unavailable": preview.unavailable, "backups": preview.backups, "indicators": preview.indicators}, indent=2))
            else:
                _print_preview(preview)
            return 0
        if args.command == "send":
            if not args.yes:
                print("Refusing to write: rerun with 'send --yes' after reviewing 'preview'.", file=sys.stderr)
                return 2
            result = run_once(source=source, reminder=reminder, state_store=store, config=config.digest)
            if result.outcome not in {"clean", "duplicate_suppressed"}:
                print(f"{result.outcome}: {result.update_count} update(s), {result.battery_count} low battery item(s), {result.unavailable_count} unavailable, {result.backup_count} backup, {result.indicator_count} indicator finding(s)")
            return 0
        if args.command == "resolve":
            if not args.yes:
                print("Refusing to change state without --yes.", file=sys.stderr)
                return 2
            resolve_pending(state_store=store, outcome=args.outcome, now=datetime.now())
            print(f"Pending delivery marked {args.outcome}. Review 'preview' before any later send.")
            return 0
        if args.command == "state-reset":
            if not args.yes:
                print("Refusing to reset state without --yes.", file=sys.stderr)
                return 2
            with store.lock():
                backup = store.reset_with_backup(datetime.now())
            print("State reset; prior state was backed up." if backup else "State initialized; no prior state existed.")
            return 0
    except (ConfigurationError, CorruptStateError, LockBusyError, UncertainDeliveryError, WorkflowError, AdapterError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    return 2


def _configure(directory: Path) -> int:
    print(f"Configuration directory: {directory}")
    base_url = input("Home Assistant URL (for example http://homeassistant.local:8123): ").strip()
    reminder_list = input("Existing Apple Reminders list name: ").strip()
    token = getpass.getpass("Home Assistant long-lived access token (input hidden): ")
    write_configuration(directory=directory, base_url=base_url, reminder_list=reminder_list, token=token)
    print("Configuration saved with owner-only permissions. Token was not printed.")
    print("Next: run 'ha-maintenance doctor', then 'ha-maintenance preview'.")
    return 0


def _doctor(config, source, reminder, store: StateStore) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("configuration", True, "valid; credentials file permissions are owner-only"))
    selections = (len(config.digest.unavailable_rules), len(config.digest.backup_rules), len(config.digest.indicator_rules))
    checks.append(("maintenance selections", True, f"{selections[0]} unavailable, {selections[1]} backup, {selections[2]} indicator mapping(s); unconfigured categories are off"))
    try:
        source.check()
        checks.append(("Home Assistant", True, "read-only API authentication succeeded"))
    except Exception as exc:
        checks.append(("Home Assistant", False, str(exc)))
    try:
        status = reminder.status()
        authorized = isinstance(status, dict) and status.get("authorized") is True
        checks.append(("Reminders authorization", authorized, "authorized" if authorized else "remindctl reports access is not authorized"))
    except Exception as exc:
        checks.append(("Reminders authorization", False, str(exc)))
    try:
        exists = reminder.list_exists(config.digest.reminder_list)
        checks.append(("Reminders list", exists, "configured list exists" if exists else "configured list was not found"))
    except Exception as exc:
        checks.append(("Reminders list", False, str(exc)))
    try:
        with store.lock():
            state = store.load()
        message = "valid"
        if state.get("pending_delivery"):
            message = "valid, but an uncertain delivery is pending operator review"
            checks.append(("state", False, message))
        else:
            checks.append(("state", True, message))
    except Exception as exc:
        checks.append(("state", False, str(exc)))
    for name, ok, message in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {message}")
    return 0 if all(ok for _, ok, _ in checks) else 3


def _print_preview(preview) -> None:
    if preview.title is None:
        print("No actionable maintenance findings.")
        return
    print(preview.title)
    for item in preview.updates:
        print(f"- update: {item['name']} ({item['installed']} -> {item['latest']}) [{item['entity_id']}]")
    for item in preview.batteries:
        print(f"- battery: {item['name']} ({item['percent']}%) [{item['entity_id']}]")
    for item in preview.unavailable:
        print(f"- unavailable: {item['name']} (continuous for at least {item['duration']}) [{item['entity_id']}]")
    for item in preview.backups:
        print(f"- backup: {item['name']} ({item['status']}: {item['detail']}) [{item['entity_id']}]")
    for item in preview.indicators:
        print(f"- indicator: {item['name']} ({item['detail']}) [{item['entity_id']}]")
    print("Preview only; no reminder was created.")


if __name__ == "__main__":
    raise SystemExit(main())
