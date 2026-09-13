"""
financial_engine.py
Reconstructs daily cash positions and computes safe spending capacity.
Implements:
1. Linear closed-form headroom calculation (no binary search).
2. Sliding-window earliest full payment date lookup.
3. Decoupled pre-change vs post-change cash flow evaluation.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Set


def parse_date(d_str: str) -> datetime:
    return datetime.strptime(str(d_str).strip()[:10], '%Y-%m-%d')


def format_date(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d')


class FinancialEngine:
    def __init__(
        self,
        data_loader,
        recurring_detector,
        resolved_image_amounts: Optional[Dict[str, float]] = None,
        message_resolver: Optional[Any] = None,
    ):
        self.loader = data_loader
        self.detector = recurring_detector
        self.image_amounts = resolved_image_amounts or {}
        self.message_resolver = message_resolver

    def get_timeline(
        self,
        user_id: str,
        start_date: str,
        horizon_days: int = 180,
        spending_changes: Optional[Dict[str, Any]] = None,
        stop_salary: bool = False,
        updated_salary_amt: Optional[float] = None,
    ) -> Tuple[List[str], List[float]]:
        """
        Builds the daily balance trajectory without any purchase payment,
        from start_date to start_date + horizon_days.
        Returns (date_strings, daily_balances).
        """
        if self.message_resolver is not None:
            ov = self.message_resolver.get_override(user_id)
            if not stop_salary and ov.get('stop_salary'):
                stop_salary = True
            if updated_salary_amt is None and ov.get('updated_salary_amt') is not None:
                updated_salary_amt = ov['updated_salary_amt']
            msg_sched_salary_date = ov.get('scheduled_salary_date')
            rent_multiplier = float(ov.get('rent_multiplier', 1.0))
            confirmed_invoices = ov.get('confirmed_invoices', [])
        else:
            msg_sched_salary_date = None
            rent_multiplier = 1.0
            confirmed_invoices = []

        profile = self.loader.profiles[user_id]
        home_curr = profile['home_currency']
        starting_balance = float(profile['current_available_balance'])

        start_dt = parse_date(start_date)
        end_dt = start_dt + timedelta(days=horizon_days)
        end_date_str = format_date(end_dt)

        # Net daily cash flows on each date: date_str -> net_amount
        daily_cashflows: Dict[str, float] = {}

        # 1. Include explicit future events from dataset
        user_events = self.loader.events_by_user.get(user_id, [])
        for ev in user_events:
            s_date = str(ev.get('settlement_date', '')).strip()
            if not s_date or s_date < start_date or s_date > end_date_str:
                continue

            status = str(ev.get('status', '')).strip()
            direction = str(ev.get('direction', '')).strip()
            category = str(ev.get('category', '')).strip()
            ev_id = str(ev.get('event_id', '')).strip()

            # Resolution rules:
            # - Exclude failed, cancelled, unrealized
            if status in {'failed', 'cancelled', 'unrealized'}:
                continue

            # - Debits: reserve pending and scheduled
            # - Credits: count only settled or confirmed scheduled salary
            if direction == 'credit':
                if status == 'pending':
                    # Unconfirmed pending credit (bonus, refund, prize, etc.) - DO NOT COUNT
                    continue
                if status == 'scheduled' and category != 'salary':
                    continue

            # Determine amount
            raw_amt = ev.get('amount')
            if raw_amt is None or str(raw_amt).strip() in {'', 'nan'}:
                # Check resolved image amounts
                if ev_id in self.image_amounts:
                    amt = float(self.image_amounts[ev_id])
                else:
                    amt = 0.0
            else:
                amt = float(raw_amt)

            if amt <= 0:
                continue

            # Check if salary amount was amended by message
            if category == 'salary' and updated_salary_amt is not None:
                amt = updated_salary_amt

            # FX conversion
            ev_curr = str(ev.get('currency', home_curr)).strip()
            if ev_curr != home_curr:
                fx_rate = self.loader.get_fx_rate(s_date, ev_curr, home_curr)
                amt *= fx_rate

            # Net impact
            if direction == 'credit':
                daily_cashflows[s_date] = daily_cashflows.get(s_date, 0.0) + amt
            else:
                daily_cashflows[s_date] = daily_cashflows.get(s_date, 0.0) - amt

        # 2. Include projected recurring events
        # Find scheduled salary anchor if available
        scheduled_salary_date = msg_sched_salary_date
        if not scheduled_salary_date:
            for ev in user_events:
                if ev.get('category') == 'salary' and ev.get('status') == 'scheduled':
                    s_date = str(ev.get('settlement_date', '')).strip()
                    if s_date >= start_date:
                        scheduled_salary_date = s_date
                        break

        projected_events = self.detector.project_recurring_events(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date_str,
            spending_changes=spending_changes,
            stop_salary=stop_salary,
            updated_salary_amt=updated_salary_amt,
            scheduled_salary_date=scheduled_salary_date,
            rent_multiplier=rent_multiplier,
        )

        for pev in projected_events:
            p_date = pev['settlement_date']
            amt = pev['amount']
            p_curr = pev['currency']
            if p_curr != home_curr:
                fx_rate = self.loader.get_fx_rate(p_date, p_curr, home_curr)
                amt *= fx_rate

            if pev['direction'] == 'credit':
                daily_cashflows[p_date] = daily_cashflows.get(p_date, 0.0) + amt
            else:
                daily_cashflows[p_date] = daily_cashflows.get(p_date, 0.0) - amt

        # 3. Include confirmed client invoices from messages
        for inv in confirmed_invoices:
            inv_date = str(inv['date']).strip()
            if start_date <= inv_date <= end_date_str:
                inv_amt = float(inv['amount'])
                inv_curr = str(inv['currency']).strip()
                if inv_curr != home_curr:
                    fx_rate = self.loader.get_fx_rate(inv_date, inv_curr, home_curr)
                    inv_amt *= fx_rate
                daily_cashflows[inv_date] = daily_cashflows.get(inv_date, 0.0) + inv_amt

        # 4. Simulate continuous daily balance trajectory
        dates = []
        balances = []
        curr_bal = starting_balance

        curr_dt = start_dt
        while curr_dt <= end_dt:
            d_str = format_date(curr_dt)
            # Apply today's net cashflow
            cf = daily_cashflows.get(d_str, 0.0)
            curr_bal += cf

            dates.append(d_str)
            balances.append(curr_bal)
            curr_dt += timedelta(days=1)

        return dates, balances

    def compute_amount_safe_to_pay(
        self,
        user_id: str,
        request_date: str,
        requested_amount: float,
    ) -> float:
        """
        Computes amount_safe_to_pay today strictly BEFORE any optional spending changes.
        Linear closed form:
        headroom = min(balance_t over [request_date, request_date + 90]) - minimum_balance_to_keep
        amount_safe_to_pay = clamp(headroom, 0, requested_amount)
        """
        profile = self.loader.profiles[user_id]
        min_balance = float(profile['minimum_balance_to_keep'])

        dates, balances = self.get_timeline(
            user_id=user_id,
            start_date=request_date,
            horizon_days=90,
            spending_changes=None,  # Strictly pre-change
        )

        # Min balance across the 90-day window
        min_bal_in_window = min(balances[:91])
        headroom = min_bal_in_window - min_balance

        safe_amount = max(0.0, min(float(requested_amount), float(headroom)))
        return safe_amount

    def compute_earliest_date_for_full_payment(
        self,
        user_id: str,
        request_date: str,
        requested_amount: float,
        spending_changes: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Finds the first candidate date D in [request_date, request_date + 90]
        such that paying requested_amount on D maintains balance >= min_balance
        throughout all 90 days after D (i.e. [D, D + 90]).
        """
        profile = self.loader.profiles[user_id]
        min_balance = float(profile['minimum_balance_to_keep'])

        # Precompute trajectory across 180 days (covers D up to 90 + 90 days lookahead)
        dates, balances = self.get_timeline(
            user_id=user_id,
            start_date=request_date,
            horizon_days=180,
            spending_changes=spending_changes,
        )

        date_to_idx = {d: i for i, d in enumerate(dates)}
        start_dt = parse_date(request_date)

        for d_offset in range(91):
            cand_dt = start_dt + timedelta(days=d_offset)
            cand_date_str = format_date(cand_dt)
            cand_idx = date_to_idx[cand_date_str]

            # 90-day lookahead window from D
            window_balances = balances[cand_idx : cand_idx + 91]
            min_bal_in_window = min(window_balances)

            # Check if balance stays >= min_balance after paying requested_amount
            if (min_bal_in_window - requested_amount) >= min_balance:
                return cand_date_str

        return ""

    def simulate_payment_plan(
        self,
        user_id: str,
        payments: List[Tuple[str, float]],
        spending_changes: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Simulates an arbitrary list of (payment_date, amount) tuples.
        Returns True if after every payment, balance stays >= min_balance
        throughout all 90 days following each payment date.
        """
        profile = self.loader.profiles[user_id]
        min_balance = float(profile['minimum_balance_to_keep'])

        if not payments:
            return False

        # Find earliest payment and latest payment
        first_d = payments[0][0]
        last_d = payments[-1][0]

        start_dt = parse_date(first_d)
        last_dt = parse_date(last_d)
        total_horizon = (last_dt - start_dt).days + 95

        dates, base_balances = self.get_timeline(
            user_id=user_id,
            start_date=first_d,
            horizon_days=total_horizon,
            spending_changes=spending_changes,
        )

        date_to_idx = {d: i for i, d in enumerate(dates)}

        # Subtract each payment from all days starting on payment_date
        adjusted_balances = list(base_balances)
        for p_date, p_amt in payments:
            if p_date not in date_to_idx:
                return False
            p_idx = date_to_idx[p_date]
            for i in range(p_idx, len(adjusted_balances)):
                adjusted_balances[i] -= p_amt

        # For each payment date, verify balance >= min_balance for 90 days after it
        for p_date, _ in payments:
            p_idx = date_to_idx[p_date]
            window = adjusted_balances[p_idx : p_idx + 91]
            if min(window) < min_balance - 1e-4:
                return False

        return True
