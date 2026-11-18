# Hermes setup and scheduling

This workflow uses Hermes **script-only cron (`--no-agent`)** because the Python package deterministically decides whether to send a reminder. No LLM is needed on each run. The commands below follow the current official documentation:

- [Script-Only Cron Jobs](https://hermes-agent.nousresearch.com/docs/guides/cron-script-only)
- [Scheduled Tasks (Cron)](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron)
- [Cron Troubleshooting](https://hermes-agent.nousresearch.com/docs/guides/cron-troubleshooting)

The checked-in Hermes skill also requires doctor/preview/manual approval before activation.

## 1. Install the package and skill

From a trusted checkout:

```bash
python3 -m venv ~/.local/share/home-assistant-maintenance/venv
~/.local/share/home-assistant-maintenance/venv/bin/python -m pip install .
mkdir -p ~/.hermes/skills/home-assistant-maintenance ~/.hermes/scripts
cp skills/home-assistant-maintenance/SKILL.md ~/.hermes/skills/home-assistant-maintenance/SKILL.md
cp scripts/home-assistant-maintenance.py ~/.hermes/scripts/home-assistant-maintenance.py
chmod 700 ~/.hermes/scripts/home-assistant-maintenance.py
```

Hermes requires cron scripts to resolve inside `~/.hermes/scripts/`. `--interpreter` pins this Python job to the user-managed virtual environment, rather than Hermes' own environment. Start a fresh Hermes session after installing the skill.

## 2. Configure locally and pass the production gate

```bash
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance configure
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance doctor
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance preview
```

Do not paste the token into Hermes. `configure` uses hidden terminal input and owner-only files. Fix every doctor failure. Review the complete preview.

If desired, manually approve exactly one real write:

```bash
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance send --yes
```

Confirm the Reminder exists in the configured list before scheduling. This repository and its tests do not perform that live verification for you.

## 3. Create a paused job

Choose an IANA timezone for your location; do not copy the placeholder literally. Creating the job paused prevents an accidental reminder during setup:

```bash
hermes cron create "0 9 * * 1" \
  --no-agent \
  --script home-assistant-maintenance.py \
  --interpreter ~/.local/share/home-assistant-maintenance/venv/bin/python \
  --timezone Area/City \
  --deliver local \
  --name "Home Assistant maintenance" \
  --paused \
  --paused-reason "Awaiting doctor, preview, and manual-send review"
```

`--deliver local` stores non-empty script output locally. Clean and duplicate-suppressed runs produce no stdout and are silent. A nonzero exit is still recorded as a failure. You may select another configured Hermes delivery target after reviewing its privacy implications.

Inspect only; do not use `hermes cron run` as a harmless test because this script's job is to send a Reminder:

```bash
hermes cron list
hermes cron doctor
```

When the user explicitly approves activation after the gate:

```bash
hermes cron resume "Home Assistant maintenance"
```

No command in this document is run automatically.

## Operations

```bash
hermes cron list
hermes cron pause "Home Assistant maintenance"
hermes cron resume "Home Assistant maintenance"
hermes cron runs <job_id>
hermes cron doctor
```

A running Hermes gateway normally drives recurring jobs. The official docs note that bare `hermes cron tick` can run `no_agent` jobs, but a regular CLI chat session does not fire schedules automatically.

## Uncertain delivery

The package never retries a write when delivery is uncertain. A pending marker blocks later writes. Run `doctor`, inspect the configured Reminders list, then choose one explicit resolution:

```bash
ha-maintenance resolve --outcome delivered --yes
ha-maintenance resolve --outcome not-delivered --yes
```

`delivered` confirms dedup state. `not-delivered` clears the pending attempt but does not send; a later `send --yes` or scheduled run can then write. If you cannot establish what happened, keep the job paused and leave the pending state intact.
