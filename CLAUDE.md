# CLAUDE.md

## What this project is

Leicester Dynasty Archive: a local, Windows-oriented **Football Manager archive and AI analysis workspace**. FM save files are imported into SQLite; the user browses snapshots, runs restricted SQL, and chats with an assistant that retrieves evidence through bounded, read-only tools.

Two halves, deliberately separate:

- **Deterministic pipeline** (no model calls): stability + SHA-256 dedup → DB backup → `fmsave` parse + reader validation → visible-field allowlist → `db/archive.sqlite3`.
- **Bounded agent loop**: the model picks one of 11 tools, receives results, and answers with structured references; `src/evidence_gate.py` checks those references against the tool output. The agent can only read the DB.

Two conversation spaces share the archive: **Analysis** (game facts) and **Dressing room** (stories/headcanon). Fiction is never auto-promoted to fact. Services bind to loopback only. `README.md` is the authoritative long-form guide; read it before changing the pipeline, tools, or evidence rules.

## Tech stack

- Python 3.12 only (`requires-python >=3.12,<3.13`, `.python-version`), managed with **uv** (`pyproject.toml`, `uv.lock`, `package = false`).
- Dependencies: `fmsave==0.5.4` (save parser), `streamlit` (legacy UI), `requests`, `PyJWT[crypto]`.
- Storage: SQLite (stdlib `sqlite3`) under `db/`; no ORM.
- Live frontend: plain HTML/CSS/JS in `ui-preview/` served by a stdlib `http.server` backend (no bundler, no npm).
- Tests: stdlib `unittest`.

## Directory structure

| Path | Role |
| --- | --- |
| `ui-preview/` | **The live workspace** (name is historical). `server.py` is the HTTP service on `127.0.0.1:8502`; `app.js`, `archive.js`, `live.js`, `charts.js`, `timeline.js`, `i18n.js` and CSS are the frontend |
| `app.py`, `src/*_ui.py` | Optional legacy Streamlit pages (port 8501) |
| `src/sync_save.py`, `src/import_save.py` | Find latest save, backup, orchestrate import |
| `src/safe_export.py`, `src/archive.py`, `src/analytics.py` | Allowlisted projection, storage, statistics |
| `src/league_archive.py`, `src/movements.py`, `src/transfers.py` | League snapshots, squad movements, transfer evidence |
| `src/chat_auth.py` | Authorization, model directory, streaming, bounded tool loop |
| `src/chat_tools.py` | The 11 tool schemas, argument validation, read-only execution |
| `src/evidence_gate.py` | Structured fact references, coverage warnings, title-race rules; holds the model-facing `INSTRUCTIONS` |
| `src/web_chat.py`, `src/chat_store.py`, `src/chat_trace.py` | Background jobs, persistence, traces/usage |
| `src/attack_comparison.py`, `src/charts.py` | Attacking metrics/per-90, chart specs resolved from tool results |
| `src/sql_console.py`, `src/web_archive.py` | Restricted manual SQL workbench, native archive pages API |
| `src/story_memory.py`, `src/lore.py`, `src/conversations.py`, `src/import_transcript.py` | Stories, canon/inference/headcanon, conversation originals |
| `src/i18n.py`, `locales/` | UI catalog (`zh-CN.json`), functional input/club aliases |
| `tests/` | Synthetic unit and mocked-service tests |
| `data/`, `db/`, `logs/`, `.tools/`, `.venv/` | Local runtime state, **Git-ignored** (only `data/**/README.md` tracked) |
| `*.ps1`, `*.cmd` | Windows launchers: `Setup`, `Start-Workspace`, `Start-Archive`, `Stop-Archive`, `Import-Save`, `Update-Latest` |
| `docs/manual-stories.md` | Format of the local `data/manual/lore.json` |

## Running and testing

Setup and launch are Windows PowerShell scripts; on other platforms run the underlying commands directly.

```
uv sync --locked                      # install pinned deps into .venv (Setup.ps1 does this)
uv run python -X utf8 ui-preview/server.py      # live workspace → http://127.0.0.1:8502
uv run python -X utf8 -m streamlit run app.py   # legacy Streamlit UI → http://127.0.0.1:8501
```

Tests (run from the repo root; they import `src.*` and need the deps installed, e.g. `streamlit` — without `uv sync` roughly 17 tests error on import):

```
uv run python -m unittest discover -s tests
uv run python -m unittest tests.test_evidence_gate          # one module
uv run python -m unittest tests.test_chat_tools.SomeCase    # one case
```

- Tests use synthetic data and mocked model responses; they never call a live model or touch a real save. Tests needing the owner's private archive live in the ignored `tests_private/`.
- After changing parser, prompt, tool, or evidence-gate behaviour, run the relevant tests and also sanity-check a small, verifiable example by hand — a green suite does not prove the natural-language reasoning is right.
- There is no linter/formatter configured and no CI config in the repo.

## Code style and conventions

Match the surrounding code; the style is intentionally compact and not PEP 8–strict.

- Python: 4-space indent, single-quoted strings by default, short module docstring at top, few comments (explain *why*, e.g. `# An empty list or object may be cited...`). Compact forms are common: `if cond:return x`, no spaces around `=`/after commas in keyword-heavy calls (`dict(a=1,b=2)`), small helpers over classes. Plain functions and `dict` rows rather than models.
- Imports use the `src.` package path (`from src.archive import ...`); `ui-preview/server.py` inserts the repo root into `sys.path`.
- Tests: `unittest.TestCase`, one `tests/test_<module>.py` per area, temp dirs/in-memory SQLite for isolation. Add a regression test with each behaviour change (edge cases the README lists: duplicate saves, season rollover, zero minutes, nulls, ambiguous names, mixed competitions, tied standings).
- **English is the source language** for code, prompts, messages and docs. User-facing strings get a `zh-CN` entry in `locales/zh-CN.json` (preserve `{0}` placeholders); `input-aliases.json` / `club-aliases.json` are lookup inputs, not display labels. Don't translate stored names, originals, SQL, or evidence payloads.
- Frontend: vanilla JS/CSS, no build step; keep `ui-preview/i18n.js` and `locales/` in sync.

## Invariants — do not break

- **Agent is read-only.** SQL is fixed/parameterised and the DB is opened read-only (`?mode=ro`); the SQL workbench is restricted (500-row/size/time limits). Imports never call a model.
- **Visible-field allowlist** (`src/safe_export.py`): hidden CA/PA, personality, reputation, raw attributes must never reach exports, tools, or the model. Tests guard this.
- **Evidence references**: every cited value must resolve by path in a tool result and match exactly; charts read values from tool results, never from model text.
- Loopback-only binding and Host-header checks in `server.py`; credentials are never sent to the frontend.
- Never commit personal data: `*.fm`, `*.sqlite*`, `data/`, `db/`, `logs/`, `.private/`, `.env*`, transcripts, screenshots, credentials. `.gitignore` already covers these; don't loosen it. Git is not a backup — use SQLite's backup API for live DBs.
- Duplicate-save detection is by content SHA-256 across core, extended and league imports; keep imports idempotent.
