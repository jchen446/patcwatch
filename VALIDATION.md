# Validation

2026-09-10: CLI and real browser UI experiment passed 8/8 scenarios. The browser Run button produced a fresh persisted report and two template drafts. Experiment guard blocked its deliberate outbound connection attempt. No model SDK or dispatch path exists. Runtime model calls: 0 under these experiment controls.

Three unit tests passed: baseline/change/repeat/failure preservation, atomic rejection of duplicate IDs, and literal treatment of untrusted text. CLI help works. A POST without the UI origin/header was rejected with HTTP 403.

This validates synthetic local replay only. No live source integration or provider usage telemetry is claimed. Application-build tokens are excluded. Runtime evidence lives in ignored `.local/latest.json`.
