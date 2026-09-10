# Patcwatch

A standalone local UI for testing feedback change detection without runtime model calls. No Craylen dependency, model SDK, API key, external font, analytics or heartbeat.

## Run

Requires Python 3.9 or later. No packages to install.

```sh
python3 app.py
```

Open http://127.0.0.1:8793 and click **Run offline experiment**.

```sh
python3 app.py --experiment
python3 -m unittest -v
python3 app.py --help
```

The CLI experiment exits nonzero when a scenario or network-guard probe fails. The UI displays the eight scenario outcomes, zero model calls, outbound connections, and generated drafts. Evidence is saved to `.local/latest.json` (ignored by Git).

## Experiment boundaries

The sample data is synthetic and contains no customer messages. The process reads `samples.json`, hashes content by message ID, and fills literal templates for changed/new messages. It does not decide whether a change is actionable, write original prose, fix bugs or send messages. Missing virtualized messages are not deletions. Source failure preserves the prior successful state.

At startup a Python audit hook blocks outbound socket connections, DNS resolution and process launch through audited APIs. The experiment verifies this control using an actual attempted loopback connection that is blocked before connect. The HTTP server only binds to 127.0.0.1. The UI talks to this local server; it has no external requests. Same-origin checks protect the experiment POST.

**The zero-call finding applies to this controlled experiment.** It is supported by a stdlib-only execution path, blocked outbound connections/process launches, and no model client or dispatch path. The audit hook is not an OS security sandbox against malicious native code. The zero counters are application assertions under these controls, not independent provider billing telemetry. Codex tokens used to develop the app are excluded.

Live Teams/Jira collection is not connected. Previously configured external automations are not changed by running this app. Adding authenticated live source adapters will require a separate test and scoped network policy. No model-generated status updates run here.

## Files

- `app.py`: deterministic detector, audit guard, experiment and local HTTP server.
- `index.html`: dashboard and template draft queue, with literal text rendering.
- `samples.json`: eight repeatable synthetic scenarios.
- `test_app.py`: state preservation, duplicate rejection and untrusted-text tests.

The detector state is intentionally recreated for each experiment. This is an experiment UI, not yet a persistent production monitor.
