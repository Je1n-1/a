from __future__ import annotations

import unittest
from datetime import datetime

from services import interactive_planning as engine


class InteractivePlanningEngineTest(unittest.TestCase):
    def objective(self, ident=1, **values):
        return {
            "objective_id": ident,
            "study_subject_id": ident,
            "name": f"Matéria {ident}",
            "status": "active",
            "start_date": "2026-09-01",
            "deadline_date": "2026-09-30",
            "budget_minutes": 1500,
            "budget_origin": "user",
            "budget_is_provisional": False,
            "realized_seconds": 0,
            "difficulty": 3,
            "mastery": 2,
            "allowed_weekdays": list(range(7)),
            "manual_daily_minutes": None,
            "preferred_duration_minutes": 50,
            "topics": [{"id": ident, "status": "not_started", "archived_at": None}],
            "topic_ids": [ident],
            "canonical_valid": True,
            **values,
        }

    def snapshot(self, objectives, *, start="2026-09-01", end="2026-09-30", minutes=60, **values):
        current = datetime.fromisoformat(start).date()
        final = datetime.fromisoformat(values.get("calculation_end", end)).date()
        availability = {}
        while current <= final:
            availability[current.isoformat()] = [[8 * 60, 8 * 60 + minutes]]
            current = current.fromordinal(current.toordinal() + 1)
        return {
            "horizon_start": start,
            "horizon_end": end,
            "calculation_end": values.pop("calculation_end", end),
            "selected_study_ids": [item["study_subject_id"] for item in objectives],
            "objectives": objectives,
            "availability": availability,
            "preserved_allocations": [],
            "actual_focus_seconds_by_day": {},
            "daily_limit_minutes": 0,
            "weekly_limit_minutes": 0,
            "pause_minutes": 0,
            **values,
        }

    def plan(self, snapshot, intents=None, parameters=None):
        return engine.plan(snapshot, intents or [{"type": "distribute_remaining"}], parameters or {}, datetime(2026, 9, 1, 6, 0))

    def test_largest_remainder_conserves_accepted_weight_example(self):
        self.assertEqual(engine.largest_remainder(180, {1: 20, 2: 4, 3: 12}), {1: 100, 2: 20, 3: 60})

    def test_twenty_five_hours_over_thirty_eligible_days_is_fifty_daily(self):
        result = self.plan(self.snapshot([self.objective()]))
        by_day = {item["scheduled_date"]: item["planned_duration_minutes"] for item in result["sessions"]}
        self.assertEqual(len(by_day), 30)
        self.assertEqual(set(by_day.values()), {50})
        self.assertEqual(sum(by_day.values()), 1500)

    def test_forty_two_hours_over_forty_two_days_is_sixty_daily(self):
        objective = self.objective(budget_minutes=42 * 60, deadline_date="2026-10-12")
        snapshot = self.snapshot([objective], end="2026-10-12", calculation_end="2026-10-12")
        result = self.plan(snapshot)
        self.assertEqual(len(result["sessions"]), 42)
        self.assertEqual({item["planned_duration_minutes"] for item in result["sessions"]}, {60})

    def test_manual_fifty_is_fifty_independent_of_preferred_duration(self):
        objective = self.objective(budget_minutes=500, preferred_duration_minutes=15)
        snapshot = self.snapshot([objective], end="2026-09-01", minutes=240)
        result = self.plan(snapshot, [{"type": "subject_day", "study_subject_id": 1, "date": "2026-09-01", "minutes": 50}])
        self.assertEqual([item["planned_duration_minutes"] for item in result["sessions"]], [50])
        self.assertEqual(result["totals"]["proposed_focus_minutes"], 50)

    def test_manual_dates_remain_exact_when_remaining_is_distributed(self):
        objective = self.objective(budget_minutes=300, deadline_date="2026-09-03")
        snapshot = self.snapshot([objective], end="2026-09-03", minutes=180)
        result = self.plan(snapshot, [
            {"type": "subject_day", "study_subject_id": 1, "date": "2026-09-01", "minutes": 120},
            {"type": "subject_day", "study_subject_id": 1, "date": "2026-09-02", "minutes": 120},
            {"type": "distribute_remaining"},
        ])
        by_day = {item["scheduled_date"]: item["planned_duration_minutes"] for item in result["sessions"]}
        self.assertEqual(by_day, {"2026-09-01": 120, "2026-09-02": 120, "2026-09-03": 60})

    def test_daily_total_uses_weights_and_exact_integer_sum(self):
        objectives = [
            self.objective(1, budget_minutes=500, difficulty=4, mastery=1),
            self.objective(2, budget_minutes=500, difficulty=2, mastery=4),
            self.objective(3, budget_minutes=500, difficulty=3, mastery=2),
        ]
        result = self.plan(
            self.snapshot(objectives, end="2026-09-01", minutes=180),
            [{"type": "daily_total", "dates": ["2026-09-01"], "minutes": 180}],
        )
        amounts = {item["study_subject_id"]: item["planned_duration_minutes"] for item in result["sessions"]}
        self.assertEqual(amounts, {1: 100, 2: 20, 3: 60})

    def test_no_preference_keeps_one_hundred_twenty_continuous(self):
        objective = self.objective(budget_minutes=120)
        result = self.plan(self.snapshot([objective], end="2026-09-01", minutes=120), parameters={"use_preferred_duration": False})
        self.assertEqual([item["planned_duration_minutes"] for item in result["sessions"]], [120])

    def test_explicit_preference_splits_without_changing_total(self):
        objective = self.objective(budget_minutes=180, preferred_duration_minutes=50)
        result = self.plan(self.snapshot([objective], end="2026-09-01", minutes=180), parameters={"use_preferred_duration": True})
        self.assertEqual([item["planned_duration_minutes"] for item in result["sessions"]], [50, 50, 50, 30])
        self.assertEqual(result["totals"]["proposed_focus_minutes"], 180)

    def test_overlapping_windows_are_not_counted_twice(self):
        snapshot = self.snapshot([self.objective(budget_minutes=180)], end="2026-09-01", minutes=1)
        snapshot["availability"]["2026-09-01"] = [[480, 600], [540, 660]]
        result = self.plan(snapshot)
        self.assertEqual(result["totals"]["proposed_focus_minutes"], 180)
        self.assertEqual(len(result["sessions"]), 1)

    def test_missing_deadline_or_topic_blocks_only_automatic_distribution(self):
        objective = self.objective(deadline_date=None, topic_ids=[], topics=[])
        snapshot = self.snapshot([objective], end="2026-09-01", minutes=60)
        automatic = self.plan(snapshot)
        self.assertFalse(automatic["sessions"])
        self.assertEqual({item["code"] for item in automatic["blockers"]}, {"deadline_required", "topic_required"})
        manual = self.plan(snapshot, [{"type": "subject_day", "study_subject_id": 1, "date": "2026-09-01", "minutes": 30}])
        self.assertEqual(manual["totals"]["manual_minutes"], 30)

    def test_real_focus_reduces_budget_but_future_allocation_is_only_reserved(self):
        objective = self.objective(budget_minutes=120, realized_seconds=30 * 60)
        snapshot = self.snapshot([objective], end="2026-09-02", minutes=60)
        snapshot["preserved_allocations"] = [{
            "id": 10, "study_subject_id": 1, "scheduled_date": "2026-09-01",
            "start_time": "08:00", "planned_duration_minutes": 30, "source": "manual", "is_locked": 1,
        }]
        result = self.plan(snapshot)
        ledger = result["objectives"][0]
        self.assertEqual(ledger["remaining_minutes"], 90)
        self.assertEqual(ledger["preserved_minutes"], 30)
        self.assertEqual(result["totals"]["suggested_minutes"], 60)

    def test_manual_over_budget_requires_a_decision_without_negative_balance(self):
        snapshot = self.snapshot([self.objective(budget_minutes=30)], end="2026-09-01", minutes=60)
        result = self.plan(snapshot, [{"type": "subject_day", "study_subject_id": 1, "date": "2026-09-01", "minutes": 50}])
        self.assertIn("manual_exceeds_budget", {item["code"] for item in result["conflicts"]})
        self.assertEqual(result["objectives"][0]["balance_to_plan_minutes"], 0)
        self.assertEqual(result["sessions"][0]["planned_duration_minutes"], 50)

    def test_result_is_deterministic_for_equal_input(self):
        snapshot = self.snapshot([self.objective()])
        first = self.plan(snapshot)
        second = self.plan(snapshot)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
