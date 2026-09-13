"""
tests/test_recurring_detector.py
Permanent unit and regression test suite for recurring_detector.py.

Asserts:
1. Calendar day-of-month anchoring (15th stays 15th across varying month lengths).
2. Four named regression scenarios:
   a. Arrears scenario (established salary + irregular one-off arrears ignored).
   b. Bonus scenario (established salary + mid-cycle bonus ignored).
   c. Legitimate increase scenario (established salary + 2+ consistent occurrences on cadence -> baseline updated).
   d. Irregular adjustment after normal (established salary + 1 unconfirmed adjustment -> baseline retained).
3. Cold-start fallback (<2 historical salary occurrences).
4. Non-monthly variable interval preservation (e.g. 10-day groceries, 21-day dining).
"""

import unittest
from datetime import datetime
import sys
import os

# Ensure code/ is on path
sys.path.insert(0, os.path.abspath('code'))
from recurring_detector import (
    RecurringDetector,
    RecurringSeries,
    add_months,
    is_amount_consistent,
    is_cadence_consistent,
)


class MockDataLoader:
    def __init__(self, events_by_user):
        self.events_by_user = events_by_user
        self.profiles = {}


class TestRecurringDetector(unittest.TestCase):

    def test_calendar_day_anchoring_preservation(self):
        """Proves that a 15th anchor stays on the 15th across varying month lengths (Feb, Apr, etc.)."""
        # Starting Jan 15, 2024 (leap year)
        dt = datetime(2024, 1, 15)
        # 1 month: Feb 15
        dt_feb = add_months(dt, 1, 15)
        self.assertEqual(dt_feb.strftime('%Y-%m-%d'), '2024-02-15')

        # 2 months: Mar 15
        dt_mar = add_months(dt, 2, 15)
        self.assertEqual(dt_mar.strftime('%Y-%m-%d'), '2024-03-15')

        # 3 months: Apr 15 (30-day month)
        dt_apr = add_months(dt, 3, 15)
        self.assertEqual(dt_apr.strftime('%Y-%m-%d'), '2024-04-15')

        # 4 months: May 15
        dt_may = add_months(dt, 4, 15)
        self.assertEqual(dt_may.strftime('%Y-%m-%d'), '2024-05-15')

        # 5 months: Jun 15
        dt_jun = add_months(dt, 5, 15)
        self.assertEqual(dt_jun.strftime('%Y-%m-%d'), '2024-06-15')

        # Month-end clamping check: 31st in February clamps to 29 (in 2024 leap year) and 28 (in 2025)
        dt_31 = datetime(2024, 1, 31)
        dt_feb31 = add_months(dt_31, 1, 31)
        self.assertEqual(dt_feb31.strftime('%Y-%m-%d'), '2024-02-29')

        dt_2025 = datetime(2025, 1, 31)
        dt_feb2025 = add_months(dt_2025, 1, 31)
        self.assertEqual(dt_feb2025.strftime('%Y-%m-%d'), '2025-02-28')

    def test_scenario_a_arrears_ignored(self):
        """Arrears scenario: established salary + 1 irregular arrears payment must NOT overwrite baseline."""
        events = [
            {'event_id': 'e1', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 100000.0, 'currency': 'IDR', 'settlement_date': '2024-01-15', 'status': 'settled'},
            {'event_id': 'e2', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 100000.0, 'currency': 'IDR', 'settlement_date': '2024-02-15', 'status': 'settled'},
            {'event_id': 'e3', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 100000.0, 'currency': 'IDR', 'settlement_date': '2024-03-15', 'status': 'settled'},
            {'event_id': 'e4', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 100000.0, 'currency': 'IDR', 'settlement_date': '2024-04-15', 'status': 'settled'},
            {'event_id': 'e5', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 45000.0, 'currency': 'IDR', 'settlement_date': '2024-04-20', 'status': 'settled', 'description': 'Promotion arrears payment'},
        ]
        mock_loader = MockDataLoader({'u_test': events})
        detector = RecurringDetector(mock_loader)
        sal_series = [s for s in detector.user_series['u_test'] if s.category == 'salary']

        self.assertEqual(len(sal_series), 1)
        s = sal_series[0]
        self.assertEqual(s.last_amount, 100000.0)
        self.assertEqual(s.anchor_day, 15)

    def test_scenario_b_bonus_ignored(self):
        """Bonus scenario: established salary + 1 mid-cycle bonus must NOT overwrite baseline."""
        events = [
            {'event_id': 'e1', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 94000.0, 'currency': 'INR', 'settlement_date': '2024-11-15', 'status': 'settled'},
            {'event_id': 'e2', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 94000.0, 'currency': 'INR', 'settlement_date': '2024-12-15', 'status': 'settled'},
            {'event_id': 'e3', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 94000.0, 'currency': 'INR', 'settlement_date': '2025-01-15', 'status': 'settled'},
            {'event_id': 'e4', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 48612.98, 'currency': 'INR', 'settlement_date': '2025-01-22', 'status': 'settled', 'description': 'Quarterly performance bonus'},
        ]
        mock_loader = MockDataLoader({'u_test': events})
        detector = RecurringDetector(mock_loader)
        sal_series = [s for s in detector.user_series['u_test'] if s.category == 'salary']

        self.assertEqual(len(sal_series), 1)
        s = sal_series[0]
        self.assertEqual(s.last_amount, 94000.0)
        self.assertEqual(s.anchor_day, 15)

    def test_scenario_c_legitimate_salary_increase(self):
        """Legitimate increase scenario: 2+ consistent occurrences on cadence DO update baseline & anchor."""
        events = [
            {'event_id': 'e1', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 2123.0, 'currency': 'EUR', 'settlement_date': '2024-04-15', 'status': 'settled'},
            {'event_id': 'e2', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 2123.0, 'currency': 'EUR', 'settlement_date': '2024-05-15', 'status': 'settled'},
            {'event_id': 'e3', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 2123.0, 'currency': 'EUR', 'settlement_date': '2024-06-15', 'status': 'settled'},
            # New salary starts with shifted pay date (25th)
            {'event_id': 'e4', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 2650.0, 'currency': 'EUR', 'settlement_date': '2024-07-25', 'status': 'settled'},
            {'event_id': 'e5', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 2650.0, 'currency': 'EUR', 'settlement_date': '2024-08-25', 'status': 'settled'},
        ]
        mock_loader = MockDataLoader({'u_test': events})
        detector = RecurringDetector(mock_loader)
        sal_series = [s for s in detector.user_series['u_test'] if s.category == 'salary']

        self.assertEqual(len(sal_series), 1)
        s = sal_series[0]
        self.assertEqual(s.last_amount, 2650.0)
        self.assertEqual(s.anchor_day, 25)

    def test_scenario_d_irregular_adjustment_after_normal(self):
        """Irregular adjustment after normal: 1 unconfirmed higher/lower payment is rejected as baseline."""
        events = [
            {'event_id': 'e1', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 260000.0, 'currency': 'INR', 'settlement_date': '2024-07-15', 'status': 'settled'},
            {'event_id': 'e2', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 260000.0, 'currency': 'INR', 'settlement_date': '2024-08-15', 'status': 'settled'},
            {'event_id': 'e3', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 260000.0, 'currency': 'INR', 'settlement_date': '2024-09-15', 'status': 'settled'},
            {'event_id': 'e4', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 260000.0, 'currency': 'INR', 'settlement_date': '2024-10-15', 'status': 'settled'},
            # Irregular single adjustment:
            {'event_id': 'e5', 'user_id': 'u_test', 'category': 'salary', 'direction': 'credit', 'amount': 117000.0, 'currency': 'INR', 'settlement_date': '2024-10-20', 'status': 'settled'},
        ]
        mock_loader = MockDataLoader({'u_test': events})
        detector = RecurringDetector(mock_loader)
        sal_series = [s for s in detector.user_series['u_test'] if s.category == 'salary']

        self.assertEqual(len(sal_series), 1)
        s = sal_series[0]
        self.assertEqual(s.last_amount, 260000.0)
        self.assertEqual(s.anchor_day, 15)

    def test_cold_start_fallback(self):
        """Cold-start case: User with only 1 historical salary occurrence uses it without requiring 2.
        Note: is_monthly=True is an intentional domain default for salary when a single occurrence provides no cadence gap.
        """
        events = [
            {'event_id': 'e1', 'user_id': 'u_cold', 'category': 'salary', 'direction': 'credit', 'amount': 5000.0, 'currency': 'USD', 'settlement_date': '2024-05-10', 'status': 'settled'},
        ]
        mock_loader = MockDataLoader({'u_cold': events})
        detector = RecurringDetector(mock_loader)
        sal_series = [s for s in detector.user_series['u_cold'] if s.category == 'salary']

        self.assertEqual(len(sal_series), 1)
        s = sal_series[0]
        self.assertEqual(s.last_amount, 5000.0)
        self.assertEqual(s.anchor_day, 10)
        self.assertTrue(s.is_monthly)

    def test_non_monthly_cadence_preservation(self):
        """Proves non-monthly recurring series (e.g. 10-day groceries, 21-day dining) preserve exact integer intervals."""
        events = [
            # Groceries every 10 days
            {'event_id': 'g1', 'user_id': 'u_var', 'category': 'groceries', 'direction': 'debit', 'amount': 100.0, 'currency': 'USD', 'settlement_date': '2024-01-01', 'status': 'settled'},
            {'event_id': 'g2', 'user_id': 'u_var', 'category': 'groceries', 'direction': 'debit', 'amount': 100.0, 'currency': 'USD', 'settlement_date': '2024-01-11', 'status': 'settled'},
            {'event_id': 'g3', 'user_id': 'u_var', 'category': 'groceries', 'direction': 'debit', 'amount': 100.0, 'currency': 'USD', 'settlement_date': '2024-01-21', 'status': 'settled'},
            {'event_id': 'g4', 'user_id': 'u_var', 'category': 'groceries', 'direction': 'debit', 'amount': 100.0, 'currency': 'USD', 'settlement_date': '2024-01-31', 'status': 'settled'},
        ]
        mock_loader = MockDataLoader({'u_var': events})
        detector = RecurringDetector(mock_loader)
        g_series = [s for s in detector.user_series['u_var'] if s.category == 'groceries'][0]

        self.assertFalse(g_series.is_monthly)
        self.assertEqual(g_series.interval_days, 10)

        # Verify projections step by 10 days
        projected = detector.project_recurring_events('u_var', '2024-02-01', '2024-03-01')
        proj_dates = [p['settlement_date'] for p in projected]
        self.assertEqual(proj_dates, ['2024-02-10', '2024-02-20', '2024-03-01'])


if __name__ == '__main__':
    unittest.main()
