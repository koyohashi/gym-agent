from datetime import timedelta

import pytest

import db


def test_session_lifecycle(database):
    assert database.active_session() is None
    s1, created = database.start_session("push")
    assert created and s1["label"] == "push"
    s2, created = database.start_session("")
    assert not created and s2["id"] == s1["id"]
    database.add_set(s1["id"], "bench_press", 135, 8, "lbs", "")
    database.add_set(s1["id"], "dip", 0, 10, "lbs", "")
    ended = database.end_session()
    assert ended["ended_at"] is not None and len(ended["sets"]) == 2
    assert database.active_session() is None
    assert database.end_session() is None


def test_add_and_undo(database):
    s, _ = database.start_session("")
    database.add_set(s["id"], "bench_press", 135, 8, "lbs", "")
    database.add_set(s["id"], "bench_press", 145, 6, "lbs", "felt heavy")
    sets = database.session_sets(s["id"])
    assert [x["reps"] for x in sets] == [8, 6] and sets[1]["note"] == "felt heavy"
    removed = database.delete_last_set(s["id"])
    assert float(removed["weight"]) == 145
    assert database.delete_last_set(s["id"])["reps"] == 8
    assert database.delete_last_set(s["id"]) is None


def test_find_sets_filters(database):
    old, _ = database.start_session("")
    database.add_set(old["id"], "back_squat", 225, 5, "lbs", "")
    database.add_set(old["id"], "bench_press", 135, 8, "lbs", "")
    database.add_set(old["id"], "back_squat", 225, 4, "lbs", "")
    database.end_session()
    cur, _ = database.start_session("")
    database.add_set(cur["id"], "back_squat", 235, 5, "lbs", "")

    squats = database.find_sets(exercise_ids=["back_squat"], exclude_session_id=cur["id"])
    assert [(float(s["weight"]), s["reps"]) for s in squats] == [(225, 4), (225, 5)]  # newest first
    assert len(database.find_sets(exercise_ids=["back_squat", "bench_press"])) == 4
    assert database.find_sets(exercise_ids=["deadlift"]) == []
    assert database.find_sets(start=db.now() + timedelta(days=1)) == []


def test_pr_mixes_units(database):
    s, _ = database.start_session("")
    database.add_set(s["id"], "deadlift", 300, 3, "lbs", "")
    database.add_set(s["id"], "deadlift", 140, 1, "kg", "")  # 308.6 lbs
    database.add_set(s["id"], "deadlift", 305, 2, "lbs", "")
    pr = database.get_pr("deadlift")
    assert pr["unit"] == "kg" and float(pr["weight"]) == 140
    assert database.get_pr("bench_press") is None


def test_pr_tie_goes_to_most_recent(database):
    s, _ = database.start_session("")
    database.add_set(s["id"], "bench_press", 225, 1, "lbs", "")
    database.add_set(s["id"], "bench_press", 225, 3, "lbs", "")
    assert database.get_pr("bench_press")["reps"] == 3


def test_user_exercises(database):
    database.add_user_exercise({"id": "hack_squat", "name": "Hack Squat", "aliases": ["hack"],
                                "weight_type": "machine", "muscle_group": "quads"})
    assert database.list_user_exercises() == [{"id": "hack_squat", "name": "Hack Squat", "aliases": ["hack"],
                                               "weight_type": "machine", "muscle_group": "quads"}]


def test_one_active_session_index(database):
    """The unique index rejects a second open session even if the app's check is bypassed."""
    if isinstance(database, db.MemoryDB):
        pytest.skip("index exists only in Postgres")
    from postgrest.exceptions import APIError

    database.start_session("")
    with pytest.raises(APIError) as exc:
        database.client.table("sessions").insert({"user_id": database.user_id}).execute()
    assert exc.value.code == "23505"
