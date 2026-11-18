# Public extraction notes

This repository is a sanitized, standalone implementation derived from a private maintenance workflow. The extraction was inspected read-only before implementation. No production script, schedule, Home Assistant instance, credential store, or Reminders data was changed.

Behavior retained:

- available `update.*` entities and numeric battery sensors are selected;
- thresholds are inclusive and configurable;
- update versions and battery percentages participate in deterministic deduplication;
- a clean run permits a later recurrence to notify;
- existing reminders are not completed or deleted.

Production-oriented improvements:

- installable CLI and wheel;
- secure local credential prompt and owner-only files;
- GET-only Home Assistant adapter;
- preview, doctor, and explicit `send --yes` boundary;
- atomic state, non-overlapping-run lock, corrupt-state fail-closed behavior;
- pre-write pending intent and post-write marker readback;
- uncertain delivery blocks automatic retry until operator resolution;
- configurable list, thresholds, exclusions, display names, limits, and timeouts;
- Hermes skill and documented paused-first script-only scheduling;
- offline automated tests and macOS CI.

Private paths, job identifiers, list names, device identifiers, execution dates, historical run totals, raw outputs, and household-specific configuration are intentionally omitted.
