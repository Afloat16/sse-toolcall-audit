# sse-toolcall-audit

Offline SSE capture auditor for Chat Completions and Responses tool-call assembly, completion and semantic comparison.

[中文](README.zh-CN.md) · [Demand evidence](docs/EVIDENCE.md) · [License](LICENSE)

Independent, experimental utility maintained by **Afloat16**. Original implementation; no upstream endorsement is implied.

## Install

Python 3.10+.

```bash
git clone https://github.com/Afloat16/sse-toolcall-audit.git
cd sse-toolcall-audit
python -m venv .venv
# Activate the virtual environment for your OS, then:
python -m pip install -e '.[dev]'
```

The core package uses the Python standard library only. No GPU, ROS runtime, API key, hosted service or model weights are required for the core offline workflow.

## First run

```bash
sse-toolcall-audit examples/chat.sse --compare examples/final.json
sse-toolcall-audit saved-response.sse --api responses --output stream-report.json
```

## Inputs and checks

Saved raw UTF-8 SSE body, not an HTTP-header dump or JSON array. Handles CR/LF/CRLF, comments, multi-line data and Unicode. Chat Completions calls are assembled by choice/tool index; Responses calls by item ID. Parallel calls are supported.

Checks terminal markers, finish reasons, missing function fields, strict object JSON arguments and Responses delta/final consistency. `--compare` accepts a saved non-streaming Chat Completions or Responses JSON response and compares the multiset of names and semantic argument objects, ignoring IDs and object-key order.

## Boundaries

Targeted tool-result audit, not validation of every protocol field. Two stochastic generations need not match. No network calls, tool execution or silent JSON repair. Reports omit argument values/content/reasoning, but names, IDs and SHA-256 digests still expose metadata/equality; hashes are not guaranteed anonymization. Real captures may contain secrets and should stay local. Limits: 64 MiB capture, 100,000 SSE data events.

## Output and development

Audit commands exit 0 for no error findings, 1 for errors (also warnings with --strict), and 2 for malformed input/report-write failure. --output creates a new JSON file exclusively; existing files are never overwritten. Detailed audit findings are capped at 200 while total severity counts remain accurate.

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m build
```

The configured CI matrix covers Ubuntu, Windows and macOS with Python 3.10/3.13; inspect Actions for actual results. Fixtures are synthetic. No private captures or upstream user attachments are redistributed.

Report problems with command/version, expected/actual result and a minimal synthetic reproduction. Keep source attribution and compatible licensing. MIT license, copyright Afloat16.
