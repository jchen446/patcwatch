# Patcwatch

**Local feedback monitoring. Zero runtime model calls.**

Patcwatch watches a JSON file, detects new or changed messages and puts template-based drafts in a local browser UI. It runs on your computer with no account, API key, Craylen dependency or telemetry.

**v0.1 beta:** local file monitoring and the offline experiment are supported. Teams, Jira, GitHub APIs, original writing and automatic bug fixes are not connected. This is a local application, not a hosted multi-user service.

## Install and run

Install Python 3.9+ first. In a terminal:

```sh
python3 -m venv .venv
.venv/bin/pip install https://github.com/jchen446/patcwatch/releases/download/v0.1.0/patcwatch-0.1.0-py3-none-any.whl
.venv/bin/patcwatch
```

On Windows, use `py -m venv .venv`, `.venv\Scripts\pip.exe` and `.venv\Scripts\patcwatch.exe` in place of those commands.

Open **http://127.0.0.1:8793**. Click **Run offline experiment** to confirm eight sample scenarios and the outbound-connection guard. Press Ctrl+C in the terminal to stop the app. If the port is busy, use `patcwatch --port 8794` and open that port instead.

Already use pipx? Install the same wheel URL with `pipx install URL`, then run `patcwatch`.

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

There is no model SDK or model-dispatch path. At startup a Python audit hook blocks outbound socket connections, DNS lookups and audited process launches. A deliberate loopback connection attempt confirms blocking before connection. Browser assets are bundled; the UI only requests its local server. Runtime counters are application assertions under these controls, not provider billing telemetry. The hook is not an OS sandbox against malicious native extensions. Codex tokens used to build the application are excluded.

A live service adapter would need a separately scoped network policy and verification. This release does not make live-source claims. Other existing automations are not disabled by installing Patcwatch.

## Development

```sh
python3 -m pip install .
python3 -m unittest -v
python3 app.py --experiment --data-dir ./test-state
```

GitHub Actions runs tests and the installed CLI experiment on Linux, macOS and Windows. The public release includes a Python wheel and SHA256 checksum. No runtime dependencies. Python package build tools are used only during development/installation from source.

## Security and support

The server binds only to `127.0.0.1` and checks request Host/Origin. Do not expose or proxy it onto the public Internet; it has no user authentication or multi-user isolation. Local users with access to the same machine are within the trust boundary.

Report bugs through GitHub Issues, using synthetic examples and removing private source text. See [SECURITY.md](SECURITY.md) for vulnerability reporting. MIT licensed.
