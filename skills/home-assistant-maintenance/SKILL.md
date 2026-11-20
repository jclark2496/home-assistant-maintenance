---
name: home-assistant-maintenance
description: "Use when installing or operating the read-only Home Assistant maintenance check with explicit Apple Reminders delivery."
version: 1.0.0
author: Home Assistant Maintenance contributors
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [home-assistant, reminders, maintenance, macos]
    required_commands: [ha-maintenance, remindctl]
---

# Home Assistant Maintenance

Use the deterministic CLI; do not recreate its Home Assistant or Reminders logic in an agent prompt.

## Safety rules

- `preview` and `doctor` are read-only. Preview may query bounded Home Assistant history for explicitly configured unavailable entities.
- Never request, paste, print, or pass a Home Assistant token in chat or command arguments. The user enters it locally with `ha-maintenance configure`.
- Never run `send --yes`, `resolve`, or `state-reset` without the user's explicit request.
- Never auto-retry an uncertain delivery. Run `doctor`, inspect the configured Reminders list, and let the user choose `resolve --outcome delivered|not-delivered --yes`.
- Do not create or resume a Hermes schedule until doctor, preview, and one user-approved manual send have been reviewed.
- Email is not implemented.

## Onboarding

1. Ask the user to run `ha-maintenance configure` locally so hidden token input stays on their Mac.
2. Run `ha-maintenance doctor` and fix every failure.
3. Inspect `config.example.json` and help the user opt in only entities whose integration semantics they have verified. Leave unavailable, backup, and indicator lists empty otherwise; never guess backup fields or alarm/fault states.
4. Run `ha-maintenance preview`; explain that it performs only Home Assistant GET requests. For unavailable checks, missing/partial history fails closed. For backups, unknown or timezone-ambiguous timestamps are not called stale.
5. Only with explicit approval, run `ha-maintenance send --yes`.
6. For scheduling, follow `docs/HERMES_SETUP.md`. Create the job paused first and verify it with `hermes cron list`; do not run it as a schedule test because that can create a reminder.

## Optional maintenance mappings

- `unavailable_entities`: explicit entity plus persistence duration. Do not broaden this to all unavailable entities.
- `backup_entities`: explicit failure states and/or explicit ISO timestamp source plus maximum age. Home Assistant has no universal backup entity schema.
- `maintenance_indicators`: exact problem states or an explicit numeric operator, threshold, and optional unit. Do not infer generic alarm states.
- New categories default off. Review the complete preview after every mapping change; a changed finding changes dedup state.

## Commands

```bash
ha-maintenance doctor
ha-maintenance preview
ha-maintenance preview --json
ha-maintenance send --yes
ha-maintenance resolve --outcome delivered --yes
ha-maintenance resolve --outcome not-delivered --yes
ha-maintenance state-reset --yes
```

A successful clean or duplicate-suppressed scheduled run is intentionally silent. A newly confirmed reminder prints only counts, not credentials.
