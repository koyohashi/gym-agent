import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db  # noqa: E402
import exercises  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

HAVE_SUPABASE = all(os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"))


@pytest.fixture(params=["memory", pytest.param("supabase", marks=pytest.mark.skipif(
    not HAVE_SUPABASE, reason="SUPABASE_URL / SUPABASE_SERVICE_KEY not set"))])
def database(request):
    """A clean database per test. Supabase tests use a random user_id and delete its rows afterwards."""
    if request.param == "memory":
        database = db.MemoryDB()
    else:
        database = db.SupabaseDB(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"], str(uuid.uuid4()))
    db.set_db(database)
    exercises.reload()
    yield database
    if request.param == "supabase":
        for table in ("sets", "sessions", "user_exercises"):
            database.client.table(table).delete().eq("user_id", database.user_id).execute()
    db.set_db(None)
    exercises.reload()


@pytest.fixture
def memdb():
    database = db.MemoryDB()
    db.set_db(database)
    exercises.reload()
    yield database
    db.set_db(None)
    exercises.reload()
