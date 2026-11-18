# Portability and limitations

- Apple Reminders delivery requires macOS, a signed-in Apple account, `remindctl`, and EventKit/TCC permission for the actual process context.
- Interactive `remindctl` access does not prove that a scheduled process has permission. Use `doctor` from the same user context before activation.
- Home Assistant must be reachable from the Mac. The source is read-only and has no retry loop.
- The configured Reminders list must already exist; the workflow never creates, renames, or deletes a list.
- A changed low-battery percentage or update version changes the fingerprint and can create a new aggregate reminder.
- Reminder title details are count- and character-bounded. The fingerprint still covers the full actionable set.
- Readback verifies the deterministic marker, not Apple cloud synchronization to every device.
- An uncertain write remains blocked until an operator inspects Reminders and resolves it. There is intentionally no blind retry.
- Resetting damaged state can permit a duplicate; the command preserves the prior file for investigation.
- The package does not complete old reminders or emit resolution reminders.
- Hermes is the primary onboarding and supported scheduler, but the Python core can run without Hermes.
- Email is a future adapter and is not implemented.
