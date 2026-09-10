# v0.2 integration beta validation

2026-09-10, macOS, Python 3.12 (also unit-tested on Python 3.9):

- 13 unit tests pass, including persisted restart deduplication, transactional rollback, exclusive process ownership, Graph destination restrictions, one-time refresh after HTTP 401, workbook identity validation and literal Teams plain text.
- Larger scheduler test passes: 100 virtual cycles, 1,000 starting records, 198 scheduled checks, 1,332 loopback HTTP requests, three restart recoveries, 100 suppressed duplicate ticks, 20 expected/20 observed events and 123 assertions. Six fault categories preserve successful state. Zero model calls/external connections under the audit controls; actual denied connection probe and production transport denial verified.
- Installed Microsoft UI: scheduler button displays COMPLETE/PASS. Unconfigured authentication is visibly NOT CONNECTED, not a success.
- Separate explicitly simulated UI: chat-name discovery returns duplicate names; exact second chat ID selected; SharePoint library/workbook browsing, worksheet/ID/column mapping and source baseline observed. Script-like worksheet content displays literally.
- macOS LaunchAgent installed from a permanent venv; loopback UI served by launchd. Automatic process restart and state persistence checked.
- Existing eight-case offline CLI experiment remains supported. Host/Origin validation applies to Microsoft setup actions.

**Not certified:** real tenant device sign-in, encrypted token renewal against Microsoft, tenant consent/policy, live Teams/SharePoint delivery, overnight/sleep recovery, Windows/Linux keychain behavior. No app registration IDs were supplied for live qualification. Synthetic auth and virtual scheduler time are not proof of these behaviors.

The service performs Microsoft reads and local deterministic comparisons. Build-time Codex use is excluded from zero-runtime-model-call claims. Missing rows are not inferred as deletions. The source does not dispatch to any model provider. Private captures and credentials are not published.

GitHub Actions runs installation, unit tests, both experiments and version checks across Linux/macOS/Windows and Python 3.9/3.13. Consult the current run for the actual verdict.
