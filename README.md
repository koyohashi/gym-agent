---
title: Gym Agent
emoji: 🏋️
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
python_version: "3.12"
pinned: false
short_description: Typing-only gym logger driven by a smolagents agent
tags:
- smolagents
- agent
---

# Gym Agent

Type shorthand like `bench 3x8 @135`; a smolagents `ToolCallingAgent` turns it into tool calls that write sets to Supabase.

Supports logging sets, undoing the last set, starting and ending sessions, "what did I do last time on X?", and "what's my PR on X?".

## Layout

| File | Owns |
| --- | --- |
| `app.py` | Entrypoint: checks config, builds the agent, launches the UI |
| `ui.py` | Gradio chat with password login |
| `agent.py` | Model config and `build_agent()` |
| `tools.py` | The nine `@tool` functions |
| `db.py` | All Supabase access (plus an in-memory backend for tests and evals) |
| `exercises.py` | Exercise list loading and fuzzy matching |
| `prompts.yaml` | Agent prompt templates and the notation rules (`instructions`) |
| `data/exercises.json` | Canonical exercises and aliases |
| `sql/schema.sql` | Supabase tables and row-level security |
| `evals/` | Eval cases and runner |
| `tests/` | Unit tests that need no model |

## Local development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt gradio pytest
cp .env.example .env            # fill it in
.venv/bin/pytest                # Supabase tests run only when SUPABASE_* and APP_USER_ID are set
.venv/bin/python app.py         # MODEL_BACKEND=ollama against a local Ollama server
```

Set `DB_BACKEND=memory` in `.env` to try the chat without Supabase (local only; refused on a Space).

## Database setup

Run `sql/schema.sql` in the Supabase SQL editor of a dev project. RLS is enabled with no policies, so the anon key can read nothing; the app uses the service-role key server-side.

## Evals

```bash
.venv/bin/python evals/run.py --model ollama:qwen2:7b --model hf:Qwen/Qwen2.5-72B-Instruct
```

Prints a pass rate per model, split into single-exercise and compound cases. Runs against the in-memory database.

## Space secrets

`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `APP_USER_ID`, `MODEL_BACKEND`, `MODEL_ID`, `HF_TOKEN` (or the provider key), `GRADIO_USER`, `GRADIO_PASSWORD`. `app.py` refuses to start if any is missing.
