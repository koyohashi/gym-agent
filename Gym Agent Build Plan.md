# Gym Agent: Build Plan

Oct 17, 2026 · @Koyo

## Overview

Build a typing-only gym logger: the user types shorthand such as `bench 3x8 @135`, an LLM turns it into tool calls, and the tools write sets to Supabase. It is a single-user app, hosted on Hugging Face Spaces with a hosted model, and developed locally against Ollama first.

**v1 goal:** log sets by chat, undo the last one, and answer "what did I do last time on X?" and "what's my PR on X?".

**Starting point:** the Hugging Face `agents-course/First_agent_template` Space (`app.py`, `Gradio_UI.py`, `prompts.yaml`, `requirements.txt`, `README.md`). Keep its file layout and deploy format; replace its placeholder tools and drop its unused image-generation tool.

**How to use this doc:** build in the order given under Build order. Treat Decisions as fixed; if one blocks you, stop and ask instead of changing it. Check the current smolagents docs before writing agent code, because the template pins an older version (1.13.0) and class names have changed since.

## Decisions

These are settled; do not revisit them without asking.

- **Input:** typing only. No voice or microphone in v1.
- **Agent framework:** smolagents. Start with `ToolCallingAgent` because the tools write to a database; try `CodeAgent` later against the eval set.
- **UI:** Gradio chat in `ui.py`, with password login before the Space is made public.
- **Model:** one swappable config value. Local dev uses Ollama (`qwen2:7b`, also try `qwen2.5:7b`). Production uses a hosted model through Hugging Face inference or a LiteLLM provider. Choose by eval results.
- **Storage:** Supabase Postgres, called directly from the tools with `supabase-py`. No separate API layer. All database code lives in `db.py` so the backend can be swapped (for example, to SQLite).
- **Users:** single user. No signup flow, but keep a `user_id` column and turn on row-level security.
- **Exercise list:** `data/exercises.json`, starting from a generated list that the user edits. The agent may add an exercise only after the user confirms. Added exercises are stored in a Supabase table named user\_exercises, not in the JSON file, because the Space's disk does not persist.
- **Sessions:** explicit start and end. Logging a set with no active session auto-starts one. A session stays open until the user ends it.
- **Sets:** exercise, weight, reps, unit, timestamp, optional note. Weight is per dumbbell for dumbbell lifts. Bodyweight movements store 0 plus any added load. Default unit is lbs; `kg` typed with a weight overrides it for that set.
- **Editing:** undo the last set only.
- **Stats:** last performance for an exercise, and PR defined as the heaviest weight for any reps.
- **Hosting:** Hugging Face Spaces (Gradio SDK). Secrets go in Space secrets, never in the repo.

## Architecture

The model only chooses which tool to call; only the tools touch your data.

&#91;embedded content: architecture · 9 components, 9 connections\]

Read left to right: the phone talks to the UI, the UI to the agent, and the agent to the model. The highlighted tools are the only path to the exercise list and the database.

**Write path** (`bench 3x8 @135`):

1. `ui.py` passes the message and chat history to the agent.
2. The model calls `resolve_exercise("bench")` and gets `bench_press`.
3. It calls `log_set` three times. If no session is open, the first call starts one.
4. `db.py` inserts the rows into Supabase.
5. The model replies with a short confirmation.

**Read path** (`what's my bench PR?`): the model resolves the exercise, calls `get_pr`, `db.py` queries `sets`, and the model words the answer. Nothing is written.

## Repo layout

Each file owns one job, so the database, tools, agent, and UI can each be tested or swapped alone.

| File | Owns |
| --- | --- |
| `app.py` | Entrypoint. Reads config, builds the agent, launches the UI. |
| `ui.py` | Gradio chat UI and login. Replaces or wraps the template's `Gradio_UI.py`. |
| `agent.py` | Model config, agent construction, system prompt loading. |
| `tools.py` | The `@tool` functions the agent can call. No raw SQL here. |
| `db.py` | All Supabase access: session, set, and user-added exercise queries. Only file that imports `supabase`. |
| `exercises.py` | Loads `data/exercises.json`, fuzzy-matches names, and merges in user-added exercises from db.py. |
| `prompts.yaml` | Agent prompt templates, plus the notation rules from the Agent section. |
| `data/exercises.json` | Canonical exercise names, aliases, weight type. |
| `sql/schema.sql` | Supabase table definitions and row-level security. |
| `evals/cases.jsonl` + `evals/run.py` | Sample inputs with expected tool calls, and a runner. |
| `tests/` | Unit tests for `exercises.py`, `db.py`, and each tool without the agent. |
| `requirements.txt` | Pinned dependencies. |
| `README.md` | Spaces metadata header (`sdk: gradio`, `app_file: app.py`) plus run instructions. |

## Data model

Two stores: a static exercise list in JSON, and Supabase tables for everything that changes.

**`data/exercises.json`** is a list of objects. Generate a starter list of common lifts with the abbreviations lifters actually type, then let the user edit it.

```json
[
  {
    "id": "bench_press",
    "name": "Barbell Bench Press",
    "aliases": ["bench", "bp", "flat bench"],
    "weight_type": "barbell",
    "muscle_group": "chest"
  }
]
```

`weight_type` is one of `barbell`, `dumbbell`, `machine`, `cable`, `bodyweight`. Ids are lowercase snake\_case, unique, and never change once sets reference them. Aliases must be unique across the file.

**`sql/schema.sql`** creates the session and set tables:

```sql
create table sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  label text
);

-- at most one open session per user
create unique index one_active_session on sessions (user_id) where ended_at is null;

create table sets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  session_id uuid not null references sessions(id) on delete cascade,
  exercise_id text not null,
  weight numeric not null check (weight >= 0),
  reps integer not null check (reps > 0 and reps < 200),
  unit text not null default 'lbs' check (unit in ('lbs', 'kg')),
  note text,
  logged_at timestamptz not null default now()
);

create index sets_exercise_time on sets (user_id, exercise_id, logged_at desc);

alter table sessions enable row level security;
alter table sets enable row level security;
```

**Added exercises** live in a third table, because the Space's disk is not persistent and edits to the JSON file would be lost on restart. `exercises.py` merges `exercises.json` with this table when it loads. Ids and aliases must stay unique across both.

```sql
create table user_exercises (
  id text primary key,
  user_id uuid not null,
  name text not null,
  aliases text[] not null default '{}',
  weight_type text not null check (weight_type in ('barbell', 'dumbbell', 'machine', 'cable', 'bodyweight')),
  muscle_group text
);

alter table user_exercises enable row level security;
```

**Access and keys:** the app runs server-side on the Space with the Supabase service-role key as a Space secret, which bypasses row-level security. Enable RLS with no public policies so the anon key can read nothing. `user_id` comes from an `APP_USER_ID` environment variable.

**Unit handling:** store each set in the unit it was entered in. When comparing weights (for example PR), convert kg to lbs with 1 kg = 2.20462 lbs, and return the original set with its original unit.

## Tools

Nine tools in `tools.py`, each a `@tool` function with type hints and a docstring whose `Args:` section describes every argument, since the model reads the docstring to decide when and how to call it. Tools return short plain strings. On bad input or a missing record they return a string starting with `ERROR:` and a reason instead of raising, so the agent can recover or explain.

| Tool | Arguments | Behavior | Returns |
| --- | --- | --- | --- |
| `resolve_exercise` | `query` | Fuzzy-match against names and aliases in `exercises.json` (use `rapidfuzz`). Thresholds are constants in `exercises.py`, tuned by tests. | `match` with id and name, `ambiguous` with up to 3 candidates, or `none` |
| `add_exercise` | `name`, `aliases`, `weight_type`, `muscle_group` | Insert into the user\_exercises table instead of `exercises.json`. The agent calls it only after the user confirms. Reject duplicate ids or aliases. | Confirmation with the new id |
| `start_session` | `label` | Open a session. If one is already open, return it instead of creating another. | Session id and start time |
| `end_session` | none | Set `ended_at` on the active session. | Count of sets and exercises in it |
| `log_set` | `exercise_id`, `weight`, `reps`, `unit`, `note` | Auto-start a session if none is open. Validate that the exercise exists, `weight >= 0`, `1 <= reps < 200`, unit is `lbs` or `kg`. Timestamp server-side. | One-line confirmation, such as `Logged bench_press 135 lbs x 8` |
| `undo_last_set` | none | Delete the most recent set in the active session. | What was removed, or `ERROR:` if the session has no sets |
| `get_active_session` | none | Read the open session and its sets so far, so "another set" can reuse the last exercise and weight. | Session summary, or a note that none is open |
| `get_last_performance` | `exercise_id` | Sets from the most recent earlier session that includes this exercise, excluding the active session. | Date and list of sets |
| `get_pr` | `exercise_id` | Heaviest weight for any reps, comparing in lbs. Ties go to the most recent set. | The set with its date and original unit |

`unit` and `note` are required string arguments in the signatures. The system prompt tells the agent to pass `lbs` when the user gave no unit and an empty string when there is no note. This avoids relying on how a given smolagents version handles optional arguments; revisit if the installed version supports them cleanly.

**Rules every tool follows**

- Only `db.py` talks to Supabase, and only `exercises.py` reads or writes `exercises.json`.
- A set is always logged against a resolved `exercise_id`, never free text.
- One `log_set` call per set. Shorthand like `3x8 @135` becomes three calls.
- Each tool is unit-tested directly, without the agent or the model.

## Agent and prompt

The LLM does the understanding (shorthand into structured tool calls); the code does the checking (exercise names, number ranges, database rules).

**Agent:** a smolagents `ToolCallingAgent` with the nine tools plus the built-in final answer, `max_steps` around 10 (the template uses 6, but one `3x8` message needs a resolve call and three `log_set` calls), and a modest `verbosity_level`. Build it in `agent.py` behind a function like `build_agent()` so `app.py`, tests, and the eval runner all share it.

**Model config:** read from environment variables so switching models is one value, not a code change.

- `MODEL_BACKEND`: `ollama` for local dev, `hf` for Hugging Face inference, or `litellm` for another provider.
- `MODEL_ID`: the model name for that backend.
- Secrets (`HF_TOKEN` or the provider key) come from the environment, never the repo.

The template's `HfApiModel` is a class name from its pinned smolagents version. Check the current docs for the matching class (`InferenceClientModel` in newer releases, as far as I know) and for how to point `LiteLLMModel` at a local Ollama server. Do not assume the template's imports still work after upgrading.

**System prompt:** keep it in `prompts.yaml`. If the installed smolagents version supports an `instructions` argument, append these rules through it; otherwise add them to the system prompt template. Keep it short, because small models follow tight prompts better.

```text
You log gym workouts for one user and answer questions about their history.

Notation the user types:
- "3x8" = 3 sets of 8 reps. "3x8 @135" = at weight 135.
- "@" or "at" introduces the weight. "x" separates sets from reps.
- A list like "10, 10, 8" after a weight = reps for consecutive sets at that weight.
- No unit means lbs. "kg" overrides it. Always pass the unit explicitly.
- Dumbbell weight is per dumbbell. Bodyweight movements use weight 0 plus any added load.
- "same as last time" = call get_last_performance and reuse those numbers.
- "another set" = repeat the last set from get_active_session.

Rules:
- Always call resolve_exercise before logging. If the result is ambiguous, ask which one. Never guess.
- If the exercise is unknown, ask whether to add it. Call add_exercise only after the user says yes.
- Call log_set once per set. Do not call end_session unless the user says they are done.
- Pass an empty string as note when there is none.
- If weight or reps are missing, ask. Never invent numbers.
- After logging, reply with a short confirmation of what was logged.

Examples:
- "bench 3x8 @135" -> resolve_exercise("bench"), then log_set x3 with weight 135, reps 8, unit lbs.
- "incline db 60s for 10, 10, 8" -> resolve_exercise("incline db"), then log_set with weight 60 and reps 10, 10, 8.
- "undo" -> undo_last_set.
```

Every rule added here needs a matching case in the eval set.

## UI and deployment

The app is a Gradio chat that runs the same way locally and on a Hugging Face Space; only environment variables differ.

**UI (`ui.py`)**

- Use the template's `GradioUI` if it fits, otherwise `gr.ChatInterface`. The template's `Gradio_UI.py` was not reviewed for this plan, so read it first and check whether its `launch()` accepts a login. If not, call Gradio's `launch(auth=(user, password))` on a `ChatInterface` yourself.
- Login credentials come from `GRADIO_USER` and `GRADIO_PASSWORD`. Do not make the Space public without them, because anyone with the URL could otherwise spend model credits and write to the database.
- Keep conversation memory across turns within a browser session so clarification questions work ("which bench?" then "incline"). Check the installed smolagents docs for how to run without resetting memory. Tools must never depend on that memory for state; the database is the source of truth.
- Chat box only in v1. No table, chart, or microphone.

**Hugging Face Space**

- `README.md` carries the Spaces header: `sdk: gradio`, `app_file: app.py`, plus the SDK version. Pin `smolagents`, `supabase`, `rapidfuzz`, and `gradio` in `requirements.txt`.
- **The Space's local disk is not persistent on the free tier.** Anything the app must keep goes in Supabase, never in local files. This affects added exercises (see Data model).
- A free Space may sleep when idle and take a moment to wake. Acceptable for v1.

**Secrets (Space secrets, or a local `.env` that is gitignored)**

| Name | Purpose |
| --- | --- |
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_KEY` | Service-role key, server-side only |
| `APP_USER_ID` | The single user's UUID, written to every row |
| `MODEL_BACKEND`, `MODEL_ID` | Which model to use |
| `HF_TOKEN` or provider key | Model access |
| `GRADIO_USER`, `GRADIO_PASSWORD` | Chat login |

`app.py` should fail at startup with a clear message if any required variable is missing.

**Local development:** run `python app.py` with `MODEL_BACKEND=ollama` against a local Ollama server. Supabase can be a separate dev project. Deploy to the Space only after the eval set passes locally.

## Evals

The eval set decides which model to use and catches prompt regressions. Build it before tuning the prompt.

**Format:** `evals/cases.jsonl`, one case per line with `input`, optional `setup` (for example a set already logged), and `expect` (an ordered list of tool names with the arguments that must match). `evals/run.py` builds the agent from `build_agent()`, swaps `db.py` for an in-memory fake, records every tool call, and prints a pass rate per model. A case also fails if the agent exceeds `max_steps`, or makes a write call where the case expects none.

**Starter cases** (the user adds more from real typing):

| Input | Expected tool calls |
| --- | --- |
| `bench 3x8 @135` | `resolve_exercise`, then `log_set` x3 (135, 8, lbs) |
| `incline db 60s for 10, 10, 8` | `resolve_exercise`, then `log_set` x3 (60 lbs; reps 10, 10, 8) |
| `squat 5x5 @225` | `resolve_exercise`, then `log_set` x5 |
| `deadlift 1x5 @100kg` | `resolve_exercise`, then `log_set` with unit kg |
| `pull ups 3x10` | `resolve_exercise`, then `log_set` x3 with weight 0 |
| `bench 3x8` | No `log_set`; agent asks for the weight |
| `bench` (two matching exercises) | No `log_set`; agent asks which one |
| `hack squat 3x10 @180` (not in the list) | No `add_exercise` call; agent asks whether to add it |
| `another set` (after a logged set) | `get_active_session`, then `log_set` repeating it |
| `same as last time on squats` | `resolve_exercise`, `get_last_performance`, then `log_set` per set |
| `undo` | `undo_last_set` |
| `what's my bench PR?` | `resolve_exercise`, `get_pr`; no writes |
| `what did I do last time on squats?` | `resolve_exercise`, `get_last_performance`; no writes |
| `done` | `end_session` |
| `bench 3x8 @135 then incline db 3x10 @60` | Six `log_set` calls with the right exercises |
| `bench 1x8 @135 left shoulder tight` | `log_set` with a non-empty note |

**Using the results:** run every case against local `qwen2:7b`, `qwen2.5:7b`, and one or two hosted models. Choose the cheapest model that passes all single-exercise cases and most compound ones. Report the compound cases separately, since small models fail there first.

## Build order

Build the deterministic parts first and test them without a model, then add the agent, then the UI, then deploy. Each step has a check; do not start the next step until it passes.

1. **Scaffold.** Copy the template's layout, set the README header, pin `requirements.txt`, and drop the unused image-generation tool and search dependency. *Done when* the template's chat runs locally.
2. **Data.** Generate `data/exercises.json` (a starter list of common lifts with the abbreviations lifters type) and write `sql/schema.sql`. Apply it to a dev Supabase project. *Done when* the tables exist, RLS is on, and a second open session for the same user is rejected by the unique index.
3. **Exercise lookup.** Build `exercises.py` with tests. *Done when* `bench`, `bp`, and `flat bench` all resolve to `bench_press`, an ambiguous query returns candidates, and an unknown name returns `none`.
4. **Database layer.** Build `db.py` with tests against the dev project. *Done when* start and end session, add set, undo, last performance, PR, and add and list user exercises all pass, including a PR comparison that mixes lbs and kg.
5. **Tools.** Build `tools.py` on top of steps 3 and 4. *Done when* each tool returns its expected string, or an `ERROR:` string for each invalid input, in tests that use no model.
6. **Agent.** Build `agent.py` and `prompts.yaml` against local Ollama. *Done when* `bench 3x8 @135` logs three sets in a manual run.
7. **Evals.** Write `evals/cases.jsonl` and `evals/run.py`, tune the prompt, and compare models. *Done when* a pass-rate report exists for each model tried and one is chosen.
8. **UI and login.** Build `ui.py` with the password login. *Done when* the chat works in a browser and refuses access without the password.
9. **Deploy.** Create the Space, set the secrets, point `MODEL_BACKEND` at the hosted model, and push. *Done when* a full workout (start, log sets, undo, PR question, end) works from a phone on cellular data.

## Out of scope and open questions

**Out of scope for v1:** voice input, logging past workouts after the fact, editing anything except the last set, volume and frequency stats, estimated 1RM, charts or a live table of today's sets, multiple users, a separate API layer, and RPE or set-type fields.

**Open questions.** Each has a default so building can continue; change the default if the answer differs.

- **Notes:** attach to a set (default) or to the whole session?
- **Hosted model:** which provider and model? Decide from eval results, and set a spending cap or budget alert on whichever account is used.
- **Login:** does the template's `Gradio_UI.py` accept `auth`? Default is to use `gr.ChatInterface` if it does not.
- **Starter list size:** default is about 50 common lifts.
