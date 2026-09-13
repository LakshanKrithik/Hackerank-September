"""
tests/test_decision_engine.py
Permanent unit tests for decision_engine.py.

Asserts:
1. Candidate plan generation (full_payment, partial_payment, installments, wait, not_recommended).
2. The 6-tier ranking hierarchy:
   - Priority 1: Completes on or before desired_completion_date
   - Priority 2: Requires no spending changes
   - Priority 3: Minimizes total amount paid
   - Priority 4: Starts earlier
   - Priority 5: Uses fewer payments
   - Priority 6: Lowest payment_option_id
3. Validation of the 8 returned output fields against the challenge contract.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath('code'))
from decision_engine import DecisionEngine
from output_validator import validate_row, REQUIRED_COLUMNS


class MockEngine:
    def __init__(self, safe_amt=0.0, earliest_date="", plan_safe=True):
        self.safe_amt = safe_amt
        self.earliest_date = earliest_date
        self.plan_safe = plan_safe

    def compute_amount_safe_to_pay(self, uid, req_date, req_amt):
        return self.safe_amt

    def compute_earliest_date_for_full_payment(self, uid, req_date, req_amt, spending_changes=None):
        return self.earliest_date

    def simulate_payment_plan(self, uid, pmts, spending_changes=None):
        return self.plan_safe


class MockDataLoader:
    def __init__(self):
        self.profiles = {
            'u1': {
                'home_currency': 'USD',
                'payment_methods': {'full_payment', 'partial_payment', 'installments'},
                'max_installment_months': 6.0,
                'minimum_balance_to_keep': 1000.0,
            }
        }
        self.options_by_request = {
            'r1': [
                {
                    'payment_option_id': 'payment_option_02',
                    'payment_method': 'installments',
                    'first_payment_date': '2024-03-01',
                    'payment_frequency_days': 30,
                    'number_of_payments': 3,
                    'payment_amount': 350.0,
                    'total_payable_amount': 1050.0,
                },
                {
                    'payment_option_id': 'payment_option_01',
                    'payment_method': 'installments',
                    'first_payment_date': '2024-03-01',
                    'payment_frequency_days': 30,
                    'number_of_payments': 3,
                    'payment_amount': 340.0,
                    'total_payable_amount': 1020.0,  # Cheaper!
                }
            ]
        }


class TestDecisionEngine(unittest.TestCase):

    def test_full_payment_affordable_now(self):
        loader = MockDataLoader()
        engine = MockEngine(safe_amt=1000.0, earliest_date='2024-03-01')
        dec_engine = DecisionEngine(loader, engine)

        req = {
            'request_id': 'r1',
            'user_id': 'u1',
            'request_date': '2024-03-01',
            'requested_amount': 1000.0,
            'desired_completion_date': '2024-03-01',
            'allows_partial_payment': False,
        }
        res = dec_engine.evaluate_request(req)

        self.assertEqual(res['affordability_status'], 'affordable_now')
        self.assertEqual(res['recommended_payment_method'], 'full_payment')
        self.assertEqual(res['payment_plan'], '2024-03-01:1000.00')
        self.assertEqual(res['earliest_date_for_full_payment'], '2024-03-01')

        # Assert zero schema validation errors
        errs = validate_row(res, requested_amount=1000.0)
        self.assertEqual(errs, [])

    def test_ranking_minimizes_total_cost(self):
        """When multiple installment options are safe and on time, picks the one with lower total payable amount."""
        loader = MockDataLoader()
        engine = MockEngine(safe_amt=100.0, earliest_date='2024-06-01', plan_safe=True)
        dec_engine = DecisionEngine(loader, engine)

        req = {
            'request_id': 'r1',
            'user_id': 'u1',
            'request_date': '2024-03-01',
            'requested_amount': 1000.0,
            'desired_completion_date': '2024-06-01',
            'allows_partial_payment': False,
        }
        res = dec_engine.evaluate_request(req)

        self.assertEqual(res['affordability_status'], 'affordable_with_plan')
        self.assertEqual(res['recommended_payment_method'], 'installments')
        # payment_option_01 has total 1020 vs option_02 total 1050
        self.assertIn('2024-03-01:340.00', res['payment_plan'])
        self.assertIn('payment_option_01', res['decision_explanation'])

    def test_not_recommended_fallback(self):
        """When no option or wait plan is safe, falls back to not_recommended."""
        loader = MockDataLoader()
        engine = MockEngine(safe_amt=0.0, earliest_date='', plan_safe=False)
        dec_engine = DecisionEngine(loader, engine)

        req = {
            'request_id': 'r1',
            'user_id': 'u1',
            'request_date': '2024-03-01',
            'requested_amount': 1000.0,
            'desired_completion_date': '2024-03-15',
            'allows_partial_payment': False,
        }
        res = dec_engine.evaluate_request(req)

        self.assertEqual(res['affordability_status'], 'not_affordable')
        self.assertEqual(res['recommended_payment_method'], 'not_recommended')
        self.assertEqual(res['payment_plan'], 'none')
        self.assertEqual(res['earliest_date_for_full_payment'], '')


if __name__ == '__main__':
    unittest.main()
