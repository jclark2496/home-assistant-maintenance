# Home Assistant Maintenance Workflow

**Turn low batteries and available updates in Home Assistant into actionable Apple Reminders—with Hermes handling setup and scheduled checks.**

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

### Delivered where you already manage tasks

- **Apple Reminders delivery:** send a consolidated maintenance reminder to a list you choose.
- **Scheduled checks through Hermes:** choose a recurring schedule during setup, with your approval before activation.
- **Preview before sending:** review real findings without creating any reminders.
- **Duplicate suppression:** unchanged findings do not create another reminder when using the same tracking state.
- **Verified local delivery:** read the created reminder back from the selected list before confirming success.

This creates **one digest reminder per changed set of findings**, not a separate task for every device. Existing reminders are never automatically completed or deleted. A changed battery percentage or update version can produce a new digest even if the underlying maintenance task is still outstanding.

## What a reminder looks like

Illustrative example—not data from a real home:

> **Review Home Assistant: updates (2): Home Assistant Core 2026.10.0→2026.10.1; Hub Firmware 1.2→1.3 | low batteries (3): Front Door Lock 18%; Alarm Keypad 12%; Hallway Motion Sensor 9%**

The default title shows up to six updates and eight battery items, with a `+N more` summary when needed. Item limits and maximum title length are configurable. The current reminder is a compact digest, not a full checklist; the CLI preview provides the detailed findings.

## Set it up with Hermes

Give Hermes this request:

> Install the Home Assistant Maintenance Workflow from https://github.com/jclark2496/home-assistant-maintenance. Read its included skill and setup instructions first. Check prerequisites, guide me through secure local credential entry and Apple Reminders permissions, show me a preview, verify a first delivery with my approval, then help me enable a recurring schedule. Do not change Home Assistant devices or install updates.

Hermes walks through:

1. Installing the package and checking the required tools.
2. Connecting to your Home Assistant instance using a token you enter locally—not in chat.
3. Checking Apple Reminders permission and your chosen list.
4. Setting battery thresholds and exclusions as needed.
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
- Reminder title prefix and display limits.
- Connection timeouts and local tracking-state location.
- Check schedule, managed separately through Hermes.

See [config.example.json](config.example.json). Local configuration and credentials stay outside the repository.

## Safety and privacy

- **Home Assistant is read-only.** The adapter only uses `GET /api/` and `GET /api/states`. It never changes devices or installs updates.
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

## Troubleshooting

- **No battery item for a device?** Check that Home Assistant exposes a valid battery percentage and that it meets your threshold and is not excluded.
- **No update listed?** The integration must expose an `update.*` entity with state `on`.
- **No new reminder?** Unchanged findings are intentionally suppressed. Check `preview` and `doctor` before assuming a failure.
- **Works interactively but not on schedule?** Confirm the scheduled process can find `remindctl` and has macOS Reminders permission. Test that context separately.
- **Delivery is uncertain?** Inspect the destination list before resolving it. Do not reset state just to retry: that can create duplicates.

Use the installed CLI's `--help` for `resolve` and `state-reset`. State reset preserves a backup but should only follow manual review.

## Verification and limitations

The package has been tested through a fresh isolated installation, real read-only Home Assistant checks, direct Apple Reminders delivery, duplicate suppression, and a one-time Hermes scheduled delivery on macOS. Follow-up fixes for delivery-marker uniqueness and invalid battery values have automated regression coverage; those fixes were not followed by an additional live reminder write.

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
