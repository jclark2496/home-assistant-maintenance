# Distribution manifest

Public project contents:

- `src/home_maintenance_digest/` — deterministic core, config handling, adapters, safe workflow, and CLI.
- `skills/home-assistant-maintenance/SKILL.md` — Hermes onboarding and operating policy.
- `scripts/home-assistant-maintenance.py` — Hermes script-only cron entrypoint.
- `docs/HERMES_SETUP.md` — supported paused-first scheduling procedure.
- `fixtures/` and `tests/` — synthetic, offline verification.
- `.github/workflows/test.yml` — macOS Python build/install/test matrix.
- `config.example.json` — credential-free configuration example.

Excluded by design: credentials, local config/state, production schedules, logs, device snapshots, personal paths, identifiers, and delivery records.
