"""Checks of the scoring rules, using two answers from the first real evaluation run."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_assistant import facts_in_answer, grounding_problems, rows_match

SEVEN = [{"machine_id": m, "failure_spike_count": n} for m, n in [
    ("TURBINE_01", 7), ("PUMP_02", 6), ("TURBINE_02", 5), ("COMPRESSOR_01", 4),
    ("HEAT_EXCHANGER_02", 4), ("PUMP_03", 4), ("GENERATOR_02", 3)]]
SEVENTEEN = SEVEN + [{"machine_id": f"M_{i:02d}", "failure_spike_count": 1} for i in range(10)]


def test_short_list_answer_must_name_every_machine():
    cut_off = "TURBINE_01 requires maintenance with a failure spike count of 7, followed by PUMP_02 with 6 and TURBINE_02 with 5."
    assert not facts_in_answer(SEVEN, cut_off)
    full = ", ".join(f"{r['machine_id']} ({r['failure_spike_count']})" for r in SEVEN)
    assert facts_in_answer(SEVEN, full)


def test_long_list_answer_needs_count_and_top_item():
    answer = "All 17 machines had failure spikes, with counts from 1 to 7. The highest were TURBINE_01 (7) and PUMP_02 (6)."
    assert facts_in_answer(SEVENTEEN, answer)
    assert not facts_in_answer(SEVENTEEN, "Several machines had failure spikes, led by TURBINE_01.")
    assert not facts_in_answer(SEVENTEEN, "All 17 machines had failure spikes.")


def test_invented_machine_and_number_are_caught():
    rows = [{"machine_id": "PUMP_01", "cost": 2.5}]
    ids, nums = grounding_problems("PUMP_09 costs 99.9 EUR.", rows, "which machine costs most?")
    assert ids == ["PUMP_09"] and nums == ["99.9"]
    assert grounding_problems("PUMP_01 costs 2.5 EUR.", rows, "q") == ([], [])


def test_extra_column_is_fine_extra_row_is_not():
    ref = [{"machine_id": "A_01"}]
    assert rows_match(ref, [{"machine_id": "A_01", "machine_type": "A"}])
    assert not rows_match(ref, [{"machine_id": "A_01"}, {"machine_id": "B_01"}])
