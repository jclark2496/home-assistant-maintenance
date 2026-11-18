# Home Assistant Maintenance Workflow

A production-oriented Hermes workflow for reading Home Assistant maintenance signals and creating a deduplicated Apple Reminder on macOS. Home Assistant access is read-only (`GET /api/` and `GET /api/states`). Reminder writes are explicit, marker-verified, locked, and never blindly retried after uncertain delivery.

> **Start with Hermes:** install the included skill, then let Hermes guide the local credential prompt, doctor, preview, and optional paused schedule. Do not paste a Home Assistant token into chat.

## Set it up with Hermes

Give Hermes this request:

> Install the Home Assistant Maintenance Workflow from https://github.com/jclark2496/home-assistant-maintenance. Read its included skill and setup instructions first. Check prerequisites, guide me through secure local credential entry and Apple Reminders permissions, verify a first delivery with my approval, then help me enable a recurring schedule. Do not change Home Assistant devices or install updates.

The repository must be accessible to your GitHub account. Hermes handles the commands below; you still approve macOS permissions and enter your token locally. Never paste credentials into chat.

## Installation reference for Hermes on macOS

Prerequisites: Python 3.11+, [Hermes Agent](https://hermes-agent.nousresearch.com/docs/), Home Assistant network access, and `remindctl` with Reminders permission.

```bash
# Clone this repository, then:
cd home-assistant-maintenance
python3 -m venv ~/.local/share/home-assistant-maintenance/venv
~/.local/share/home-assistant-maintenance/venv/bin/python -m pip install .
mkdir -p ~/.hermes/skills/home-assistant-maintenance
cp skills/home-assistant-maintenance/SKILL.md ~/.hermes/skills/home-assistant-maintenance/SKILL.md
```

Start a fresh Hermes session so the new skill is discovered. Ask:

```text
Use the home-assistant-maintenance skill to help me configure, doctor, and preview the workflow. Do not send or schedule anything.
```

Hermes should ask you to run this **locally**; hidden input keeps the token out of chat, shell arguments, logs, and the repository:

```bash
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance configure
```

Then complete the production gate:

```bash
ha-maintenance doctor       # read-only checks
ha-maintenance preview      # read-only Home Assistant fetch; no Reminder write
ha-maintenance send         # refuses to write
ha-maintenance send --yes   # explicit write; run only after approving the preview
```

`configure` writes `~/.config/home-assistant-maintenance/config.json` and `credentials.json` with owner-only permissions. The token is not accepted as a CLI argument. Edit `config.json` locally to change thresholds, entity exclusions, the existing Reminders list, title limits, timeouts, or state location. Never commit local config or credentials.

See [docs/HERMES_SETUP.md](docs/HERMES_SETUP.md) for the supported, paused-first Hermes scheduling workflow. This repository does not install a schedule and its tests never send a Reminder.

## Safety model

- **Read-only source:** the Home Assistant adapter only performs GET requests.
- **Explicit destination write:** `send --yes` is required.
- **Verified delivery:** each reminder carries a deterministic marker in notes and is read back from the configured list before deduplication state is confirmed.
- **No blind retry:** if `remindctl` times out, fails, or cannot be verified, state remains pending and later sends are blocked. After inspecting Reminders, the operator must run `resolve --outcome delivered --yes` or `resolve --outcome not-delivered --yes`.
- **Crash-safe ordering:** pending intent is atomically persisted before the Reminder call. A crash after creation can be reconciled by marker readback without a second write.
- **Concurrent-run lock:** a non-blocking file lock permits only one send/state transition at a time.
- **Corrupt state fails closed:** invalid state blocks writes. `state-reset --yes` preserves the original as a private backup, but may permit a duplicate and should follow manual review.
- **Private state:** credentials, state, lock, and backups use owner-only modes. State contains hashes/counts/markers, not tokens or HA snapshots.
- **Bounded errors:** adapters report status/type, not tokens, response bodies, reminder contents, or command output.

## Doctor and operations

`doctor` verifies config structure and secret-file permissions, authenticates to Home Assistant read-only, checks `remindctl status`, confirms the configured list exists, and validates local state. It does not create or change reminders.

```bash
ha-maintenance doctor
ha-maintenance preview --json
ha-maintenance resolve --outcome delivered --yes
ha-maintenance resolve --outcome not-delivered --yes
ha-maintenance state-reset --yes
```

A low battery percentage or update version change changes the fingerprint and may create a new reminder. A clean run resets the confirmed fingerprint, so a later recurrence can notify again. Existing reminders are never completed or deleted.

## Local development (secondary)

All tests are offline and use synthetic entities, fake destinations, and temporary state:

```bash
python3 -m pip install '.[dev]'
python3 -m unittest discover -s tests -v
python3 -m build
```

CI builds and installs the wheel on macOS with Python 3.11–3.13, runs the offline suite, and smoke-tests the installed CLI.

## Scope

- macOS and Apple Reminders via `remindctl` are supported.
- The core package does not require Hermes; Hermes is the primary installation and scheduling experience.
- No schedule, production send, Home Assistant mutation, or Reminders mutation occurs during installation or testing.
- **Email is a future adapter and is not implemented.**

## License

MIT
