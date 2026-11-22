# Home Assistant Maintenance Workflow

Get one Apple Reminder when a new set of home maintenance jobs needs attention. The workflow runs on your Mac, reads a reachable Home Assistant instance, gathers low batteries and available updates, and can also flag persistent outages, backup problems, and service indicators you select.

**[Try the offline quickstart](#quickstart)** · [Set it up with Hermes](#set-it-up-with-hermes)

<a id="what-a-reminder-looks-like"></a>

Here is the reminder title the workflow produces from the [synthetic fixture](fixtures/home_assistant_states.synthetic.json) with the default thresholds.

> Review Home Assistant: updates (1): Example Hub Firmware 1.2.3→1.2.4 | low batteries (2): Example Phone Battery 5%; Example Window Battery 24%

<a id="features"></a>

## What it can do

### Find batteries and updates that need attention

- <a id="low-battery-reminders"></a>**Batteries.** Find locks, alarm keypads, contact sensors, and other devices that expose a numeric battery percentage. By default, 25% or lower qualifies. Give a critical lock a higher threshold, rename it in the digest, or exclude a device.
- <a id="home-assistant-and-device-update-reminders"></a>**Updates.** List available Home Assistant Core, OS, Supervisor, add-on, HACS, or firmware updates when the integration exposes an `update.*` entity whose state is `on`. Include installed and available versions when present and exclude selected updates.

### Watch conditions that matter in your home

- <a id="persistent-unavailable-entities"></a>**Persistent outages.** Choose entities and a duration for each. A device must currently report `unavailable`, with Recorder history covering the threshold window. A normal state within that window resets the clock.
- <a id="backup-health"></a>**Backup health.** Match explicit failure states, flag a last-success timestamp older than your chosen limit, or use both checks. Read the timestamp from an entity state or a named attribute. Separate rules can cover separate status and timestamp entities.
- <a id="integration-provided-maintenance-indicators"></a>**Service and fault indicators.** Map a filter, consumable, appliance fault, or service flag to exact states or a numeric threshold. A mapping can read an attribute and require a matching unit.

<a id="delivered-where-you-already-manage-tasks"></a>

### Review and deliver a digest

With the three optional checks configured, one reminder can look like this. These names and conditions are illustrative.

> Review Home Assistant: maintenance (3): Garage Hub unavailable 2h; Home Assistant Backup backup stale; HVAC Filter on

- **Inspect findings first.** `doctor` checks the connection, Reminders authorization, destination list, and tracking state. `preview` shows the proposed title and each finding. `preview --json` returns counts and structured details.
- **Create one task.** An approved send adds a single digest due that day to an existing Apple Reminders list. A saved fingerprint covers all five categories and suppresses repeat writes for unchanged findings. A changed battery percentage, update version, or optional maintenance finding can trigger another digest. A clean run allows a later recurrence.
- **Run on a schedule.** Hermes sets up a paused script-only job on the Mac. Review a preview, verify the first approved reminder in the list, then activate the chosen schedule. Clean and duplicate-suppressed runs stay silent.

## Quickstart

To try the digest without credentials, use Python 3.11 or later on macOS or Linux. These commands call the package’s preview function on the bundled sample.

```bash
git clone https://github.com/jclark2496/home-assistant-maintenance.git
cd home-assistant-maintenance
PYTHONPATH=src python3 - <<'PY'
import json
from pathlib import Path
from home_maintenance_digest import DigestConfig, make_preview

states = json.loads(Path("fixtures/home_assistant_states.synthetic.json").read_text())
rules = DigestConfig(reminder_list="Home Maintenance")
print(make_preview(states, rules).title)
PY
```

You should see the title above with one firmware update and two low batteries. The example reads a local file. To preview findings from your own home, follow the Hermes setup below.

## One design decision

**Record the delivery attempt before asking Reminders to write.** A timeout can happen after macOS has accepted the reminder. The workflow saves a unique marker, adds it to the reminder, then reads the selected list back for that marker. If the outcome is uncertain, the next run checks for the marker before any new write. This protects against duplicate tasks even when the first command’s reply is lost.

## Set it up with Hermes

### Requirements

For delivery, use a Mac running Hermes Agent, Python 3.11 or newer, and `remindctl`. The Mac needs access to Home Assistant, a valid token, a signed-in Apple account, an existing Reminders list, and Reminders permission for the process that will run the job. For scheduled checks, the Mac and the Hermes scheduler must be running at the scheduled time.

Give Hermes the following request.

> Install the Home Assistant Maintenance Workflow from https://github.com/jclark2496/home-assistant-maintenance. Read its included skill and setup guide. Check my prerequisites, guide me through local credential entry and Reminders permissions, and show me a read-only preview. Ask before sending a first reminder or activating a recurring schedule.

Hermes installs the package and skill, checks access to your list, helps map entities, and previews what needs attention. A configured home with no findings produces `No actionable maintenance findings.` Verify any first write in the chosen list before enabling the recurring job. [Hermes setup and scheduling](docs/HERMES_SETUP.md) · [Included skill](skills/home-assistant-maintenance/SKILL.md)

## What you can customize

`configure` creates local settings in `~/.config/home-assistant-maintenance/config.json` and a separate owner-only `credentials.json`. Enter the token at the hidden local prompt. Use the [example config](config.example.json) as a reference for entity IDs and attributes you have inspected in your own Home Assistant.

| Setting | What it changes |
| --- | --- |
| Batteries and updates | Default and per-device thresholds, friendly battery names, and entity exclusion lists. |
| Destination and title | Reminders list, title prefix, item counts, and maximum title length. The defaults show up to 6 updates, 8 batteries, and 8 other findings in 900 characters. `+N more` marks overflow within a category. The full findings remain available in the preview. |
| Runtime | Connection and Reminders timeouts, `remindctl` path, and tracking-state location. Choose the schedule and timezone separately in Hermes. |

<a id="new-category-configuration-reference"></a>

### Optional entity rules

All three lists default to `[]`. Adding the workflow to an existing battery/update setup leaves these checks opt-in. Durations such as `90m`, `2h`, or `1d` accept the suffixes `s`, `m`, `h`, `d`, and `w`.

| Key | Required | Optional |
| --- | --- | --- |
| `unavailable_entities` | `entity_id` | `name`, `threshold` (default `2h`) |
| `backup_entities` | `entity_id` and at least one of `failure_states` or `max_age` | `name`, `timestamp_attribute`, `timestamp_timezone` |
| `maintenance_indicators` | `entity_id` and exactly one of `problem_states` or `operator` + `threshold` | `name`, `unit`, `value_attribute` |

Use an ISO 8601 backup timestamp with an offset, or specify an IANA timezone for a local timestamp. Failure and problem states match whole values, case-insensitively. Numeric operators are `lt`, `lte`, `gt`, `gte`, `eq`, and `ne`. Nonnumeric values, nonfinite values, and unit mismatches do not trigger numeric rules.

Each entity may appear once within a category. If the same entity matches multiple optional categories, the digest prefers the outage, then the backup finding, then the indicator. Battery and update findings are evaluated independently.

## Safety and privacy

- Home Assistant access is read-only. The adapter uses `GET /api/` and `GET /api/states`. When outage rules are configured, it also reads a bounded interval of history for the selected entities. Device control and update installation stay in Home Assistant.
- Installation and preview only prepare or read data. Reminder creation requires `send --yes` or a scheduled job you have activated. Existing reminders are left for you to complete or delete.
- Configuration, credentials, and state stay outside the repository. Credential and state files are owner-only. A lock prevents overlapping writes against a shared state file, and invalid state blocks a send.
- Readback confirms delivery to the list on that Mac. Synchronization to other devices follows your Apple account settings.

## Installation reference

For the default Hermes profile, run the following from the cloned repository. For another profile, use its skill and script directories.

```bash
python3 -m venv ~/.local/share/home-assistant-maintenance/venv
~/.local/share/home-assistant-maintenance/venv/bin/python -m pip install .
mkdir -p ~/.hermes/skills/home-assistant-maintenance ~/.hermes/scripts
cp skills/home-assistant-maintenance/SKILL.md ~/.hermes/skills/home-assistant-maintenance/SKILL.md
cp scripts/home-assistant-maintenance.py ~/.hermes/scripts/home-assistant-maintenance.py
chmod 700 ~/.hermes/scripts/home-assistant-maintenance.py
```

Start a fresh Hermes session to load the skill. Configure the CLI locally, check permissions, and inspect the first preview.

```bash
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance configure
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance doctor
~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance preview
```

For an approved write, run `~/.local/share/home-assistant-maintenance/venv/bin/ha-maintenance send --yes`. For scheduling, create the job paused, verify access in the actual scheduled context, and resume it after approval. [Scheduling commands](docs/HERMES_SETUP.md)

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing battery or update | A battery must expose a 0–100 number with unit `%` and either the battery device class or `battery` in its entity ID. A binary low-battery flag is insufficient. Updates require an `update.*` entity with state `on`. Check exclusions. |
| Missing outage | Select the entity explicitly and check Recorder coverage of the whole window. A normal state or insufficient evidence suppresses the finding. The current `last_changed` identifies an outage episode. If that field is missing or malformed, an outage that clears and recurs between polls can stay suppressed until a clean poll is seen. |
| Missing backup or indicator | Inspect the actual entity state, attributes, units, and configured rules. Missing, malformed, or timezone-ambiguous timestamps cannot establish an overdue backup. |
| No new reminder | Check `preview` and `doctor`. An unchanged digest is suppressed. For a scheduled-only failure, verify `remindctl` and Reminders permission from the scheduled process. |
| Uncertain delivery | Inspect the configured list. Use `resolve --outcome delivered --yes` or `resolve --outcome not-delivered --yes` only after establishing what happened. Leave an unresolved job paused. `state-reset --yes` backs up the prior state but can permit a duplicate. |

## Project details

### Verification and limitations

The original battery/update workflow was verified on macOS with real read-only Home Assistant checks, Apple Reminders delivery, duplicate suppression, and one-time scheduled delivery. The outage, backup, and indicator checks have synthetic offline and installed-CLI coverage only. Live Home Assistant history and backup integrations, Reminders writes for those three categories, and their scheduled delivery still need verification. The Mac used for the original checks already had Reminders permission. First-time authorization depends on your machine.

Delivery supports Apple Reminders on macOS. Email, urgent alarm monitoring, automatic updates, and management of per-device tasks are outside the current release. [Portability notes](docs/PORTABILITY_GAPS.md) · [Behavior audit](docs/BEHAVIOR_AUDIT.md)

<a id="optional-run-tests-without-hermes"></a>

### Offline tests

In an activated Python 3.11+ virtual environment, run the following from the repo root. The suite uses synthetic entities and fake destinations. CI also builds and installs the wheel and smoke-tests the installed CLI on macOS with Python 3.11–3.13. [CI workflow](.github/workflows/test.yml)

```bash
python3 -m pip install '.[dev]'
python3 -m unittest discover -s tests -v
python3 -m build
```

### License

[MIT](LICENSE) · [Forkthis build notes](https://forkthis.ai/home-assistant-maintenance/)
