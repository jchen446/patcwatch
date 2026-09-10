# Release validation

Local macOS / Python 3.9 validation on 2026-09-10:

- Five unit tests pass: change/repeat/failure handling, malformed capture atomicity, literal untrusted text, persisted restart deduplication, and source identity isolation.
- Installed package CLI experiment passes 8/8 cases and blocks the deliberate outbound connection attempt. CLI help/version work.
- Installed package UI opened in a real browser. The Check source now button showed the changed local feedback draft. The Run offline experiment button produced a fresh 8/8 report with zero model calls under the experiment controls.
- Requests missing the UI Origin/header are rejected. Requests with an unexpected Host are rejected.
- GitHub Actions defines Linux, macOS and Windows installation/test jobs. Check the repository's current Actions results for their actual completion status.

Synthetic local captures only. No live service integration or provider billing telemetry is claimed. Build-time Codex tokens are excluded. Local runtime reports are private and not in the release.
