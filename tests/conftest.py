import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import exercises  # noqa: E402


@pytest.fixture(scope="session")
def local_supabase():
    """URL and service key of the local Supabase stack. Never reads .env, so tests can't touch production."""
    try:
        out = subprocess.run(["supabase", "status", "-o", "env"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.fail("Local Supabase is not running. Run the tests with scripts/test-db.sh.", pytrace=False)
    env = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return env["API_URL"].strip('"'), env["SERVICE_ROLE_KEY"].strip('"')


@pytest.fixture
def database(local_supabase):
    """A clean database per test: a random user_id whose rows are deleted afterwards."""
    database = db.SupabaseDB(*local_supabase, str(uuid.uuid4()))
    db.set_db(database)
    exercises.reload()
    yield database
    for table in ("sets", "sessions", "user_exercises"):
        database.client.table(table).delete().eq("user_id", database.user_id).execute()
    db.set_db(None)
    exercises.reload()
