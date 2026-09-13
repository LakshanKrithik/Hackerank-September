"""
decision_engine.py
Implements plan generation and ranking across candidate payment methods:
- full_payment
- partial_payment
- installments
- wait
- not_recommended (fallback)

Ranks eligible safe plans according to the problem statement contract:
1. Complete by desired_completion_date
2. Require no spending changes
3. Minimize total amount paid
4. Start payment earlier
5. Use fewer payments
6. Lowest payment_option_id as final tie-breaker
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
try:
    from .output_validator import format_safe_amount, format_plan_amount
except ImportError:
    from output_validator import format_safe_amount, format_plan_amount


def parse_date(d_str: str) -> datetime:
    return datetime.strptime(str(d_str).strip()[:10], '%Y-%m-%d')


class DecisionEngine:
    def __init__(self, data_loader, financial_engine, spending_solver: Optional[Any] = None):
        self.loader = data_loader
        self.engine = financial_engine
        self.spending_solver = spending_solver

    def evaluate_request(
        self,
        request: Dict[str, Any],
        spending_changes: Optional[Dict[str, Any]] = None,
        spending_changes_str: str = 'none',
    ) -> Dict[str, Any]:
        """
        Evaluates a single financial request and returns the structured decision row.
        """
        rid = str(request['request_id']).strip()
        uid = str(request['user_id']).strip()
        req_date = str(request['request_date']).strip()
        req_amt = float(request['requested_amount'])
        desired_date = str(request['desired_completion_date']).strip()
        allows_partial = str(request.get('allows_partial_payment', '')).strip().lower() in {'true', '1'}

        profile = self.loader.profiles[uid]
        currency = profile['home_currency']
        user_methods = profile['payment_methods']
        max_inst_months = (
            float(profile['max_installment_months'])
            if pd.notna(profile.get('max_installment_months'))
            else None
        )

        # 1. Compute pre-change safe amount today and earliest date for full payment
        safe_amt = self.engine.compute_amount_safe_to_pay(uid, req_date, req_amt)
        earliest_date = self.engine.compute_earliest_date_for_full_payment(
            uid, req_date, req_amt, spending_changes=spending_changes
        )

        candidate_plans: List[Dict[str, Any]] = []

        # Candidate A: full_payment today
        if 'full_payment' in user_methods and safe_amt >= req_amt - 1e-4:
            p_str = f"{req_date}:{format_plan_amount(req_amt, currency)}"
            candidate_plans.append({
                'status': 'affordable_now',
                'method': 'full_payment',
                'plan_str': p_str,
                'completion_date': req_date,
                'start_date': req_date,
                'total_paid': req_amt,
                'num_payments': 1,
                'spending_changes': spending_changes_str,
                'option_id': '',
            })

        # Candidate B: partial_payment (exactly 2 payments: today and on earliest_date)
        if (
            allows_partial
            and 'partial_payment' in user_methods
            and 0 < safe_amt < req_amt
            and earliest_date
            and earliest_date <= desired_date
        ):
            p1 = safe_amt
            p2 = req_amt - safe_amt
            if self.engine.simulate_payment_plan(
                uid, [(req_date, p1), (earliest_date, p2)], spending_changes=spending_changes
            ):
                p_str = f"{req_date}:{format_plan_amount(p1, currency)}|{earliest_date}:{format_plan_amount(p2, currency)}"
                candidate_plans.append({
                    'status': 'affordable_with_plan',
                    'method': 'partial_payment',
                    'plan_str': p_str,
                    'completion_date': earliest_date,
                    'start_date': req_date,
                    'total_paid': req_amt,
                    'num_payments': 2,
                    'spending_changes': spending_changes_str,
                    'option_id': '',
                })

        # Candidate C: installments (must follow a supplied option in request_payment_options.csv)
        if 'installments' in user_methods:
            options = self.loader.options_by_request.get(rid, [])
            for opt in options:
                if opt.get('payment_method') != 'installments':
                    continue
                opt_id = opt['payment_option_id']
                init_date = str(opt['first_payment_date']).strip()
                cadence = int(float(opt['payment_frequency_days'])) if pd.notna(opt.get('payment_frequency_days')) else 30
                num_pmts = int(opt['number_of_payments'])
                inst_amt = float(opt['payment_amount'])
                tot_payable = float(opt['total_payable_amount'])

                # Check max_installment_months constraint
                init_dt = parse_date(init_date)
                last_dt = init_dt + timedelta(days=(num_pmts - 1) * cadence)
                duration_months = (last_dt - init_dt).days / 30.0
                if max_inst_months is not None and duration_months > max_inst_months + 0.1:
                    continue

                # Build schedule
                pmts = []
                for i in range(num_pmts):
                    p_dt = init_dt + timedelta(days=i * cadence)
                    pmts.append((p_dt.strftime('%Y-%m-%d'), inst_amt))

                comp_date = pmts[-1][0]

                # Check simulation safety
                if self.engine.simulate_payment_plan(uid, pmts, spending_changes=spending_changes):
                    p_str = '|'.join(f"{d}:{format_plan_amount(a, currency)}" for d, a in pmts)
                    candidate_plans.append({
                        'status': 'affordable_with_plan',
                        'method': 'installments',
                        'plan_str': p_str,
                        'completion_date': comp_date,
                        'start_date': init_date,
                        'total_paid': tot_payable,
                        'num_payments': num_pmts,
                        'spending_changes': spending_changes_str,
                        'option_id': opt_id,
                    })

        # Candidate D: wait (full payment on earliest_date_for_full_payment)
        if 'full_payment' in user_methods and earliest_date:
            p_str = f"{earliest_date}:{format_plan_amount(req_amt, currency)}"
            candidate_plans.append({
                'status': 'affordable_later',
                'method': 'wait',
                'plan_str': p_str,
                'completion_date': earliest_date,
                'start_date': earliest_date,
                'total_paid': req_amt,
                'num_payments': 1,
                'spending_changes': spending_changes_str,
                'option_id': '',
            })

        # If no immediate on-time plan without spending changes, check if spending changes can make an immediate plan viable
        immediate_on_time = [
            p for p in candidate_plans
            if p['method'] in {'full_payment', 'partial_payment', 'installments'}
            and p['completion_date'] <= desired_date
        ]

        if not immediate_on_time and self.spending_solver is not None and spending_changes is None:
            # 1. Try full_payment with spending changes
            if 'full_payment' in user_methods and req_date <= desired_date:
                res = self.spending_solver.find_minimal_spending_changes(
                    uid,
                    lambda sc: self.engine.simulate_payment_plan(uid, [(req_date, req_amt)], spending_changes=sc)
                )
                if res:
                    sc_dict, sc_token = res
                    p_str = f"{req_date}:{format_plan_amount(req_amt, currency)}"
                    candidate_plans.append({
                        'status': 'affordable_with_plan',
                        'method': 'full_payment',
                        'plan_str': p_str,
                        'completion_date': req_date,
                        'start_date': req_date,
                        'total_paid': req_amt,
                        'num_payments': 1,
                        'spending_changes': sc_token,
                        'option_id': '',
                    })

            # 2. Try installments with spending changes
            if 'installments' in user_methods:
                options = self.loader.options_by_request.get(rid, [])
                for opt in options:
                    if opt.get('payment_method') != 'installments':
                        continue
                    opt_id = opt['payment_option_id']
                    init_date = str(opt['first_payment_date']).strip()
                    cadence = int(float(opt['payment_frequency_days'])) if pd.notna(opt.get('payment_frequency_days')) else 30
                    num_pmts = int(opt['number_of_payments'])
                    inst_amt = float(opt['payment_amount'])
                    tot_payable = float(opt['total_payable_amount'])

                    init_dt = parse_date(init_date)
                    last_dt = init_dt + timedelta(days=(num_pmts - 1) * cadence)
                    duration_months = (last_dt - init_dt).days / 30.0
                    if max_inst_months is not None and duration_months > max_inst_months + 0.1:
                        continue

                    pmts = []
                    for i in range(num_pmts):
                        p_dt = init_dt + timedelta(days=i * cadence)
                        pmts.append((p_dt.strftime('%Y-%m-%d'), inst_amt))
                    comp_date = pmts[-1][0]
                    if comp_date > desired_date:
                        continue

                    res = self.spending_solver.find_minimal_spending_changes(
                        uid,
                        lambda sc: self.engine.simulate_payment_plan(uid, pmts, spending_changes=sc)
                    )
                    if res:
                        sc_dict, sc_token = res
                        p_str = '|'.join(f"{d}:{format_plan_amount(a, currency)}" for d, a in pmts)
                        candidate_plans.append({
                            'status': 'affordable_with_plan',
                            'method': 'installments',
                            'plan_str': p_str,
                            'completion_date': comp_date,
                            'start_date': init_date,
                            'total_paid': tot_payable,
                            'num_payments': num_pmts,
                            'spending_changes': sc_token,
                            'option_id': opt_id,
                        })

        # Plan selection and ranking
        # Immediate payment methods (full_payment, partial_payment, installments) that complete on time
        # take priority over waiting. Wait is considered when no immediate on-time plan is safe.
        if candidate_plans:
            immediate_on_time = [
                p for p in candidate_plans
                if p['method'] in {'full_payment', 'partial_payment', 'installments'}
                and p['completion_date'] <= desired_date
            ]

            def rank_key(p):
                no_changes = 0 if p['spending_changes'] == 'none' else 1
                return (
                    no_changes,
                    p['total_paid'],
                    p['start_date'],
                    p['num_payments'],
                    p['option_id'],
                )

            if immediate_on_time:
                best = min(immediate_on_time, key=rank_key)
            else:
                # If no immediate plan completes on time, check if wait is safe and completes on time
                wait_plan = next((p for p in candidate_plans if p['method'] == 'wait'), None)
                if wait_plan and wait_plan['completion_date'] <= desired_date:
                    best = wait_plan
                elif wait_plan:
                    # Wait plan safe within forecast, even if past desired completion date
                    best = wait_plan
                else:
                    best = {
                        'status': 'not_affordable',
                        'method': 'not_recommended',
                        'plan_str': 'none',
                        'spending_changes': 'none',
                    }
        else:
            best = {
                'status': 'not_affordable',
                'method': 'not_recommended',
                'plan_str': 'none',
                'spending_changes': 'none',
            }

        ed_report = earliest_date if best['method'] != 'not_recommended' else ''
        return {
            'request_id': rid,
            'amount_safe_to_pay': format_safe_amount(safe_amt),
            'affordability_status': best['status'],
            'recommended_payment_method': best['method'],
            'payment_plan': best['plan_str'],
            'earliest_date_for_full_payment': ed_report,
            'spending_changes_needed': best.get('spending_changes', 'none'),
            'decision_explanation': self._build_explanation(best, profile, req_amt, ed_report),
        }

    def _build_explanation(
        self,
        best_plan: Dict[str, Any],
        profile: Dict[str, Any],
        req_amt: float,
        earliest_date: str,
    ) -> str:
        curr = profile['home_currency']
        min_keep = profile['minimum_balance_to_keep']
        method = best_plan['method']

        if method == 'full_payment':
            return f"Pay in full today. The balance remains safely above the {curr} {min_keep} minimum requirement throughout the forecast."
        elif method == 'partial_payment':
            return f"Use partial payment: safe initial payment today followed by remaining balance on {earliest_date} to stay above the {curr} {min_keep} reserve."
        elif method == 'installments':
            return f"Use recommended installment plan ({best_plan.get('option_id', '')}). Payments are distributed safely to maintain the required {curr} {min_keep} reserve."
        elif method == 'wait':
            return f"Wait until {earliest_date} for full payment. Paying earlier would reduce available balance below the required {curr} {min_keep} minimum."
        else:
            return f"Not recommended within the forecast period. Cannot safely complete the request while maintaining the {curr} {min_keep} minimum reserve."
