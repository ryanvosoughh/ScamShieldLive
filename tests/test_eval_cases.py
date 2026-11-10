"""4A The evaluation test set (eval/cases.json): its shape, so a typo can't skew the results.

No model calls: this only checks the file. eval/README.md says how the cases were made.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from app.analysis.analyzer import normalised_words
from app.analysis.prompts import NO_SCAM, OTHER_SCAM, SCAM_TYPES
from app.demo.scenarios import CALLS_DIR, load_scenario

CASES = json.loads((Path(__file__).resolve().parents[1] / "eval" / "cases.json").read_text())
FIELDS = {"id", "label", "scam_type", "tags", "source", "seen_in_development", "tests", "text"}
SOURCES = {"claude-drafted", "hand-written", "public-paraphrase"}
# About 30 s of speech, the length of the live check's window, so one check
# on the whole case sees what the live check would see.
MAX_WORDS = 80
SCAMS = [case for case in CASES if case["label"] == "scam"]
NORMALS = [case for case in CASES if case["label"] == "normal"]


def test_ids_are_unique():
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_every_case_is_complete(case):
    assert set(case) == FIELDS
    assert case["label"] in ("scam", "normal")
    assert case["source"] in SOURCES
    assert isinstance(case["seen_in_development"], bool)
    assert isinstance(case["tags"], list) and case["tags"]
    assert case["tests"].strip()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_the_scam_type_matches_the_label(case):
    if case["label"] == "scam":
        assert case["scam_type"] in {*SCAM_TYPES, OTHER_SCAM}
    else:
        assert case["scam_type"] == NO_SCAM


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_each_case_fits_in_one_check(case):
    assert 20 <= len(case["text"].split()) <= MAX_WORDS


def test_the_set_is_balanced_and_covers_the_hard_cases():
    assert len(SCAMS) >= 10 and len(NORMALS) >= 10
    types = Counter(case["scam_type"] for case in SCAMS)
    assert all(types[scam_type] >= 2 for scam_type in SCAM_TYPES), types
    assert sum("polite" in case["tags"] for case in SCAMS) >= 4
    assert sum("lookalike" in case["tags"] for case in NORMALS) >= 4


def test_no_case_reuses_a_demo_script_line():
    # The demo scripts were used while tuning the prompt, so they would flatter the results.
    cases = [f" {normalised_words(case['text'])} " for case in CASES]
    for script in sorted(CALLS_DIR.glob("*.json")):
        for line in load_scenario(script.stem).lines:
            words = normalised_words(line.text)
            if len(words.split()) >= 5:
                assert not any(f" {words} " in case for case in cases), (script.stem, line.text)
