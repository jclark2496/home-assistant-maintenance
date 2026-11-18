from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from home_maintenance_digest import DigestConfig, StateStore, battery_items, build_title, make_preview, run_once, update_items
from home_maintenance_digest.config import ConfigurationError, load_config, write_configuration
from home_maintenance_digest.workflow import CorruptStateError, LockBusyError, UncertainDeliveryError, resolve_pending

ROOT = Path(__file__).resolve().parents[1]


class FakeSource:
    def __init__(self, states):
        self.payload = states
        self.calls = 0

    def states(self):
        self.calls += 1
        return self.payload


class FakeReminder:
    def __init__(self, *, fail=False, readback=True):
        self.fail = fail
        self.readback = readback
        self.calls = []
        self.markers = set()

    def add(self, **kwargs):
        self.calls.append(kwargs)
        if not self.fail:
            self.markers.add(kwargs["marker"])
        if self.fail:
            raise RuntimeError("synthetic failure")

    def find_by_marker(self, *, list_name, marker):
        return [{"notes": marker}] if self.readback and marker in self.markers else []


class DigestWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.states = json.loads((ROOT / "fixtures" / "home_assistant_states.synthetic.json").read_text())
        self.config = DigestConfig(
            reminder_list="Home Maintenance",
            special_battery_thresholds={"sensor.example_lock_battery": 30},
            special_battery_names={"sensor.example_lock_battery": "Entry Lock Battery"},
            ignored_battery_entities=frozenset({"sensor.example_phone_battery"}),
        )
        self.now = lambda: datetime(2026, 1, 5, 9, 0, 0)

    def test_fixture_filtering_and_thresholds(self):
        updates = update_items(self.states, self.config)
        batteries = battery_items(self.states, self.config)
        self.assertEqual([item["entity_id"] for item in updates], ["update.example_hub_firmware"])
        self.assertEqual([item["entity_id"] for item in batteries], ["sensor.example_window_battery", "sensor.example_lock_battery"])

    def test_update_exclusion(self):
        config = DigestConfig(reminder_list="Home Maintenance", ignored_update_entities=frozenset({"update.example_hub_firmware"}))
        self.assertEqual(update_items(self.states, config), [])

    def test_title_is_bounded(self):
        config = DigestConfig(reminder_list="Home Maintenance", max_title_length=80)
        title = build_title(update_items(self.states, config), battery_items(self.states, config), config)
        self.assertLessEqual(len(title), 80)
        self.assertTrue(title.endswith("…"))

    def test_preview_has_no_side_effect(self):
        preview = make_preview(self.states, self.config)
        self.assertEqual(len(preview.updates), 1)
        self.assertEqual(len(preview.batteries), 2)

    def test_identical_issue_set_is_suppressed_after_verified_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            reminder = FakeReminder()
            first = run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            second = run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            self.assertEqual(first.outcome, "reminder_added")
            self.assertEqual(second.outcome, "duplicate_suppressed")
            self.assertEqual(len(reminder.calls), 1)

    def test_changed_battery_value_creates_new_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            reminder = FakeReminder()
            run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            changed = json.loads(json.dumps(self.states))
            next(item for item in changed if item["entity_id"] == "sensor.example_window_battery")["state"] = "23"
            run_once(source=FakeSource(changed), reminder=reminder, state_store=store, config=self.config, now=self.now)
            self.assertEqual(len(reminder.calls), 2)

    def test_clean_run_allows_later_recurrence(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            reminder = FakeReminder()
            run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            run_once(source=FakeSource([]), reminder=reminder, state_store=store, config=self.config, now=self.now)
            run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            self.assertEqual(len(reminder.calls), 2)

    def test_failure_leaves_pending_and_never_blind_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            reminder = FakeReminder(fail=True, readback=False)
            with self.assertRaises(UncertainDeliveryError):
                run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            with self.assertRaises(UncertainDeliveryError):
                run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            self.assertEqual(len(reminder.calls), 1)
            self.assertIn("pending_delivery", store.load())

    def test_error_with_successful_readback_is_confirmed(self):
        class ErrorAfterWrite(FakeReminder):
            def add(self, **kwargs):
                self.calls.append(kwargs)
                self.markers.add(kwargs["marker"])
                raise RuntimeError("lost response")
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            result = run_once(source=FakeSource(self.states), reminder=ErrorAfterWrite(), state_store=store, config=self.config, now=self.now)
            self.assertEqual(result.outcome, "reminder_added_readback")
            self.assertNotIn("pending_delivery", store.load())

    def test_pending_is_reconciled_without_new_add(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            reminder = FakeReminder(fail=True, readback=False)
            with self.assertRaises(UncertainDeliveryError):
                run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            marker = store.load()["pending_delivery"]["marker"]
            reminder.fail = False
            reminder.readback = True
            reminder.markers.add(marker)
            result = run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            self.assertEqual(result.outcome, "delivery_reconciled")
            self.assertEqual(len(reminder.calls), 1)

    def test_operator_not_delivered_resolution_allows_later_explicit_run(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            reminder = FakeReminder(fail=True, readback=False)
            with self.assertRaises(UncertainDeliveryError):
                run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            resolve_pending(state_store=store, outcome="not-delivered", now=self.now())
            reminder.fail = False
            reminder.readback = True
            result = run_once(source=FakeSource(self.states), reminder=reminder, state_store=store, config=self.config, now=self.now)
            self.assertEqual(result.outcome, "reminder_added")

    def test_corrupt_state_blocks_send(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("not-json")
            with self.assertRaises(CorruptStateError):
                run_once(source=FakeSource(self.states), reminder=FakeReminder(), state_store=StateStore(path), config=self.config, now=self.now)

    def test_state_reset_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("not-json")
            store = StateStore(path)
            backup = store.reset_with_backup(self.now())
            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_text(), "not-json")
            self.assertEqual(store.load()["schema_version"], 1)

    def test_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            with store.lock():
                with self.assertRaises(LockBusyError):
                    with store.lock():
                        pass

    def test_state_file_permissions_are_restrictive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            run_once(source=FakeSource([]), reminder=FakeReminder(), state_store=StateStore(path), config=self.config, now=self.now)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class ConfigurationTests(unittest.TestCase):
    def test_configuration_files_are_private_and_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_configuration(directory=path, base_url="http://ha.example:8123", reminder_list="Home Maintenance", token="fake")
            self.assertEqual(stat.S_IMODE((path / "credentials.json").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((path / "config.json").stat().st_mode), 0o600)
            loaded = load_config(path)
            self.assertEqual(loaded.token, "fake")

    def test_insecure_credentials_permissions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_configuration(directory=path, base_url="http://ha.example:8123", reminder_list="Home Maintenance", token="fake")
            os.chmod(path / "credentials.json", 0o644)
            with self.assertRaises(ConfigurationError):
                load_config(path)

    def test_invalid_config_value_is_reported_without_traceback_type_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_configuration(directory=path, base_url="http://ha.example:8123", reminder_list="Home Maintenance", token="fake")
            config = json.loads((path / "config.json").read_text())
            config["special_battery_thresholds"] = None
            (path / "config.json").write_text(json.dumps(config))
            with self.assertRaisesRegex(ConfigurationError, "invalid value"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
