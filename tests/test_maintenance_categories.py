from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from home_maintenance_digest import (
    BackupRule,
    DigestConfig,
    IndicatorRule,
    UnavailableRule,
    backup_items,
    indicator_items,
    issue_fingerprint,
    make_preview,
    parse_duration,
    run_once,
    unavailable_items,
)
from home_maintenance_digest.config import ConfigurationError, load_config, write_configuration
from home_maintenance_digest.workflow import StateStore


NOW = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


def state(entity_id: str, value: str, **attributes):
    return {"entity_id": entity_id, "state": value, "attributes": attributes}


def history(entity_id: str, value: str, changed: str):
    return {"entity_id": entity_id, "state": value, "last_changed": changed}


class UnavailableHistoryTests(unittest.TestCase):
    def setUp(self):
        self.rule = UnavailableRule("sensor.synthetic_device", parse_duration("2h"), "Synthetic Device")
        self.config = DigestConfig(reminder_list="Synthetic", unavailable_rules=(self.rule,))
        self.states = [state("sensor.synthetic_device", "unavailable", friendly_name="Ignored Name")]

    def test_threshold_requires_history_proof_covering_entire_window(self):
        records = {"sensor.synthetic_device": [history("sensor.synthetic_device", "unavailable", "2026-11-20T12:00:00Z")]}
        result = unavailable_items(self.states, records, self.config, NOW)
        self.assertEqual(result[0]["duration"], "2h")

        too_recent = {"sensor.synthetic_device": [history("sensor.synthetic_device", "unavailable", "2026-11-20T14:00:01Z")]}
        self.assertEqual(unavailable_items(self.states, too_recent, self.config, NOW), [])
        self.assertEqual(unavailable_items(self.states, {}, self.config, NOW), [])

    def test_available_reset_inside_window_prevents_finding(self):
        records = {"sensor.synthetic_device": [
            history("sensor.synthetic_device", "unavailable", "2026-11-20T12:00:00Z"),
            history("sensor.synthetic_device", "on", "2026-11-20T14:00:00Z"),
            history("sensor.synthetic_device", "unavailable", "2026-11-20T14:30:00Z"),
        ]}
        self.assertEqual(unavailable_items(self.states, records, self.config, NOW), [])

    def test_preview_is_pure_and_defaults_to_no_unavailable_without_history(self):
        preview = make_preview(self.states, self.config, now=NOW)
        self.assertEqual(preview.unavailable, [])
        self.assertIsNone(preview.title)

    def test_moving_history_baseline_does_not_change_episode_fingerprint(self):
        first_history = {"sensor.synthetic_device": [history("sensor.synthetic_device", "unavailable", "2026-11-20T13:00:00Z")]}
        second_history = {"sensor.synthetic_device": [history("sensor.synthetic_device", "unavailable", "2026-11-20T13:05:00Z")]}
        first = make_preview(self.states, self.config, histories=first_history, now=NOW)
        second = make_preview(self.states, self.config, histories=second_history, now=NOW + timedelta(minutes=5))
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.unavailable[0]["episode_id"], "bounded-history")
        self.assertNotIn("since", first.unavailable[0])

    def test_current_last_changed_is_stable_episode_identity_and_must_cover_threshold(self):
        current = state("sensor.synthetic_device", "unavailable")
        current["last_changed"] = "2026-11-20T12:15:00Z"
        records = {"sensor.synthetic_device": [history("sensor.synthetic_device", "unavailable", "2026-11-20T13:00:00Z")]}
        item = unavailable_items([current], records, self.config, NOW)[0]
        self.assertEqual(item["episode_id"], "2026-11-20T12:15:00+00:00")

        current["last_changed"] = "2026-11-20T14:00:01Z"
        self.assertEqual(unavailable_items([current], records, self.config, NOW), [])

    def test_moving_synthetic_baseline_is_duplicate_suppressed_across_polls(self):
        class Source:
            def states(self):
                return self_states

            def history(self, entity_ids, *, start, end):
                return {entity_ids[0]: [history(entity_ids[0], "unavailable", start.isoformat())]}

        class Reminder:
            def __init__(self):
                self.calls = []
                self.markers = set()

            def add(self, **kwargs):
                self.calls.append(kwargs)
                self.markers.add(kwargs["marker"])

            def find_by_marker(self, *, list_name, marker):
                return [{"notes": marker}] if marker in self.markers else []

        self_states = self.states
        reminder = Reminder()
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            first = run_once(source=Source(), reminder=reminder, state_store=store, config=self.config, now=lambda: NOW)
            second = run_once(source=Source(), reminder=reminder, state_store=store, config=self.config, now=lambda: NOW + timedelta(minutes=5))
        self.assertEqual((first.outcome, second.outcome), ("reminder_added", "duplicate_suppressed"))
        self.assertEqual(len(reminder.calls), 1)


class BackupTests(unittest.TestCase):
    def test_failed_and_stale_are_actionable_but_unknown_is_not_called_stale(self):
        rules = (
            BackupRule("sensor.failed_backup", failure_states=frozenset({"failed"})),
            BackupRule("sensor.stale_backup", max_age=parse_duration("24h")),
            BackupRule("sensor.unknown_backup", max_age=parse_duration("24h")),
        )
        config = DigestConfig(reminder_list="Synthetic", backup_rules=rules)
        states = [
            state("sensor.failed_backup", "FAILED"),
            state("sensor.stale_backup", "2026-11-18T14:00:00Z"),
            state("sensor.unknown_backup", "unknown"),
        ]
        result = backup_items(states, config, NOW)
        self.assertEqual([(item["entity_id"], item["status"]) for item in result], [("sensor.failed_backup", "failed"), ("sensor.stale_backup", "stale")])

    def test_timezone_offsets_and_explicit_timezone_for_naive_timestamp(self):
        rules = (
            BackupRule("sensor.offset", max_age=parse_duration("2h")),
            BackupRule("sensor.naive", max_age=parse_duration("2h"), timestamp_timezone="America/Chicago"),
            BackupRule("sensor.naive_unknown", max_age=parse_duration("2h")),
        )
        config = DigestConfig(reminder_list="Synthetic", backup_rules=rules)
        states = [
            state("sensor.offset", "2026-11-20T06:00:00-06:00"),
            state("sensor.naive", "2026-11-20T06:00:00"),
            state("sensor.naive_unknown", "2026-11-20T06:00:00"),
        ]
        result = backup_items(states, config, NOW)
        self.assertEqual({item["entity_id"] for item in result}, {"sensor.offset", "sensor.naive"})

    def test_timestamp_attribute_is_explicit_not_guessed(self):
        rule = BackupRule("sensor.backup_status", failure_states=frozenset({"failed"}), max_age=parse_duration("1d"), timestamp_attribute="last_success")
        config = DigestConfig(reminder_list="Synthetic", backup_rules=(rule,))
        result = backup_items([state("sensor.backup_status", "ok", last_success="2026-11-18T12:00:00Z")], config, NOW)
        self.assertEqual(result[0]["status"], "stale")

    def test_ambiguous_and_nonexistent_naive_local_times_fail_closed(self):
        rules = (
            BackupRule("sensor.ambiguous", max_age=parse_duration("1h"), timestamp_timezone="America/Chicago"),
            BackupRule("sensor.nonexistent", max_age=parse_duration("1h"), timestamp_timezone="America/Chicago"),
        )
        config = DigestConfig(reminder_list="Synthetic", backup_rules=rules)
        states = [
            state("sensor.ambiguous", "2026-11-01T01:30:00"),
            state("sensor.nonexistent", "2026-03-08T02:30:00"),
        ]
        self.assertEqual(backup_items(states, config, NOW), [])


class IndicatorTests(unittest.TestCase):
    def test_state_and_numeric_threshold_mappings(self):
        rules = (
            IndicatorRule("binary_sensor.filter", name="HVAC Filter", problem_states=frozenset({"on"})),
            IndicatorRule("sensor.filter_life", operator="lte", threshold=10, unit="%"),
        )
        config = DigestConfig(reminder_list="Synthetic", indicator_rules=rules)
        states = [state("binary_sensor.filter", "ON"), state("sensor.filter_life", "9.5", unit_of_measurement="%")]
        result = indicator_items(states, config)
        self.assertEqual({item["entity_id"] for item in result}, {"binary_sensor.filter", "sensor.filter_life"})

    def test_numeric_unit_mismatch_and_nonfinite_values_are_ignored(self):
        rule = IndicatorRule("sensor.life", operator="lte", threshold=10, unit="%")
        config = DigestConfig(reminder_list="Synthetic", indicator_rules=(rule,))
        self.assertEqual(indicator_items([state("sensor.life", "9", unit_of_measurement="h")], config), [])
        self.assertEqual(indicator_items([state("sensor.life", "nan", unit_of_measurement="%")], config), [])

    def test_new_categories_deduplicate_same_entity_by_documented_priority(self):
        entity = "sensor.shared"
        config = DigestConfig(
            reminder_list="Synthetic",
            unavailable_rules=(UnavailableRule(entity, parse_duration("1h")),),
            backup_rules=(BackupRule(entity, failure_states=frozenset({"unavailable"})),),
            indicator_rules=(IndicatorRule(entity, problem_states=frozenset({"unavailable"})),),
        )
        histories = {entity: [history(entity, "unavailable", "2026-11-20T12:00:00Z")]}
        preview = make_preview([state(entity, "unavailable")], config, histories=histories, now=NOW)
        self.assertEqual(len(preview.unavailable), 1)
        self.assertEqual(preview.backups, [])
        self.assertEqual(preview.indicators, [])

    def test_new_finding_fingerprint_state_duplicate_and_reset_cycle(self):
        class Source:
            def __init__(self, states): self.current = states
            def states(self): return self.current
            def history(self, entity_ids, *, start, end): return {}

        class Reminder:
            def __init__(self): self.calls = []; self.markers = set()
            def add(self, **kwargs): self.calls.append(kwargs); self.markers.add(kwargs["marker"])
            def find_by_marker(self, *, list_name, marker): return [{"notes": marker}] if marker in self.markers else []

        rule = IndicatorRule("sensor.fault", problem_states=frozenset({"fault", "error"}))
        config = DigestConfig(reminder_list="Synthetic", indicator_rules=(rule,))
        source = Source([state("sensor.fault", "fault")])
        reminder = Reminder()
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "state.json")
            first = run_once(source=source, reminder=reminder, state_store=store, config=config, now=lambda: NOW)
            duplicate = run_once(source=source, reminder=reminder, state_store=store, config=config, now=lambda: NOW)
            self.assertEqual((first.outcome, duplicate.outcome), ("reminder_added", "duplicate_suppressed"))
            self.assertEqual(store.load()["last_indicator_count"], 1)
            old_fingerprint = first.fingerprint
            source.current = [state("sensor.fault", "ok")]
            self.assertEqual(run_once(source=source, reminder=reminder, state_store=store, config=config, now=lambda: NOW).outcome, "clean")
            source.current = [state("sensor.fault", "error")]
            recurrence = run_once(source=source, reminder=reminder, state_store=store, config=config, now=lambda: NOW)
            self.assertEqual(recurrence.outcome, "reminder_added")
            self.assertNotEqual(recurrence.fingerprint, old_fingerprint)
            self.assertEqual(len(reminder.calls), 2)


class NewConfigurationTests(unittest.TestCase):
    def test_safe_defaults_leave_all_new_categories_off(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_configuration(directory=path, base_url="http://ha.example:8123", reminder_list="Synthetic", token="fake")
            config = load_config(path).digest
            self.assertEqual(config.unavailable_rules, ())
            self.assertEqual(config.backup_rules, ())
            self.assertEqual(config.indicator_rules, ())

    def test_empty_new_categories_preserve_legacy_fingerprint(self):
        updates = [{"entity_id": "update.synthetic", "installed": "1", "latest": "2"}]
        batteries = [{"entity_id": "sensor.synthetic_battery", "percent": "20"}]
        self.assertEqual(
            issue_fingerprint(updates, batteries, "Synthetic", (), (), ()),
            "7ea6155bc7a2e9d9098c7ec31a01f9d03053a40c6ae4ef701b52cb264876e249",
        )

    def test_config_parses_durations_and_numeric_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_configuration(directory=path, base_url="http://ha.example:8123", reminder_list="Synthetic", token="fake")
            raw = json.loads((path / "config.json").read_text())
            raw["unavailable_entities"] = [{"entity_id": "sensor.offline", "threshold": "90m"}]
            raw["backup_entities"] = [{"entity_id": "sensor.backup", "max_age": "2d", "timestamp_timezone": "UTC"}]
            raw["maintenance_indicators"] = [{"entity_id": "sensor.filter", "operator": "lte", "threshold": 10, "unit": "%"}]
            (path / "config.json").write_text(json.dumps(raw))
            loaded = load_config(path).digest
            self.assertEqual(loaded.unavailable_rules[0].threshold, timedelta(minutes=90))
            self.assertEqual(loaded.backup_rules[0].max_age, timedelta(days=2))

    def test_invalid_mappings_are_rejected(self):
        invalid = [
            {"maintenance_indicators": [{"entity_id": "sensor.bad", "problem_states": ["on"], "operator": "lte", "threshold": 1}]},
            {"maintenance_indicators": [{"entity_id": "sensor.bad", "operator": "bogus", "threshold": 1}]},
            {"unavailable_entities": [{"entity_id": "sensor.bad", "threshold": "two hours"}]},
            {"backup_entities": [{"entity_id": "sensor.bad"}]},
            {"backup_entities": [{"entity_id": "sensor.bad", "max_age": "1d", "guessed_schema": True}]},
        ]
        for update in invalid:
            with self.subTest(update=update), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                write_configuration(directory=path, base_url="http://ha.example:8123", reminder_list="Synthetic", token="fake")
                raw = json.loads((path / "config.json").read_text())
                raw.update(update)
                (path / "config.json").write_text(json.dumps(raw))
                with self.assertRaises(ConfigurationError):
                    load_config(path)

    def test_duration_units_and_invalid_values(self):
        self.assertEqual(parse_duration("30s"), timedelta(seconds=30))
        self.assertEqual(parse_duration("15m"), timedelta(minutes=15))
        self.assertEqual(parse_duration("2h"), timedelta(hours=2))
        self.assertEqual(parse_duration("3d"), timedelta(days=3))
        self.assertEqual(parse_duration("1w"), timedelta(weeks=1))
        for value in ("", "2 hours", "0h", "-1h", True):
            with self.assertRaises(ValueError, msg=str(value)):
                parse_duration(value)


if __name__ == "__main__":
    unittest.main()
