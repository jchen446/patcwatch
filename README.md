# Patcwatch

**Local feedback monitoring. Zero runtime model calls.**

Patcwatch monitors a Teams group chat and a SharePoint Excel worksheet through Microsoft Graph. Search for a chat name, select the exact chat, browse a workbook and map its ID and feedback columns. Changes appear in a local review queue. No Chrome automation, Codex runtime, Jira, model SDK or automatic sending.

**v0.2 integration beta:** Microsoft readers and persistent scheduling are implemented and tested against synthetic HTTP fixtures. Live tenant sign-in, token renewal and source delivery have not yet been certified. This is a single-user application, not a hosted multi-user service.

## Install and run

Use Python 3.9+ built with supported OpenSSL (Python 3.13 recommended; avoid Apple's old LibreSSL Python). Install into a permanent directory if using the background service:

```sh
python3 -m venv ~/.local/share/patcwatch/venv
~/.local/share/patcwatch/venv/bin/pip install https://github.com/jchen446/patcwatch/releases/download/v0.2.0/patcwatch-0.2.0-py3-none-any.whl
~/.local/share/patcwatch/venv/bin/patcwatch --microsoft
```

On Windows, create a venv in your user directory with `py -m venv`, then use its `Scripts/pip.exe` and `Scripts/patcwatch.exe`. Alternatively install the wheel with pipx. Open **http://127.0.0.1:8793** in any browser.

1. In **App registration settings**, enter your existing Microsoft Entra application's client ID and tenant ID. Use a public-client application with public client flows enabled. No client secret is used.
2. Configure delegated permissions `User.Read`, `Chat.Read`, `Sites.Read.All`, `Files.Read.All`; your tenant may require administrator consent. Sign in with the displayed device code. The app can read only resources your account can access.
3. Search by the Teams group chat topic and select the exact result. Chats with identical names remain separate choices. Channels and unnamed one-to-one chat name lookup are not supported.
4. Enter your SharePoint site URL, choose a document library and `.xlsx` file, then select the worksheet, header row, unique ID column and monitored columns. Mapping is validated before monitoring begins.

Access tokens renew through MSAL's encrypted cache. The encryption key stays in the OS keychain (macOS Keychain, Windows Credential Locker or Linux Secret Service). A headless Linux host without an unlocked Secret Service is unsupported. Tenant policy can block device-code flow or require another sign-in; the service reports this and preserves its last successful read.

The scheduler runs in the Python service, independently of the browser. Checks default to every five minutes; use `--interval 60` to change this (minimum 30 seconds). Closing the UI does not stop the service. Logging out, sleep or shutting down the computer interrupts checks.

## Background service

On macOS, stop the foreground server with Ctrl+C, then run:

```sh
~/.local/share/patcwatch/venv/bin/patcwatch --background install
~/.local/share/patcwatch/venv/bin/patcwatch --background status
```

The per-user LaunchAgent starts at login and restarts after process failure. It uses the same state directory and OS keychain as the foreground app. Keep its venv installed. Logs are in `~/.patcwatch/service.stdout.log` and `service.stderr.log`. To remove the service without deleting data:

```sh
~/.local/share/patcwatch/venv/bin/patcwatch --background uninstall
```

Windows and Linux can run the foreground command from a signed-in session; automatic service installation is currently macOS-only. Use your operating system's session task manager for other hosts, with the exact absolute executable, `--microsoft`, and `--data-dir` arguments. Do not run two instances against one data directory.

## Monitoring boundaries

- Initial Teams baseline: messages modified in the last seven days. Later checks overlap by five minutes and deduplicate by message ID. Attachments are metadata only.
- Excel: selected worksheet and columns, stable unique row IDs, cached formula values. Reordering rows produces no change. Duplicate or missing IDs, corrupt files, incomplete pagination and changing file versions fail closed.
- New and edited content generates events after baseline. Missing messages or removed spreadsheet rows are not inferred as deletions.
- SQLite stores hashes, polling cursors and events atomically. Retries honor throttling; failures do not advance successful state. Paused sources retain their state.
- Latest 200 events appear in the UI; 10,000 events are retained. Historical hashes remain for deduplication. This is not a full archive.
- Source IDs are pinned at selection. A rename does not retarget the monitor; its saved display label may retain the original name.

Private state is stored in `~/.patcwatch`. Source content stays local. Keep that directory out of Git and backups shared with others. Microsoft application and tenant IDs are configuration, not passwords; tokens never appear in the API or logs.

## Watch your own file

Save this as `feedback.json`:

```json
{"status":"OK","messages":[{"id":"issue-1","text":"Initial feedback."}]}
```

Start the installed command with `--watch`:

```sh
.venv/bin/patcwatch --watch feedback.json
```

The first successful read establishes a baseline. Edit the text or add a new message with a unique ID. Within five seconds the UI's **Your source** section shows the change and draft. **Check source now** performs an immediate read. Drafts are never sent.

- Restarting with the same file preserves hashes and avoids duplicate drafts.
- Missing, malformed or unavailable source data preserves the last successful read and is shown as unavailable.
- Missing messages are not treated as deletions.
- IDs must be unique nonempty strings; text must be a string. Files are limited to 2 MB and 10,000 distinct IDs.
- The most recent 200 drafts are retained. This is not a full archival system.
- For an unavailable capture, write `{"status":"UNAVAILABLE"}`. Prefer atomic file replacement from your exporter.

Private state is stored in `~/.patcwatch`, separately from installed application files. To watch another source, use a separate state directory:

```sh
.venv/bin/patcwatch --watch other.json --data-dir ./other-state
```

Keep private captures and state out of Git. Patcwatch only reads the file explicitly supplied on the command line. It does not discover or upload your files. On Windows, privacy follows your user-directory ACLs; Unix-style permission bits are not a Windows access-control guarantee.

## Zero-call evidence

```sh
.venv/bin/patcwatch --experiment
.venv/bin/patcwatch --version
```

The experiment reads bundled **synthetic** captures, hashes content and fills literal templates. Its exit code is nonzero if a scenario or the network-guard probe fails. Evidence is saved in `~/.patcwatch/latest.json` and is viewable from the UI.

There is no model SDK or model-dispatch path. In local-file/experiment mode a Python audit hook blocks outbound socket connections, DNS lookups and audited process launches. A deliberate loopback connection attempt confirms blocking before connection. Browser assets are bundled; the UI only requests its local server. Runtime counters are application assertions under these controls, not provider billing telemetry. The hook is not an OS sandbox against malicious native extensions. Codex tokens used to build the application are excluded.

In Microsoft mode, the HTTP transport allows only Microsoft login, Graph read requests and a pinned SharePoint download host, with redirects disabled. It does not install the offline network guard because Microsoft reads require network access.

Run the larger test from **Scheduler evidence test** in the Microsoft UI or:

```sh
patcwatch --scheduler-test --data-dir ./test-state
```

This separate process uses real loopback HTTP, Graph parsing, XLSX parsing, SQLite and scheduling with 100 virtual time cycles, 1,000 initial records, three restart recoveries and six fault types. An audit guard blocks external network and subprocesses; a real denied connection probe and production transport rejection are checked. This is synthetic integration evidence, not proof of live Microsoft authentication or billing telemetry. Other existing automations are not disabled by installing Patcwatch.

## Development

```sh
python3 -m pip install .
python3 -m unittest -v
python3 app.py --experiment --data-dir ./test-state
```

GitHub Actions runs tests and the installed CLI experiment on Linux, macOS and Windows. The public release includes a Python wheel and SHA256 checksum. Runtime dependencies are requests, MSAL, keyring, cryptography and openpyxl. CI also runs the larger scheduler test. Python package build tools are used during installation from source.

## Security and support

The server binds only to `127.0.0.1` and checks request Host/Origin. Do not expose or proxy it onto the public Internet; it has no user authentication or multi-user isolation. Local users with access to the same machine are within the trust boundary.

Report bugs through GitHub Issues, using synthetic examples and removing private source text. See [SECURITY.md](SECURITY.md) for vulnerability reporting. MIT licensed.
