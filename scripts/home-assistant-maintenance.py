#!/usr/bin/env python3
"""Hermes no-agent job entrypoint. Install under ~/.hermes/scripts/."""

from home_maintenance_digest.cli import main

raise SystemExit(main(["send", "--yes"]))
