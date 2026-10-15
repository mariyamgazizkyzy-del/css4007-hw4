import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from tools import calculate, lookup, run_tool


# ---------------------------------------------------------------- lookup
def test_lookup_correct_2025_number():
    r = lookup("Millbrook", "population_2025")
    assert r["value"] == 37203 and r["source"] == "NR-11"


def test_lookup_all_three_population_templates():
    assert lookup("Ossford", "population_2025")["value"] == 30982
    assert lookup("Ossford", "population_2020")["value"] == 31560
    assert lookup("Tarnvale", "population_2025")["value"] == 71388
    assert lookup("Tarnvale", "population_2020")["value"] == 67214


def test_lookup_misspelled_name_gives_suggestion():
    r = lookup("Ossbrige", "area_km2")
    assert "error" in r and "Ossbridge" in r["error"]


def test_lookup_similar_names_are_different_districts():
    a, b = lookup("Ossbridge", "area_km2"), lookup("Ossford", "area_km2")
    assert a["value"] == 1284.6 and b["value"] == 846.2


def test_lookup_ignores_archived_profiles():
    assert lookup("Tarnvale", "population_2025")["value"] == 71388      # not 65030 (NR-13)
    assert lookup("Kelmarsh", "schools")["value"] == 11                 # not 10 (NR-14)
    assert lookup("Tarnvale", "water_use_m3")["value"] == 5207000       # not 4980 ML (2018)


def test_lookup_applies_correction_notice():
    r = lookup("Brightwater", "area_km2")
    assert r["value"] == 921.4 and "NR-16" in r["source"]


def test_lookup_water_unit_is_m3_for_every_district():
    assert lookup("Lindenmoor", "water_use_m3")["value"] == 2151400
    assert lookup("Kelmarsh", "water_use_m3")["value"] == 1739000


def test_lookup_tariff_and_bad_inputs():
    assert lookup("Region", "water_tariff_tenge_per_m3")["value"] == 142.35
    assert "error" in lookup("Millbrook", "water_tariff_tenge_per_m3")
    assert "error" in lookup("Millbrook", "height")
    assert "error" in lookup(None, "schools")
    assert "error" in lookup("Millbrook", 5)


def test_lookup_all_fields_exist_for_all_districts():
    from tools import _DATA, FIELDS
    assert len(_DATA) == 12
    for name in _DATA:
        for f in FIELDS:
            if f != "water_tariff_tenge_per_m3":
                assert "value" in lookup(name, f), (name, f)


# ------------------------------------------------------------- calculate
def test_calculate_basic():
    assert calculate("48317 * 1.0947")["result"] == pytest.approx(52892.6199)
    assert calculate("44675 / 921.4")["result"] == pytest.approx(48.486, abs=1e-3)
    assert calculate("-(2 + 3) * 4")["result"] == -20


def test_calculate_precedence_and_power():
    assert calculate("2 + 3 * 4")["result"] == 14
    assert calculate("2 ** 10")["result"] == 1024


def test_calculate_division_by_zero():
    assert calculate("1 / 0") == {"error": "division by zero"}


@pytest.mark.parametrize("bad", [
    "__import__('os').system('echo hi')",
    "(1).__class__",
    "9**9**9",
    "open('x')",
    "[1,2,3]",
    "'a' * 3",
    "x + 1",
    "1 if 1 else 2",
    "lambda: 1",
])
def test_calculate_refuses_dangerous_input(bad):
    r = calculate(bad)
    assert "error" in r and "result" not in r


def test_calculate_bad_arguments():
    assert "error" in calculate("")
    assert "error" in calculate(None)
    assert "error" in calculate("1 +")
    assert "error" in calculate("1" * 300)
    assert "error" in calculate("1e999")
    assert "error" in calculate("10 ** 99")


# --------------------------------------------------------------- dispatch
def test_run_tool_string_arguments():
    assert run_tool("lookup", '{"district": "Redfen", "field": "schools"}')["value"] == 10
    assert run_tool("calculate", '{"expression": "1+1"}')["result"] == 2
    assert "error" in run_tool("lookup", "not json")
    assert "error" in run_tool("nope", "{}")
    assert "error" in run_tool("calculate", "[1,2]")


def test_lookup_founded_year_q10():
    s, c = lookup("Stonecairn", "founded_year")["value"], lookup("Coldharbour", "founded_year")["value"]
    assert c - s == 8
