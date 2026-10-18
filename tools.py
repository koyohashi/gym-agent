"""The @tool functions the agent can call. Database access goes through db.py, exercise lookup through exercises.py."""

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from smolagents import tool

import db
import exercises

UNITS = {"lbs": "lbs", "lb": "lbs", "pounds": "lbs", "pound": "lbs", "kg": "kg", "kgs": "kg", "kilos": "kg"}


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("APP_TIMEZONE", "UTC"))


def today_line() -> str:
    """Context for the model, which otherwise does not know the date."""
    return f"(Today is {datetime.now(_tz()).strftime('%a %Y-%m-%d')} in the user's timezone.)"


def _date(ts) -> str:
    return ts.astimezone(_tz()).strftime("%Y-%m-%d")


def _time(ts) -> str:
    return ts.astimezone(_tz()).strftime("%Y-%m-%d %H:%M")


def _w(weight) -> str:
    return f"{float(weight):g}"


def _set_str(s: dict, with_exercise: bool = True) -> str:
    text = f"{_w(s['weight'])} {s['unit']} x {s['reps']}"
    if with_exercise:
        text = f"{s['exercise_id']} {text}"
    if s.get("note"):
        text += f" ({s['note']})"
    return text


def _exercise_label(e: dict) -> str:
    return f"{e['id']} ({e['name']})"


def _check_set_values(**values) -> dict | str:
    """Validate and normalize any of weight, reps, unit. Returns the clean values, or an ERROR string."""
    clean = {}
    if "weight" in values:
        try:
            clean["weight"] = float(values["weight"])
        except (TypeError, ValueError):
            return f"ERROR: weight must be a number, got '{values['weight']}'."
        if clean["weight"] < 0:
            return "ERROR: weight must be 0 or more."
    if "reps" in values:
        try:
            reps = float(values["reps"])
        except (TypeError, ValueError):
            return f"ERROR: reps must be a whole number, got '{values['reps']}'."
        if not reps.is_integer():
            return f"ERROR: reps must be a whole number, got '{values['reps']}'."
        if not 1 <= reps < 200:
            return "ERROR: reps must be between 1 and 199."
        clean["reps"] = int(reps)
    if "unit" in values:
        clean["unit"] = UNITS.get(str(values["unit"]).strip().lower() or "lbs")
        if clean["unit"] is None:
            return f"ERROR: unit must be 'lbs' or 'kg', got '{values['unit']}'."
    return clean


@tool
def resolve_exercise(query: str) -> str:
    """Find the exercise id for a name or abbreviation the user typed. Call this before logging or looking up any exercise.

    Args:
        query: The exercise as the user typed it, without numbers, e.g. "bench", "incline db", "squats".
    """
    result = exercises.get_index().resolve(query)
    if result["status"] == "match":
        return f"match: {_exercise_label(result['exercise'])}"
    if result["status"] == "ambiguous":
        return "ambiguous: " + "; ".join(_exercise_label(e) for e in result["candidates"]) + ". Ask the user which one."
    return f"none: no exercise matches '{query}'. Ask the user whether to add it."


@tool
def add_exercise(name: str, aliases: str, weight_type: str, muscle_group: str) -> str:
    """Add a new exercise to the user's list. Only call this after the user has confirmed they want it added.

    Args:
        name: Full exercise name, e.g. "Hack Squat".
        aliases: Comma-separated short names the user types for it, e.g. "hack, hack squats". Empty string if none.
        weight_type: One of barbell, dumbbell, machine, cable, bodyweight.
        muscle_group: Main muscle group, e.g. "quads". Empty string if unknown.
    """
    name = name.strip()
    weight_type = weight_type.strip().lower()
    if not name:
        return "ERROR: name is required."
    if weight_type not in exercises.WEIGHT_TYPES:
        return f"ERROR: weight_type must be one of {', '.join(exercises.WEIGHT_TYPES)}."
    alias_list = [a.strip().lower() for a in aliases.split(",") if a.strip()]
    ex_id = exercises.to_id(name)
    index = exercises.get_index()
    if ex_id in index.by_id:
        return f"ERROR: exercise id '{ex_id}' already exists."
    taken = index.taken_keys()
    clashes = [s for s in [name, *alias_list] if exercises.normalize(s) in taken]
    if clashes:
        return f"ERROR: already used by another exercise: {', '.join(clashes)}."
    db.get_db().add_user_exercise({"id": ex_id, "name": name, "aliases": alias_list,
                                   "weight_type": weight_type, "muscle_group": muscle_group.strip() or None})
    exercises.reload()
    return f"Added exercise {ex_id} ({name})."


@tool
def start_session(label: str) -> str:
    """Start a workout session. If one is already open, returns that one instead.

    Args:
        label: Optional session label such as "push day". Empty string if none.
    """
    session, created = db.get_db().start_session(label.strip())
    verb = "Started" if created else "Already open:"
    return f"{verb} session {session['id']} at {_time(session['started_at'])}."


@tool
def end_session() -> str:
    """End the active workout session. Only call this when the user says they are done."""
    session = db.get_db().end_session()
    if not session:
        return "ERROR: no active session."
    sets = session["sets"]
    n_ex = len({s["exercise_id"] for s in sets})
    return f"Ended session: {len(sets)} sets across {n_ex} exercises."


@tool
def log_set(exercise_id: str, weight: float, reps: int, unit: str, note: str) -> str:
    """Log one set. Call once per set: "3x8" means three calls. Starts a session automatically if none is open.

    Args:
        exercise_id: The id returned by resolve_exercise, e.g. "bench_press".
        weight: Weight lifted. Per dumbbell for dumbbell lifts. 0 for bodyweight, plus any added load.
        reps: Number of reps in this set.
        unit: "lbs" or "kg". Pass "lbs" if the user gave no unit.
        note: A short note the user attached to the set, or an empty string.
    """
    if exercise_id not in exercises.get_index().by_id:
        return f"ERROR: unknown exercise_id '{exercise_id}'. Call resolve_exercise first."
    checked = _check_set_values(weight=weight, reps=reps, unit=unit)
    if isinstance(checked, str):
        return checked

    database = db.get_db()
    session, created = database.start_session("")
    row = database.add_set(session["id"], exercise_id, checked["weight"], checked["reps"], checked["unit"],
                           note.strip())
    reply = f"Logged {_set_str(row)}"
    if created:
        reply += " (started a new session)"
    return reply


@tool
def undo_last_set() -> str:
    """Delete the most recent set in the active session."""
    database = db.get_db()
    session = database.active_session()
    if not session:
        return "ERROR: no active session."
    removed = database.delete_last_set(session["id"])
    if not removed:
        return "ERROR: the active session has no sets."
    return f"Removed {_set_str(removed)}."


@tool
def edit_set(set_number: int, weight: float | None = None, reps: int | None = None, unit: str | None = None,
             note: str | None = None) -> str:
    """Change a set already logged in the active session: fix its numbers or add a note.
    Use this, not log_set, when the user comments on or corrects a set they already did.

    Args:
        set_number: The set's number in get_active_session's list. -1 means the most recent set.
        weight: New weight, or None to keep it.
        reps: New reps, or None to keep them.
        unit: New unit, "lbs" or "kg", or None to keep it.
        note: New note, or None to keep it. An empty string removes the note.
    """
    database = db.get_db()
    session = database.active_session()
    if not session:
        return "ERROR: no active session."
    sets = database.session_sets(session["id"])
    if not sets:
        return "ERROR: the active session has no sets."
    if set_number == -1:
        set_number = len(sets)
    if not 1 <= set_number <= len(sets):
        return f"ERROR: set_number must be between 1 and {len(sets)}, or -1 for the most recent set."

    changes = _check_set_values(**{k: v for k, v in {"weight": weight, "reps": reps, "unit": unit}.items()
                                   if v is not None})
    if isinstance(changes, str):
        return changes
    if note is not None:
        changes["note"] = note.strip() or None
    if not changes:
        return "ERROR: nothing to change. Pass at least one of weight, reps, unit, note."

    before = sets[set_number - 1]
    old = _set_str(before)
    after = database.update_set(before["id"], changes)
    return f"Updated set {set_number}: {_set_str(after)} (was {old})."


@tool
def get_active_session() -> str:
    """Show the open session and its sets so far. Use it to repeat the last set ("another set")."""
    database = db.get_db()
    session = database.active_session()
    if not session:
        return "No session is open."
    sets = database.session_sets(session["id"])
    lines = [f"Session started {_time(session['started_at'])}" + (f" ({session['label']})" if session["label"] else "")]
    if not sets:
        lines.append("No sets yet.")
    else:
        lines += [f"{i}. {_set_str(s)}" for i, s in enumerate(sets, 1)]
        last = sets[-1]
        lines.append(f"Last set: exercise_id={last['exercise_id']}, weight={_w(last['weight'])}, "
                     f"reps={last['reps']}, unit={last['unit']}")
    return "\n".join(lines)


MAX_EMPTY_DAYS = 31  # date ranges up to this long also list days with nothing logged
DEFAULT_RECENT_DAYS = 7  # used when no filter narrows the search


def _runs(sets: list[dict]) -> str:
    """'3×8 @135 lbs, 1×1 @225 lbs (PR)': consecutive identical sets collapsed into one entry."""
    parts = []
    for s in sets:
        key = (float(s["weight"]), s["unit"], s["reps"], s.get("note") or "")
        if parts and parts[-1][0] == key:
            parts[-1][1] += 1
        else:
            parts.append([key, 1])
    out = []
    for (weight, unit, reps, note), count in parts:
        load = "bodyweight" if weight == 0 else f"@{weight:g} {unit}"
        out.append(f"{count}×{reps} {load}" + (f" ({note})" if note else ""))
    return ", ".join(out)


def _day_line(d: date, sets: list[dict]) -> str:
    label = d.strftime("%a %Y-%m-%d")
    if not sets:
        return f"{label}: nothing logged"
    by_exercise: dict[str, list[dict]] = {}
    for s in sets:
        by_exercise.setdefault(s["exercise_id"], []).append(s)
    n_sessions = len({s["session_id"] for s in sets})
    summary = "; ".join(f"{ex}: {_runs(ex_sets)}" for ex, ex_sets in by_exercise.items())
    counts = f"{len(sets)} set{'s' if len(sets) > 1 else ''}, {n_sessions} session{'s' if n_sessions > 1 else ''}"
    return f"{label} ({counts}): {summary}"


@tool
def find_workouts(muscle_groups: list | None = None, exercise_ids: list | None = None, start_date: str | None = None,
                  end_date: str | None = None, most_recent_days: int | None = None,
                  include_current_session: bool = True) -> str:
    """Find logged sets, one line per day (oldest first), with each day's sets grouped by exercise.
    Every filter is optional and they combine. Examples:
    last time chest: find_workouts(muscle_groups=["chest"], most_recent_days=1)
    last week: find_workouts(start_date="2026-10-11", end_date="2026-10-17")
    same as last time on squat: find_workouts(exercise_ids=["back_squat"], most_recent_days=1, include_current_session=False)

    Args:
        muscle_groups: Muscle groups to match, from: chest, back, shoulders, biceps, triceps, quads, hamstrings, glutes, calves, core, traps, lower back. Exercises matching muscle_groups or exercise_ids are included.
        exercise_ids: Exercise ids from resolve_exercise, e.g. ["bench_press"].
        start_date: First day to include, "YYYY-MM-DD" in the user's local time.
        end_date: Last day to include, "YYYY-MM-DD" in the user's local time.
        most_recent_days: Keep only the latest N days that have matching sets (1 = "the last time"). Without any filter, the latest 7 days are returned.
        include_current_session: False leaves out the session that is still open.
    """
    index = exercises.get_index()
    ids = None
    if muscle_groups or exercise_ids:
        ids = set()
        if muscle_groups:
            groups = {str(g).strip().lower() for g in muscle_groups}
            known = {e.get("muscle_group") for e in index.by_id.values() if e.get("muscle_group")}
            unknown = groups - known
            if unknown:
                return f"ERROR: unknown muscle group(s) {', '.join(sorted(unknown))}. Use: {', '.join(sorted(known))}."
            ids |= {e_id for e_id, e in index.by_id.items() if e.get("muscle_group") in groups}
        if exercise_ids:
            unknown = [e for e in exercise_ids if e not in index.by_id]
            if unknown:
                return f"ERROR: unknown exercise_id(s) {', '.join(map(str, unknown))}. Call resolve_exercise first."
            ids |= set(exercise_ids)

    tz = _tz()
    try:
        first = date.fromisoformat(start_date.strip()) if start_date else None
        last = date.fromisoformat(end_date.strip()) if end_date else None
    except (AttributeError, ValueError):
        return 'ERROR: start_date and end_date must be "YYYY-MM-DD".'
    if first and last and first > last:
        return "ERROR: start_date is after end_date."
    if most_recent_days is not None and most_recent_days < 1:
        return "ERROR: most_recent_days must be 1 or more."
    if ids is None and not first and not last and most_recent_days is None:
        most_recent_days = DEFAULT_RECENT_DAYS

    database = db.get_db()
    exclude = None
    if not include_current_session:
        active = database.active_session()
        exclude = active["id"] if active else None
    rows = database.find_sets(
        exercise_ids=sorted(ids) if ids is not None else None,
        start=datetime.combine(first, time.min, tz) if first else None,
        end=datetime.combine(last + timedelta(days=1), time.min, tz) if last else None,
        exclude_session_id=exclude,
    )

    by_day: dict[date, list[dict]] = {}
    for s in rows:  # newest first
        by_day.setdefault(s["logged_at"].astimezone(tz).date(), []).append(s)
    days = list(by_day)[:most_recent_days] if most_recent_days else list(by_day)
    if first and last and not most_recent_days and (last - first).days < MAX_EMPTY_DAYS:
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    if not days:
        return "No matching sets found."
    return "\n".join(_day_line(d, sorted(by_day.get(d, []), key=lambda s: s["logged_at"])) for d in sorted(days))


@tool
def get_latest_session(include_current_session: bool = False) -> str:
    """Overview of the most recent session that has sets: when it was, how long it took, and every exercise
    with its sets, in the order done. Use it for "what did I do last session?" or "recap my last workout".

    Args:
        include_current_session: True lets the open session count as the latest. By default it is skipped,
            so mid-workout this returns the previous session.
    """
    database = db.get_db()
    exclude = None
    if not include_current_session:
        active = database.active_session()
        exclude = active["id"] if active else None
    latest = database.find_sets(exclude_session_id=exclude, limit=1)
    if not latest:
        return "No past sessions with sets found."
    session = database.get_session(latest[0]["session_id"])
    sets = database.session_sets(session["id"])

    start, end = session["started_at"], session["ended_at"]
    when = _time(start) + (f" to {end.astimezone(_tz()).strftime('%H:%M')}"
                           f" ({round((end - start).total_seconds() / 60)} min)" if end else " (still open)")
    by_exercise: dict[str, list[dict]] = {}
    for s in sets:
        by_exercise.setdefault(s["exercise_id"], []).append(s)
    volume = sum(db.weight_in_lbs(s) * s["reps"] for s in sets)
    lines = [f"Session {when}" + (f" ({session['label']})" if session["label"] else ""),
             f"{len(sets)} sets across {len(by_exercise)} exercises, {volume:,.0f} lbs total volume"]
    lines += [f"- {ex}: {_runs(ex_sets)}" for ex, ex_sets in by_exercise.items()]
    return "\n".join(lines)


@tool
def get_pr(exercise_id: str) -> str:
    """Get the personal record (heaviest weight for any reps) for an exercise.

    Args:
        exercise_id: The id returned by resolve_exercise, e.g. "bench_press".
    """
    if exercise_id not in exercises.get_index().by_id:
        return f"ERROR: unknown exercise_id '{exercise_id}'. Call resolve_exercise first."
    pr = db.get_db().get_pr(exercise_id)
    if not pr:
        return f"ERROR: no sets logged for {exercise_id}."
    return f"PR for {exercise_id}: {_set_str(pr, with_exercise=False)} on {_date(pr['logged_at'])}"


ALL_TOOLS = [resolve_exercise, add_exercise, start_session, end_session, log_set, undo_last_set, edit_set,
             get_active_session, find_workouts, get_latest_session, get_pr]
WRITE_TOOLS = {"add_exercise", "start_session", "end_session", "log_set", "undo_last_set", "edit_set"}
