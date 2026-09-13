"""
spending_solver.py
Solves for the minimal set of counterfactual spending reductions (stop / reduce_to)
to make an otherwise unaffordable purchase safe within the 90-day forecast.

Rules:
1. Maximum 3 spending changes separated by '|'.
2. Format: stop:<event_id> or reduce_to:<event_id>:<new_amount>.
3. Only non-protected recurring expenses marked as flexible may be changed.
4. References the last settled event_id of the recurring series.
5. Mutually exclusive: stopping and reducing the same event is forbidden.
6. Minimum allowed amount is used for reduce_to.
"""

from typing import Dict, List, Any, Optional, Tuple
import itertools
try:
    from .output_validator import format_spending_change_amount
except ImportError:
    from output_validator import format_spending_change_amount


class SpendingSolver:
    def __init__(self, data_loader, recurring_detector, financial_engine):
        self.loader = data_loader
        self.detector = recurring_detector
        self.engine = financial_engine

    def get_candidate_interventions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Gathers all permissible interventions for a user based on profile permissions
        and event flexibility.
        """
        profile = self.loader.profiles[user_id]
        currency = profile['home_currency']
        protected = profile['protected_categories']
        to_stop = profile['categories_to_stop']
        to_reduce = profile['categories_to_reduce']

        user_series = self.detector.user_series.get(user_id, [])
        interventions: List[Dict[str, Any]] = []

        for s in user_series:
            # Must be a debit and not protected
            if s.direction != 'debit' or s.category in protected:
                continue

            flex = s.flexibility
            eid = s.last_event_id
            curr_amt = s.get_projected_amount()

            # 1. Check stoppable option
            if flex in {'stoppable', 'reducible_or_stoppable'} and s.category in to_stop:
                interventions.append({
                    'event_id': eid,
                    'action': 'stop',
                    'saving': curr_amt,
                    'dict_entry': {'action': 'stop'},
                    'token': f"stop:{eid}",
                })

            # 2. Check reducible option
            if (
                flex in {'reducible', 'reducible_or_stoppable'}
                and s.category in to_reduce
                and s.min_allowed_amount is not None
                and s.min_allowed_amount < curr_amt
            ):
                saving = curr_amt - s.min_allowed_amount
                formatted_amt = format_spending_change_amount(s.min_allowed_amount, currency)
                interventions.append({
                    'event_id': eid,
                    'action': 'reduce_to',
                    'amount': s.min_allowed_amount,
                    'saving': saving,
                    'dict_entry': {'action': 'reduce_to', 'amount': s.min_allowed_amount},
                    'token': f"reduce_to:{eid}:{formatted_amt}",
                })

        # Sort interventions by highest monthly savings first
        interventions.sort(key=lambda x: x['saving'], reverse=True)
        return interventions

    def find_minimal_spending_changes(
        self,
        user_id: str,
        test_fn,
    ) -> Optional[Tuple[Dict[str, Any], str]]:
        """
        Searches combinations of up to 3 interventions that satisfy test_fn(spending_changes_dict).
        Returns (spending_changes_dict, token_string) or None if no combination works.
        """
        cands = self.get_candidate_interventions(user_id)
        if not cands:
            return None

        # Search combinations of size 1, 2, 3
        for k in range(1, min(4, len(cands) + 1)):
            for comb in itertools.combinations(cands, k):
                # Ensure stopping and reducing the same event is not attempted
                event_ids = [item['event_id'] for item in comb]
                if len(event_ids) != len(set(event_ids)):
                    continue

                spending_dict = {item['event_id']: item['dict_entry'] for item in comb}
                if test_fn(spending_dict):
                    token_str = '|'.join(item['token'] for item in comb)
                    return spending_dict, token_str

        return None
