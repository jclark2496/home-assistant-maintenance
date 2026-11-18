from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from home_maintenance_digest.adapters import HomeAssistantHttpSource, RemindctlAdapter, _contains_list_name
from home_maintenance_digest.cli import build_parser, main
from home_maintenance_digest.config import write_configuration


class AdapterTests(unittest.TestCase):
    def test_list_name_parser_matches_current_remindctl_shape(self):
        payload = [{"id": "synthetic", "title": "Home Maintenance", "reminderCount": 0, "overdueCount": 0}]
        self.assertTrue(_contains_list_name(payload, "home maintenance"))
        self.assertFalse(_contains_list_name(payload, "Missing"))

    @patch("home_maintenance_digest.adapters.urlopen")
    def test_home_assistant_uses_get_and_bearer_header_without_subprocess(self, mocked_urlopen):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = io.StringIO("[]")
        mocked_urlopen.return_value = response
        source = HomeAssistantHttpSource(base_url="http://ha.example:8123", token="fake")
        self.assertEqual(source.states(), [])
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake")

    @patch("home_maintenance_digest.adapters.subprocess.run")
    def test_remindctl_add_uses_argv_and_safe_noninteractive_flags(self, mocked_run):
        mocked_run.return_value = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        RemindctlAdapter(Path("/example/remindctl")).add(
            title="Synthetic title",
            list_name="Home Maintenance",
            due=__import__("datetime").date(2026, 1, 5),
            marker="[home-assistant-maintenance:synthetic]",
        )
        argv = mocked_run.call_args.args[0]
        self.assertEqual(argv[0], "/example/remindctl")
        self.assertIn("--json", argv)
        self.assertIn("--no-input", argv)
        self.assertIn("--notes", argv)
        self.assertFalse(mocked_run.call_args.kwargs.get("shell", False))


class CliSafetyTests(unittest.TestCase):
    def test_parser_has_no_token_argument(self):
        help_text = build_parser().format_help().lower()
        self.assertNotIn("--token", help_text)

    def test_send_without_yes_refuses_before_network_or_reminder_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_configuration(directory=path, base_url="http://ha.example:8123", reminder_list="Home Maintenance", token="fake")
            with patch("home_maintenance_digest.cli.HomeAssistantHttpSource.states") as states, patch("home_maintenance_digest.cli.RemindctlAdapter.add") as add:
                result = main(["--config-dir", str(path), "send"])
            self.assertEqual(result, 2)
            states.assert_not_called()
            add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
