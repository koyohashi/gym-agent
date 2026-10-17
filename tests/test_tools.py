import pytest

import tools


def call(t, **kwargs):
    return t(**kwargs)


@pytest.fixture(autouse=True)
def _db(database):
    return database


def test_resolve(database):
    assert call(tools.resolve_exercise, query="bench").startswith("match: bench_press")
    assert call(tools.resolve_exercise, query="row").startswith("ambiguous: ")
    assert call(tools.resolve_exercise, query="hack squat").startswith("none: ")


def test_log_set_autostarts_and_confirms(database):
    out = call(tools.log_set, exercise_id="bench_press", weight=135, reps=8, unit="lbs", note="")
    assert out == "Logged bench_press 135 lbs x 8 (started a new session)"
    out = call(tools.log_set, exercise_id="bench_press", weight=60, reps=5, unit="KG", note="paused")
    assert out == "Logged bench_press 60 kg x 5 (paused)"


@pytest.mark.parametrize("kwargs,error", [
    ({"exercise_id": "nope"}, "unknown exercise_id"),
    ({"weight": -5}, "weight must be 0 or more"),
    ({"weight": "heavy"}, "weight must be a number"),
    ({"reps": 0}, "reps must be between"),
    ({"reps": 200}, "reps must be between"),
    ({"reps": 7.5}, "whole number"),
    ({"unit": "stone"}, "unit must be"),
])
def test_log_set_errors(database, kwargs, error):
    args = {"exercise_id": "bench_press", "weight": 135, "reps": 8, "unit": "lbs", "note": ""} | kwargs
    out = call(tools.log_set, **args)
    assert out.startswith("ERROR:") and error in out
    assert database.active_session() is None


def test_sessions(database):
    assert call(tools.end_session) == "ERROR: no active session."
    assert call(tools.start_session, label="legs").startswith("Started session")
    assert call(tools.start_session, label="").startswith("Already open:")
    assert call(tools.get_active_session).endswith("No sets yet.")
    call(tools.log_set, exercise_id="back_squat", weight=225, reps=5, unit="lbs", note="")
    call(tools.log_set, exercise_id="leg_press", weight=400, reps=10, unit="lbs", note="")
    active = call(tools.get_active_session)
    assert "Last set: exercise_id=leg_press, weight=400, reps=10, unit=lbs" in active
    assert call(tools.end_session) == "Ended session: 2 sets across 2 exercises."
    assert call(tools.get_active_session) == "No session is open."


def test_undo(database):
    assert call(tools.undo_last_set) == "ERROR: no active session."
    call(tools.start_session, label="")
    assert call(tools.undo_last_set) == "ERROR: the active session has no sets."
    call(tools.log_set, exercise_id="bench_press", weight=135, reps=8, unit="lbs", note="")
    assert call(tools.undo_last_set) == "Removed bench_press 135 lbs x 8."


def test_last_performance_and_pr(database):
    assert call(tools.get_last_performance, exercise_id="back_squat").startswith("ERROR:")
    assert call(tools.get_pr, exercise_id="back_squat").startswith("ERROR:")
    assert call(tools.get_pr, exercise_id="nope").startswith("ERROR: unknown")
    call(tools.log_set, exercise_id="back_squat", weight=225, reps=5, unit="lbs", note="")
    call(tools.log_set, exercise_id="back_squat", weight=110, reps=3, unit="kg", note="")
    call(tools.end_session)
    call(tools.log_set, exercise_id="back_squat", weight=230, reps=5, unit="lbs", note="")
    last = call(tools.get_last_performance, exercise_id="back_squat")
    assert last.startswith("Last time (") and last.endswith("back_squat: 225 lbs x 5, 110 kg x 3")
    assert call(tools.get_pr, exercise_id="back_squat").startswith("PR for back_squat: 110 kg x 3 on ")


def test_add_exercise(database):
    assert call(tools.add_exercise, name="Hack Squat", aliases="hack, hacks", weight_type="machine",
                muscle_group="quads") == "Added exercise hack_squat (Hack Squat)."
    assert call(tools.resolve_exercise, query="hack").startswith("match: hack_squat")
    assert "already exists" in call(tools.add_exercise, name="Hack Squat", aliases="", weight_type="machine",
                                     muscle_group="")
    assert "already used" in call(tools.add_exercise, name="Pendulum Squat", aliases="bench", weight_type="machine",
                                  muscle_group="")
    assert "weight_type must be" in call(tools.add_exercise, name="Thing", aliases="", weight_type="kettlebell",
                                         muscle_group="")
