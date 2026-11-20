# Home Assistant Maintenance Workflow

**Turn Home Assistant maintenance signals—low batteries, updates, persistent outages, backup problems, and integration-reported faults—into actionable Apple Reminders, with Hermes handling setup and scheduled checks.**

A smart home needs maintenance, too. Door locks run low on batteries. Alarm keypads and contact sensors need attention. Home Assistant, integrations, and device firmware have updates waiting. Instead of checking every device and update screen yourself, this workflow gathers those maintenance items into a reminder you can act on.

Built for **Hermes on a Mac + Home Assistant + Apple Reminders**. Your home stays under your control: the workflow reads status, but never installs updates, unlocks doors, arms or disarms alarms, or changes devices.

## Features

### Low-battery reminders

- **Smart door locks:** catch low batteries before a lock stops responding.
- **Alarm and security devices:** track battery levels for compatible alarm keypads, door/window contacts, and motion sensors.
- **Other battery-powered devices:** include temperature, humidity, air-quality, and other sensors exposed through Home Assistant.
- **Your own thresholds:** use a default low-battery threshold or set a higher threshold for a particular device, such as a door lock.
- **Control what matters:** exclude devices you do not want in your maintenance digest and give battery items clearer names.
- **Ignore invalid readings:** unavailable, nonnumeric, negative, and out-of-range battery percentages are not treated as low batteries.

Battery checks require Home Assistant to expose a numeric percentage with `%` as the unit and either the battery device class or `battery` in the entity ID. Binary low-battery warnings and devices without a percentage are not currently supported. Device examples above are supported through those Home Assistant entities—not separate vendor integrations.

### Home Assistant and device update reminders

- **Home Assistant upgrades:** see available Core, OS, Supervisor, or add-on updates when your installation exposes them as update entities.
- **Integration and dashboard updates:** include HACS integrations and custom cards when they expose an update entity.
- **Device firmware updates:** include supported hubs and other devices whose integrations report available firmware updates.
- **Version details:** see installed and available versions where Home Assistant provides them.
- **Update exclusions:** leave selected update entities out of the digest.

The workflow reads `update.*` entities whose state is `on`. It does not independently check vendor websites or discover updates that Home Assistant does not expose.

### Persistent unavailable entities

- Opt in individual entities with `unavailable_entities`; the safe default is an empty list.
- Set a duration such as `90m`, `2h`, or `1d` for each entity.
- A finding is emitted only when the current state is exactly `unavailable` **and** bounded Home Assistant history proves it stayed unavailable for the entire threshold window.
- A normal state inside the window resets persistence. Missing, partial, or malformed history is treated as insufficient evidence, not as an outage.
- The fingerprint uses the current state's stable `last_changed` when available, never the history API's moving start-of-window baseline. If `last_changed` is missing or malformed, it falls back to the entity ID; this prevents repeated reminders while continuously unavailable, but an outage that clears and recurs entirely between polls may remain suppressed until a clean poll is observed.

This is intentionally not an automatic scan of every unavailable entity. Explicit selection avoids reminders for intentionally sleeping, disabled, or intermittently connected devices. Preview uses read-only `GET` requests, including the history request when this category is configured.

### Backup health

Home Assistant and backup integrations do not expose one universal entity schema. Configure the entity and its meaning explicitly under `backup_entities`:

- `failure_states` matches exact configured states, case-insensitively.
- `max_age` checks an ISO 8601 completion timestamp from the entity state, or from the explicitly named `timestamp_attribute`.
- Offset-aware timestamps are honored. A naive timestamp requires an explicit IANA `timestamp_timezone` such as `America/Chicago`.
- Missing, `unknown`, malformed, or timezone-ambiguous timestamps are **not** labeled stale. The workflow reports only configured failures and timestamps proven older than `max_age`.

Use separate rules if an integration exposes status and last-success time as separate entities. The examples are synthetic; inspect your integration's actual entities before configuring them.

### Integration-provided maintenance indicators

Configure filters, consumables, service flags, and faults under `maintenance_indicators`. Each mapping must use exactly one explicit mode:

- `problem_states`: exact configured states such as `on`, `replace`, `fault`, or `error`; or
- `operator` + numeric `threshold`: `lt`, `lte`, `gt`, `gte`, `eq`, or `ne`, optionally requiring an exact Home Assistant unit with `unit`.

Values may come from the entity state or an explicit `value_attribute`. The workflow does not guess alarm states, interpret arbitrary text, or treat every binary sensor as a fault. Nonnumeric/nonfinite values and mismatched units do not trigger numeric rules.

### Delivered where you already manage tasks

- **Apple Reminders delivery:** send a consolidated maintenance reminder to a list you choose.
- **Scheduled checks through Hermes:** choose a recurring schedule during setup, with your approval before activation.
- **Preview before sending:** review real findings without creating any reminders.
- **Duplicate suppression:** unchanged findings do not create another reminder when using the same tracking state.
- **Verified local delivery:** read the created reminder back from the selected list before confirming success.

This creates **one digest reminder per changed set of findings**, not a separate task for every device. Existing reminders are never automatically completed or deleted. A changed battery percentage or update version can produce a new digest even if the underlying maintenance task is still outstanding.

## What a reminder looks like

Illustrative example—not data from a real home:

> **Review Home Assistant: updates (1): Home Assistant Core 2026.10.0→2026.10.1 | low batteries (1): Front Door Lock 18% | maintenance (3): Garage Hub unavailable 2h; Home Assistant Backup backup stale; HVAC Filter on**

The default title shows up to six updates, eight battery items, and eight additional maintenance findings, with a `+N more` summary when needed. Item limits and maximum title length are configurable. The current reminder is a compact digest, not a full checklist; the CLI preview provides the detailed findings.

## Set it up with Hermes

Give Hermes this request:

> Install the Home Assistant Maintenance Workflow from https://github.com/jclark2496/home-assistant-maintenance. Read its included skill and setup instructions first. Check prerequisites, guide me through secure local credential entry and Apple Reminders permissions, show me a preview, verify a first delivery with my approval, then help me enable a recurring schedule. Do not change Home Assistant devices or install updates.

Hermes walks through:

1. Installing the package and checking the required tools.
2. Connecting to your Home Assistant instance using a token you enter locally—not in chat.
3. Checking Apple Reminders permission and your chosen list.
4. Setting battery thresholds and explicit entity mappings for any additional maintenance categories you want.
5. Showing the maintenance items it found.
6. Sending and verifying an approved first reminder.
7. Setting up and verifying a schedule after you approve it.

**Hermes coordinates the workflow; it does not bypass access requirements.** You still need Home Assistant access, macOS Reminders permission, and a Mac that is running and able to reach Home Assistant when checks are scheduled. The repository must be accessible to your GitHub account.

### Requirements

| Component | What you need |
| --- | --- |
| Hermes Agent | Installed on the Mac that will run the checks |
| Home Assistant | A reachable instance and a valid access token |
| Apple Reminders | An existing destination list and permission for the runtime to access it |
| Python | Version 3.11 or newer |
| Reminders bridge | `remindctl`, available to the scheduled runtime |

See the [guided setup and scheduling instructions](docs/HERMES_SETUP.md) and the [included Hermes skill](skills/home-assistant-maintenance/SKILL.md).

## What you can customize

- Destination Apple Reminders list.
- Default low-battery threshold (25% by default).
- Per-device battery thresholds and friendly names.
- Battery and update entities to ignore.
- Explicit unavailable entities and per-entity persistence thresholds.
- Explicit backup failure states, last-success timestamp source, maximum age, and timezone semantics.
- Explicit integration indicator states or numeric threshold/unit mappings.
- Reminder title prefix and display limits.
- Connection timeouts and local tracking-state location.
- Check schedule, managed separately through Hermes.

See [config.example.json](config.example.json). Local configuration and credentials stay outside the repository.

## Safety and privacy

- **Home Assistant is read-only.** The adapter only uses `GET /api/`, `GET /api/states`, and bounded `GET /api/history/period/...` requests for explicitly configured unavailable entities. It never changes devices or installs updates.
- **Sending is explicit.** The CLI requires `send --yes`; installation and preview do not create reminders. Scheduling is a separate approved step.
- **Credentials stay local.** Hidden token entry keeps the token out of chat and command-line arguments. Credential and state files use owner-only permissions.
- **Delivery checks are attempt-specific.** Each write has a unique marker saved before delivery and checked in the destination list afterward.
- **Uncertain delivery stops further writes.** A timeout or unverified result is not blindly retried; inspect Reminders and resolve the pending state first.
- **Overlapping runs are blocked.** A file lock protects a shared tracking-state store, and invalid state blocks writes rather than risking duplicates.
- **Your existing reminders are preserved.** Nothing is automatically deleted or completed.

Local readback verifies a record in macOS Reminders; it does not prove iCloud has synchronized it to every device. Home maintenance details placed in Apple Reminders are subject to your Apple account's normal synchronization settings.

## Installation reference

This section is for Hermes or anyone who wants to inspect the setup steps. The primary path is the Hermes request above.

After cloning the repository:

```bash
cd home-assistant-maintenance
python3 -m venv ~/.local/share/home-assistant-maintenance/venv
~/.local/share/home-assistant-maintenance/venv/bin/python -m pip install .
mkdir -p ~/.hermes/skills/home-assistant-maintenance
cp skills/home-assistant-maintenance/SKILL.md ~/.hermes/skills/home-assistant-maintenance/SKILL.md
```

The skill path above is for the default Hermes profile. Use the intended profile's skills directory when installing for another profile. Start a fresh Hermes session after installing the skill.

Configure locally using hidden credential input:

```bash
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance configure
```

Then verify and preview before approving a send:

```bash
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance doctor
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance preview
# Only after reviewing and approving the preview:
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance send --yes
```

Configuration is stored in `~/.config/home-assistant-maintenance/config.json` and `credentials.json`. Never commit either local file. Follow [HERMES_SETUP.md](docs/HERMES_SETUP.md) for paused-first scheduling and verification from the actual scheduled runtime.

### New-category configuration reference

All three new lists default to `[]`, so upgrading preserves the existing battery/update behavior until you opt in. Durations accept a positive number followed by `s`, `m`, `h`, `d`, or `w`.

| Config key | Required fields | Optional fields |
| --- | --- | --- |
| `unavailable_entities` | `entity_id` | `name`, `threshold` (default `2h`) |
| `backup_entities` | `entity_id`, and at least one of `failure_states` or `max_age` | `name`, `timestamp_attribute`, `timestamp_timezone` |
| `maintenance_indicators` | `entity_id`, plus exactly one of `problem_states` or `operator` + `threshold` | `name`, `unit`, `value_attribute` |

Duplicate entity mappings inside one category are rejected. If the same entity produces more than one **new-category** finding, preview keeps one in this order: unavailable, backup, then indicator. Existing battery and update findings remain independent. All categories contribute to the digest fingerprint and stored counts, so a changed new-category finding can create a new digest; a clean run allows a later recurrence.

## Troubleshooting

- **No battery item for a device?** Check that Home Assistant exposes a valid battery percentage and that it meets your threshold and is not excluded.
- **No update listed?** The integration must expose an `update.*` entity with state `on`.
- **Unavailable entity not listed?** Confirm it is explicitly configured, currently exactly `unavailable`, and Recorder/history covers the entire threshold window. Insufficient history fails closed.
- **Backup not listed?** Confirm your configured entity schema. Unknown or ambiguous timestamps are deliberately not called stale.
- **Indicator not listed?** Confirm the exact state spelling or numeric value and unit exposed by Home Assistant; no fault states are inferred.
- **No new reminder?** Unchanged findings are intentionally suppressed. Check `preview` and `doctor` before assuming a failure.
- **Works interactively but not on schedule?** Confirm the scheduled process can find `remindctl` and has macOS Reminders permission. Test that context separately.
- **Delivery is uncertain?** Inspect the destination list before resolving it. Do not reset state just to retry: that can create duplicates.

Use the installed CLI's `--help` for `resolve` and `state-reset`. State reset preserves a backup but should only follow manual review.

## Verification and limitations

The original battery/update package was tested through a fresh isolated installation, real read-only Home Assistant checks, direct Apple Reminders delivery, duplicate suppression, and a one-time Hermes scheduled delivery on macOS. The additional unavailable, backup, and indicator categories have synthetic offline coverage and an isolated installed-CLI check only. They have **not** been tested against a real Home Assistant history/backup integration or used for a live reminder write or scheduled job.

First-time macOS permission prompts still depend on the user's machine. The tested Mac already had working Home Assistant access and Reminders authorization. This is a maintenance digest—not an alarm-monitoring service, urgent security alert system, automatic updater, or per-device task reconciliation engine.

**Email delivery is not implemented.** The supported destination is Apple Reminders on macOS.

## Optional: run tests without Hermes

By the way, the Python package can also be installed and tested independently of Hermes. This is useful for contributors; it is not required for normal Hermes-led setup.

All automated tests use synthetic entities and fake destinations. They do not contact your home or write reminders.

```bash
python3 -m pip install '.[dev]'
python3 -m unittest discover -s tests -v
python3 -m build
```

GitHub CI builds and installs the wheel on macOS with Python 3.11–3.13, runs the offline suite, and checks the installed CLI.

## License

MIT
