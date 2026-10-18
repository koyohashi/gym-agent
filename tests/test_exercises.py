import pytest

import exercises


@pytest.fixture
def index(database):
    return exercises.get_index()


def test_starter_list_is_valid():
    data = exercises.load_base()
    assert len(data) >= 50
    ids = [e["id"] for e in data]
    assert len(ids) == len(set(ids))
    seen = {}
    for e in data:
        assert e["id"] == exercises.to_id(e["id"])
        assert e["weight_type"] in exercises.WEIGHT_TYPES
        for s in exercises.ExerciseIndex.names_of(e):
            key = exercises.normalize(s)
            assert seen.setdefault(key, e["id"]) == e["id"], f"'{s}' used by {seen[key]} and {e['id']}"


@pytest.mark.parametrize("query", ["bench", "bp", "flat bench", "Bench", "bench press", "benhc press"])
def test_bench_aliases(index, query):
    result = index.resolve(query)
    assert result["status"] == "match" and result["exercise"]["id"] == "bench_press"


@pytest.mark.parametrize("query,expected", [
    ("squats", "back_squat"), ("pull ups", "pull_up"), ("pull-ups", "pull_up"), ("incline db", "incline_dumbbell_press"),
    ("deadlift", "deadlift"), ("rdl", "romanian_deadlift"), ("lat pulldown", "lat_pulldown"), ("dips", "dip"),
])
def test_common_queries(index, query, expected):
    result = index.resolve(query)
    assert result["status"] == "match" and result["exercise"]["id"] == expected


@pytest.mark.parametrize("query", ["row", "curl", "fly"])
def test_ambiguous(index, query):
    result = index.resolve(query)
    assert result["status"] == "ambiguous"
    assert 2 <= len(result["candidates"]) <= exercises.MAX_CANDIDATES


@pytest.mark.parametrize("query", ["hack squat", "zercher", "smith machine bench", ""])
def test_unknown(index, query):
    assert index.resolve(query)["status"] == "none"


def test_user_exercises_are_merged(database):
    database.add_user_exercise({"id": "hack_squat", "name": "Hack Squat", "aliases": ["hack"],
                             "weight_type": "machine", "muscle_group": "quads"})
    exercises.reload()
    result = exercises.get_index().resolve("hack")
    assert result["status"] == "match" and result["exercise"]["id"] == "hack_squat"
