"""4D The report: the numbers it works out, from a small made-up results file (no model calls)."""
import importlib.util
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL_DIR))  # time_to_warning imports run_eval from next to it


def load(name):
    spec = importlib.util.spec_from_file_location(name, EVAL_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_report = load("make_report")
time_to_warning = load("time_to_warning")


def result(id, label, level, outcome, risk, tags=("plain",), red_flags=()):
    return {
        "id": id, "label": label, "level": level, "outcome": outcome, "risk": risk, "tags": list(tags),
        "red_flags": list(red_flags), "reason": "a reason", "seconds": 0.5,
    }


RESULTS = [
    result("s1", "scam", "red", "caught", 90),
    result("s2", "scam", "yellow", "caught", 50, tags=("polite",)),
    result("s3", "scam", "green", "missed", 20, tags=("polite",)),
    result("n1", "normal", "green", "correct", 10),
    result("n2", "normal", "red", "false_alarm", 75, tags=("lookalike",), red_flags=("asks_for_code",)),
    result("n3", "normal", "unknown", "unknown", None),
]
RUN = {"run_at": "2026-11-10T00:00:00+00:00", "model": "m", "yellow_threshold": 40, "red_threshold": 70,
       "prompt_sha256": "p", "cases_sha256": "c", "git_commit": "g", "cases": 6}


def test_rates_on_both_lines_leave_out_failed_checks():
    warned = make_report.rates(RESULTS, make_report.WARNED)
    assert warned == {"recall": (2, 3), "precision": (2, 3), "false_alarm_rate": (1, 2)}
    red = make_report.rates(RESULTS, make_report.RED_ONLY)
    assert red == {"recall": (1, 3), "precision": (1, 2), "false_alarm_rate": (1, 2)}


def test_no_warnings_at_all_is_not_a_division_by_zero():
    assert make_report.percent((0, 0)) == "n/a (0/0)"
    assert make_report.percent((2, 3)) == "67% (2/3)"


def test_by_tag_counts_right_and_wrong():
    assert ("polite", 2, 1, 1) in make_report.by_tag(RESULTS)


def test_the_report_lists_every_case_the_mistakes_and_the_near_misses():
    text = make_report.build_report({"run": RUN, "results": RESULTS}, timing=None)
    for case in RESULTS:
        assert f"`{case['id']}`" in text
    assert "**`s3`, missed:**" in text
    assert "**`n2`, false alarm:**" in text
    assert "**`s2`, near miss:**" in text  # caught, but only yellow


def test_the_markers_come_from_the_demo_script():
    from app.demo.scenarios import load_scenario

    marks = time_to_warning.markers(load_scenario("grandchild_scam"), yellow_threshold=40)
    assert marks == {"warning_sign_at": 19.5, "ask_at": 34.0}
    assert time_to_warning.markers(load_scenario("normal_call"), 40) == {"warning_sign_at": None, "ask_at": None}
