"""Exercise list: loads data/exercises.json, merges user-added exercises from db.py, fuzzy-matches names."""

import json
import re
from pathlib import Path

from rapidfuzz import fuzz

import db

EXERCISES_PATH = Path(__file__).parent / "data" / "exercises.json"
WEIGHT_TYPES = ("barbell", "dumbbell", "machine", "cable", "bodyweight")

# Matching thresholds, tuned by tests/test_exercises.py.
TOKEN_MIN = 80  # every query word must match some candidate word at least this well
STRONG_MATCH = 90  # a fuzzy winner must score at least this...
MATCH_MARGIN = 10  # ...and beat the runner-up by this much to count as a match
MAX_CANDIDATES = 3


def normalize(text: str) -> str:
    """Lowercase, turn separators into spaces, drop punctuation, and strip simple plurals."""
    text = re.sub(r"[-_/.]", " ", text.lower())
    text = re.sub(r"[^a-z0-9 ]", "", text)
    words = []
    for word in text.split():
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return " ".join(words)


def to_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def load_base() -> list[dict]:
    with open(EXERCISES_PATH) as f:
        return json.load(f)


class ExerciseIndex:
    def __init__(self, exercises: list[dict]):
        self.by_id = {e["id"]: e for e in exercises}
        self._exact: dict[str, set[str]] = {}
        self._strings: list[tuple[str, str]] = []  # (exercise id, normalized string)
        for e in exercises:
            for s in self.names_of(e):
                key = normalize(s)
                self._exact.setdefault(key, set()).add(e["id"])
                self._strings.append((e["id"], key))

    @staticmethod
    def names_of(exercise: dict) -> list[str]:
        return [exercise["id"], exercise["name"], *exercise.get("aliases", [])]

    def taken_keys(self) -> set[str]:
        return set(self._exact)

    def resolve(self, query: str) -> dict:
        """Return {"status": "match", "exercise": e}, {"status": "ambiguous", "candidates": [...]}, or {"status": "none"}."""
        q = normalize(query)
        if not q:
            return {"status": "none"}

        exact = self._exact.get(q, set())
        if len(exact) == 1:
            return {"status": "match", "exercise": self.by_id[next(iter(exact))]}

        q_words = q.split()
        scores: dict[str, float] = {}
        for ex_id, s in self._strings:
            s_words = s.split()
            if all(max(fuzz.ratio(w, sw) for sw in s_words) >= TOKEN_MIN for w in q_words):
                scores[ex_id] = max(scores.get(ex_id, 0), fuzz.token_sort_ratio(q, s))

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked:
            return {"status": "none"}
        if len(ranked) == 1 or (ranked[0][1] >= STRONG_MATCH and ranked[0][1] - ranked[1][1] >= MATCH_MARGIN):
            return {"status": "match", "exercise": self.by_id[ranked[0][0]]}
        return {"status": "ambiguous", "candidates": [self.by_id[i] for i, _ in ranked[:MAX_CANDIDATES]]}


_index: ExerciseIndex | None = None


def get_index() -> ExerciseIndex:
    global _index
    if _index is None:
        _index = ExerciseIndex(load_base() + db.get_db().list_user_exercises())
    return _index


def reload() -> None:
    global _index
    _index = None
