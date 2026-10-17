"""All database access. The only module that imports supabase.

Two backends share one interface: SupabaseDB (production) and MemoryDB (tests, evals,
and local runs with DB_BACKEND=memory). Rows are plain dicts with datetime timestamps.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

KG_TO_LBS = 2.20462
FIND_LIMIT = 1000  # PostgREST's default max rows per request


def now() -> datetime:
    return datetime.now(timezone.utc)


def weight_in_lbs(s: dict) -> float:
    return float(s["weight"]) * (KG_TO_LBS if s["unit"] == "kg" else 1)


class Database:
    user_id: str

    # Sessions
    def active_session(self) -> dict | None: ...
    def start_session(self, label: str = "") -> tuple[dict, bool]:
        """Open a session, or return the open one. Returns (session, created)."""
    def end_session(self) -> dict | None:
        """Close the active session. Returns it with its sets, or None if none is open."""
    # Sets
    def add_set(self, session_id: str, exercise_id: str, weight: float, reps: int, unit: str, note: str) -> dict: ...
    def session_sets(self, session_id: str) -> list[dict]:
        """Sets in a session, oldest first."""
    def delete_last_set(self, session_id: str) -> dict | None: ...
    def update_set(self, set_id: str, changes: dict) -> dict:
        """Apply changes (weight, reps, unit, note) to one set and return the updated row."""
    def exercise_sets(self, exercise_id: str) -> list[dict]: ...
    def recent_sets(self, limit: int) -> list[dict]:
        """The user's most recent sets across all sessions, newest first."""
    def find_sets(self, exercise_ids: list[str] | None = None, start: datetime | None = None,
                  end: datetime | None = None, exclude_session_id: str | None = None,
                  limit: int = FIND_LIMIT) -> list[dict]:
        """The user's sets matching every given filter (logged in [start, end)), newest first."""
    # User exercises
    def add_user_exercise(self, exercise: dict) -> dict: ...
    def list_user_exercises(self) -> list[dict]: ...

    def get_pr(self, exercise_id: str) -> dict | None:
        """Heaviest set for any reps, compared in lbs. Ties go to the most recent set."""
        sets = self.exercise_sets(exercise_id)
        if not sets:
            return None
        return max(sets, key=lambda s: (weight_in_lbs(s), s["logged_at"]))


class MemoryDB(Database):
    def __init__(self, user_id: str | None = None):
        self.user_id = user_id or str(uuid.uuid4())
        self.sessions: list[dict] = []
        self.sets: list[dict] = []
        self.user_exercises: list[dict] = []
        self._last_ts = now() - timedelta(seconds=1)

    def _ts(self) -> datetime:
        # Strictly increasing timestamps keep "most recent" well defined in fast tests.
        self._last_ts = max(now(), self._last_ts + timedelta(microseconds=1))
        return self._last_ts

    def active_session(self):
        return next((s for s in self.sessions if s["ended_at"] is None), None)

    def start_session(self, label="", started_at=None):
        active = self.active_session()
        if active:
            return active, False
        session = {"id": str(uuid.uuid4()), "user_id": self.user_id, "started_at": started_at or self._ts(),
                   "ended_at": None, "label": label or None}
        self.sessions.append(session)
        return session, True

    def end_session(self, ended_at=None):
        active = self.active_session()
        if not active:
            return None
        active["ended_at"] = ended_at or self._ts()
        return {**active, "sets": self.session_sets(active["id"])}

    def add_set(self, session_id, exercise_id, weight, reps, unit, note, logged_at=None):
        row = {"id": str(uuid.uuid4()), "user_id": self.user_id, "session_id": session_id,
               "exercise_id": exercise_id, "weight": weight, "reps": reps, "unit": unit,
               "note": note or None, "logged_at": logged_at or self._ts()}
        self.sets.append(row)
        return row

    def session_sets(self, session_id):
        return sorted((s for s in self.sets if s["session_id"] == session_id), key=lambda s: s["logged_at"])

    def delete_last_set(self, session_id):
        sets = self.session_sets(session_id)
        if not sets:
            return None
        self.sets.remove(sets[-1])
        return sets[-1]

    def update_set(self, set_id, changes):
        row = next(s for s in self.sets if s["id"] == set_id)
        row.update(changes)
        return row

    def exercise_sets(self, exercise_id):
        return [s for s in self.sets if s["exercise_id"] == exercise_id]

    def recent_sets(self, limit):
        return sorted(self.sets, key=lambda s: s["logged_at"], reverse=True)[:limit]

    def find_sets(self, exercise_ids=None, start=None, end=None, exclude_session_id=None, limit=FIND_LIMIT):
        rows = [s for s in self.sets
                if (exercise_ids is None or s["exercise_id"] in exercise_ids)
                and (start is None or s["logged_at"] >= start) and (end is None or s["logged_at"] < end)
                and s["session_id"] != exclude_session_id]
        return sorted(rows, key=lambda s: s["logged_at"], reverse=True)[:limit]

    def add_user_exercise(self, exercise):
        row = {**exercise, "user_id": self.user_id}
        self.user_exercises.append(row)
        return row

    def list_user_exercises(self):
        return [{k: v for k, v in e.items() if k != "user_id"} for e in self.user_exercises]


class SupabaseDB(Database):
    def __init__(self, url: str, key: str, user_id: str):
        from supabase import create_client

        self.client = create_client(url, key)
        self.user_id = user_id

    @staticmethod
    def _row(row: dict) -> dict:
        for k in ("started_at", "ended_at", "logged_at"):
            if isinstance(row.get(k), str):
                row[k] = datetime.fromisoformat(row[k])
        return row

    def _rows(self, response) -> list[dict]:
        return [self._row(r) for r in response.data]

    def active_session(self):
        rows = self._rows(self.client.table("sessions").select("*").eq("user_id", self.user_id)
                          .is_("ended_at", "null").limit(1).execute())
        return rows[0] if rows else None

    def start_session(self, label=""):
        from postgrest.exceptions import APIError

        active = self.active_session()
        if active:
            return active, False
        try:
            rows = self._rows(self.client.table("sessions")
                              .insert({"user_id": self.user_id, "label": label or None}).execute())
            return rows[0], True
        except APIError as e:
            if e.code == "23505":  # one_active_session: another request opened one first
                return self.active_session(), False
            raise

    def end_session(self):
        active = self.active_session()
        if not active:
            return None
        rows = self._rows(self.client.table("sessions").update({"ended_at": now().isoformat()})
                          .eq("id", active["id"]).execute())
        return {**rows[0], "sets": self.session_sets(active["id"])}

    def add_set(self, session_id, exercise_id, weight, reps, unit, note):
        row = {"user_id": self.user_id, "session_id": session_id, "exercise_id": exercise_id,
               "weight": weight, "reps": reps, "unit": unit, "note": note or None}
        return self._rows(self.client.table("sets").insert(row).execute())[0]

    def session_sets(self, session_id):
        return self._rows(self.client.table("sets").select("*").eq("session_id", session_id)
                          .order("logged_at").execute())

    def delete_last_set(self, session_id):
        rows = self._rows(self.client.table("sets").select("*").eq("session_id", session_id)
                          .order("logged_at", desc=True).limit(1).execute())
        if not rows:
            return None
        self.client.table("sets").delete().eq("id", rows[0]["id"]).execute()
        return rows[0]

    def update_set(self, set_id, changes):
        return self._rows(self.client.table("sets").update(changes).eq("id", set_id)
                          .eq("user_id", self.user_id).execute())[0]

    def exercise_sets(self, exercise_id):
        return self._rows(self.client.table("sets").select("*").eq("user_id", self.user_id)
                          .eq("exercise_id", exercise_id).execute())

    def recent_sets(self, limit):
        return self._rows(self.client.table("sets").select("*").eq("user_id", self.user_id)
                          .order("logged_at", desc=True).limit(limit).execute())

    def find_sets(self, exercise_ids=None, start=None, end=None, exclude_session_id=None, limit=FIND_LIMIT):
        query = self.client.table("sets").select("*").eq("user_id", self.user_id)
        if exercise_ids is not None:
            query = query.in_("exercise_id", list(exercise_ids))
        if start is not None:
            query = query.gte("logged_at", start.isoformat())
        if end is not None:
            query = query.lt("logged_at", end.isoformat())
        if exclude_session_id:
            query = query.neq("session_id", exclude_session_id)
        return self._rows(query.order("logged_at", desc=True).limit(limit).execute())

    def add_user_exercise(self, exercise):
        return self.client.table("user_exercises").insert({**exercise, "user_id": self.user_id}).execute().data[0]

    def list_user_exercises(self):
        rows = self.client.table("user_exercises").select("id,name,aliases,weight_type,muscle_group") \
            .eq("user_id", self.user_id).execute().data
        return rows


_db: Database | None = None


def from_env() -> Database:
    if os.environ.get("DB_BACKEND", "supabase") == "memory":
        return MemoryDB(os.environ.get("APP_USER_ID"))
    return SupabaseDB(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"], os.environ["APP_USER_ID"])


def get_db() -> Database:
    global _db
    if _db is None:
        _db = from_env()
    return _db


def set_db(database: Database) -> None:
    """Swap the backend (tests and evals use MemoryDB)."""
    global _db
    _db = database
