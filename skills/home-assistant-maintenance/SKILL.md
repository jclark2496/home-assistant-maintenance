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

- `preview` and `doctor` are read-only.
- Never request, paste, print, or pass a Home Assistant token in chat or command arguments. The user enters it locally with `ha-maintenance configure`.
- Never run `send --yes`, `resolve`, or `state-reset` without the user's explicit request.
- Never auto-retry an uncertain delivery. Run `doctor`, inspect the configured Reminders list, and let the user choose `resolve --outcome delivered|not-delivered --yes`.
- Do not create or resume a Hermes schedule until doctor, preview, and one user-approved manual send have been reviewed.
- Email is not implemented.

## Onboarding

1. Ask the user to run `ha-maintenance configure` locally so hidden token input stays on their Mac.
2. Run `ha-maintenance doctor` and fix every failure.
3. Run `ha-maintenance preview`; explain that it performs only Home Assistant GET requests.
4. Only with explicit approval, run `ha-maintenance send --yes`.
5. For scheduling, follow `docs/HERMES_SETUP.md`. Create the job paused first and verify it with `hermes cron list`; do not run it as a schedule test because that can create a reminder.

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
