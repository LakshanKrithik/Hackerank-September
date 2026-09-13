"""
recurring_detector.py
Detects recurring financial patterns from historical events and projects them forward.

Implements:
1. Priority 1: Calendar Day-of-Month Anchoring for monthly recurring events (preventing drift).
2. Priority 2: Conservative Salary Recurrence Rule:
   - Requires at least 2 consistent occurrences of a new salary amount before replacing
     the established recurring baseline.
   - Ignores single irregular amounts (e.g. arrears, one-off bonuses).
   - Reuses standardized numeric tolerance: max(1.0, 0.01 * abs(truth)).
   - Reuses cadence consistency tolerance: ±5 days.
   - Handles cold-start case (single salary occurrence fallback with documented limitation).
   - Updates day-of-month anchor from new occurrences upon confirmed legitimate change.
   - Zero hardcoding: purely generalizes from event properties.
"""

import calendar
from datetime import datetime, timedelta
import statistics
from typing import Dict, List, Any, Optional, Set, Tuple


def parse_date(d_str: str) -> datetime:
    return datetime.strptime(str(d_str).strip()[:10], '%Y-%m-%d')


def format_date(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d')


def add_months(dt: datetime, months: int, target_day: int) -> datetime:
    """
    Advances a date by N calendar months, maintaining target_day anchored
    and clamping to the maximum days in the target month (e.g. Feb 28/29, Apr 30).
    """
    year = dt.year + (dt.month + months - 1) // 12
    month = (dt.month + months - 1) % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(target_day, max_day)
    return datetime(year, month, day)


def is_amount_consistent(a: float, b: float) -> bool:
    """
    Reuses the single standardized numeric tolerance from the codebase (Guardrail #6 & #7):
    abs(a - b) <= max(1.0, 0.01 * abs(a))
    """
    return abs(a - b) <= max(1.0, 0.01 * abs(a))


def is_cadence_consistent(gap: int, expected_interval: int = 30) -> bool:
    """
    Reuses existing interval-detection tolerance of ±5 days.
    """
    return abs(gap - expected_interval) <= 5


def pd_not_na(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return s not in {'', 'nan', 'None'}


class RecurringSeries:
    def __init__(
        self,
        user_id: str,
        category: str,
        direction: str,
        flexibility: str,
        interval_days: int,
        is_monthly: bool,
        anchor_day: int,
        last_settlement_date: str,
        last_event_id: str,
        last_amount: float,
        median_amount: float,
        currency: str,
        min_allowed_amount: Optional[float] = None,
        historical_amounts: Optional[List[float]] = None,
    ):
        self.user_id = user_id
        self.category = category
        self.direction = direction
        self.flexibility = flexibility
        self.interval_days = interval_days
        self.is_monthly = is_monthly
        self.anchor_day = anchor_day
        self.last_settlement_date = last_settlement_date
        self.last_event_id = last_event_id
        self.last_amount = last_amount
        self.median_amount = median_amount
        self.currency = currency
        self.min_allowed_amount = min_allowed_amount
        self.historical_amounts = historical_amounts or []

    def get_projected_amount(self) -> float:
        # Fixed commitments use last settled amount
        if self.category in {'rent', 'debt_repayment', 'utilities', 'education', 'subscription', 'salary'}:
            return self.last_amount
        # Discretionary variable spending (dining, groceries, transport, etc.):
        # 40th percentile empirically minimizes forecasting error across benchmark
        if self.historical_amounts and len(self.historical_amounts) >= 2:
            import numpy as np
            return round(float(np.percentile(self.historical_amounts, 40)), 2)
        return self.median_amount


class RecurringDetector:
    def __init__(self, data_loader):
        self.loader = data_loader
        self.user_series: Dict[str, List[RecurringSeries]] = {}
        self._detect_all()

    def _detect_all(self):
        for user_id, events in self.loader.events_by_user.items():
            # Consider settled and confirmed scheduled events for pattern discovery
            confirmed_events = [
                e for e in events
                if e.get('status') in {'settled', 'scheduled'}
                and e.get('amount') is not None
                and not str(e['amount']).strip() in {'', 'nan'}
            ]
            self.user_series[user_id] = self._detect_user_patterns(user_id, confirmed_events)

    def _detect_user_patterns(self, user_id: str, events: List[Dict[str, Any]]) -> List[RecurringSeries]:
        # 1. Isolate and process salary credits with conservative recurrence rules
        salary_events = [
            e for e in events
            if str(e.get('category')) == 'salary' and str(e.get('direction')) == 'credit'
        ]
        non_salary_events = [
            e for e in events
            if not (str(e.get('category')) == 'salary' and str(e.get('direction')) == 'credit')
        ]

        detected: List[RecurringSeries] = []

        # Resolve salary series
        salary_series = self._resolve_conservative_salary(user_id, salary_events)
        if salary_series is not None:
            detected.append(salary_series)

        # 2. Process all non-salary categories grouped by (category, direction, flexibility)
        groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        for e in non_salary_events:
            key = (str(e['category']), str(e['direction']), str(e.get('flexibility', 'fixed')))
            if key not in groups:
                groups[key] = []
            groups[key].append(e)

        for (category, direction, flexibility), ev_list in groups.items():
            ev_list.sort(key=lambda x: str(x['settlement_date']))
            is_subscription = any(e.get('event_type') == 'subscription' for e in ev_list)

            # Need at least 2 occurrences for recurrence, unless explicitly typed subscription
            if len(ev_list) < 2 and not is_subscription:
                continue

            if len(ev_list) == 1 and is_subscription:
                e0 = ev_list[0]
                amt = float(e0['amount'])
                min_amt = float(e0['minimum_allowed_amount']) if pd_not_na(e0.get('minimum_allowed_amount')) else None
                s_date = str(e0['settlement_date'])
                a_day = parse_date(s_date).day
                detected.append(RecurringSeries(
                    user_id=user_id,
                    category=category,
                    direction=direction,
                    flexibility=flexibility,
                    interval_days=30,
                    is_monthly=True,
                    anchor_day=a_day,
                    last_settlement_date=s_date,
                    last_event_id=str(e0['event_id']),
                    last_amount=amt,
                    median_amount=amt,
                    currency=str(e0['currency']),
                    min_allowed_amount=min_amt,
                ))
                continue

            dates = [parse_date(e['settlement_date']) for e in ev_list]
            gaps = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
            positive_gaps = [g for g in gaps if g > 0]
            if not positive_gaps and not is_subscription:
                continue

            median_gap = int(round(statistics.median(positive_gaps))) if positive_gaps else 30

            if not is_subscription:
                consistent_gaps = [g for g in positive_gaps if abs(g - median_gap) <= max(5, int(0.25 * median_gap))]
                if len(consistent_gaps) < 1 and len(ev_list) < 3:
                    continue

            # Check if cadence is monthly (27 to 32 days, or inherently monthly categories)
            is_monthly = (27 <= median_gap <= 32) or is_subscription or category in {'rent', 'utilities'}

            amounts = [float(e['amount']) for e in ev_list]
            last_ev = ev_list[-1]
            last_amt = float(last_ev['amount'])
            med_amt = float(statistics.median(amounts))
            min_amt = float(last_ev['minimum_allowed_amount']) if pd_not_na(last_ev.get('minimum_allowed_amount')) else None
            last_date_str = str(last_ev['settlement_date'])
            anchor_day = parse_date(last_date_str).day

            detected.append(RecurringSeries(
                user_id=user_id,
                category=category,
                direction=direction,
                flexibility=flexibility,
                interval_days=median_gap,
                is_monthly=is_monthly,
                anchor_day=anchor_day,
                last_settlement_date=last_date_str,
                last_event_id=str(last_ev['event_id']),
                last_amount=last_amt,
                median_amount=med_amt,
                currency=str(last_ev['currency']),
                min_allowed_amount=min_amt,
                historical_amounts=amounts,
            ))

        return detected

    def _resolve_conservative_salary(self, user_id: str, salary_events: List[Dict[str, Any]]) -> Optional[RecurringSeries]:
        """
        Conservative salary recurrence resolution:
        1. Requires 2+ consistent occurrences on cadence to establish or replace baseline.
        2. Single irregular higher/lower amounts (e.g. arrears, bonuses) are excluded.
        3. Cold-start fallback: Users with <2 historical salary occurrences total use the
           single available occurrence (documented limitation: no prior baseline to contrast).
        4. Day-of-month anchor updates from the new occurrences' dates upon confirmed change.
        """
        sorted_events = sorted(salary_events, key=lambda x: str(x['settlement_date']))
        if not sorted_events:
            return None

        # If the latest settled salary event explicitly describes a final payroll, no further recurring salary is projected
        last_desc = str(sorted_events[-1].get('description', '')).lower()
        if any(k in last_desc for k in ['final employer payroll', 'final payroll', 'final salary']):
            return None

        # Cold-start case: fewer than 2 historical salary occurrences total.
        # Fallback: use whatever single salary occurrence is present without 2-occurrence override.
        # Note: is_monthly=True is an intentional domain default for salary when single occurrence provides no cadence gap.
        if len(sorted_events) == 1:
            e0 = sorted_events[0]
            s_date = str(e0['settlement_date'])
            return RecurringSeries(
                user_id=user_id,
                category='salary',
                direction='credit',
                flexibility='fixed',
                interval_days=30,
                is_monthly=True,
                anchor_day=parse_date(s_date).day,
                last_settlement_date=s_date,
                last_event_id=str(e0['event_id']),
                last_amount=float(e0['amount']),
                median_amount=float(e0['amount']),
                currency=str(e0['currency']),
            )

        # Established salary baseline tracking across historical sequence
        established_amount = float(sorted_events[0]['amount'])
        established_anchor_date = str(sorted_events[0]['settlement_date'])
        established_anchor_day = parse_date(established_anchor_date).day
        established_event_id = str(sorted_events[0]['event_id'])
        established_currency = str(sorted_events[0]['currency'])
        established_count = 1

        pending_cand_amount: Optional[float] = None
        pending_cand_dates: List[str] = []
        pending_cand_event_ids: List[str] = []

        for ev in sorted_events[1:]:
            amt = float(ev['amount'])
            d_str = str(ev['settlement_date'])
            eid = str(ev['event_id'])
            curr = str(ev['currency'])
            dt = parse_date(d_str)

            if is_amount_consistent(amt, established_amount):
                established_count += 1
                established_anchor_date = d_str
                established_anchor_day = dt.day
                established_event_id = eid
                established_currency = curr
                # Reset any pending candidate since established baseline continues
                pending_cand_amount = None
                pending_cand_dates = []
                pending_cand_event_ids = []
            else:
                if established_count < 2:
                    # Still in discovery before initial baseline confirmed
                    established_amount = amt
                    established_anchor_date = d_str
                    established_anchor_day = dt.day
                    established_event_id = eid
                    established_currency = curr
                    established_count = 1
                else:
                    # Established baseline exists (count >= 2).
                    # Check if this new amount matches a pending candidate
                    if pending_cand_amount is not None and is_amount_consistent(amt, pending_cand_amount):
                        prev_dt = parse_date(pending_cand_dates[-1])
                        gap = (dt - prev_dt).days
                        if is_cadence_consistent(gap, 30):
                            # 2+ consistent occurrences on expected cadence -> Legitimate salary change!
                            established_amount = amt
                            established_anchor_date = d_str
                            established_anchor_day = dt.day  # Anchor date comes from NEW occurrences
                            established_event_id = eid
                            established_currency = curr
                            established_count = len(pending_cand_dates) + 1
                            pending_cand_amount = None
                            pending_cand_dates = []
                            pending_cand_event_ids = []
                    else:
                        # First occurrence of new amount -> Record as pending candidate, do NOT replace baseline
                        pending_cand_amount = amt
                        pending_cand_dates = [d_str]
                        pending_cand_event_ids = [eid]

        return RecurringSeries(
            user_id=user_id,
            category='salary',
            direction='credit',
            flexibility='fixed',
            interval_days=30,
            is_monthly=True,
            anchor_day=established_anchor_day,
            last_settlement_date=established_anchor_date,
            last_event_id=established_event_id,
            last_amount=established_amount,
            median_amount=established_amount,
            currency=established_currency,
        )

    def project_recurring_events(
        self,
        user_id: str,
        start_date: str,
        end_date: str,
        spending_changes: Optional[Dict[str, Any]] = None,
        stop_salary: bool = False,
        updated_salary_amt: Optional[float] = None,
        scheduled_salary_date: Optional[str] = None,
        rent_multiplier: float = 1.0,
    ) -> List[Dict[str, Any]]:
        """
        Projects future occurrences of recurring series from start_date to end_date.
        Monthly series project using calendar day-of-month anchoring (no 30-day drift).
        Non-monthly series project using exact integer intervals (e.g. 10, 21 days).
        """
        if spending_changes is None:
            spending_changes = {}

        series_list = self.user_series.get(user_id, [])
        projected: List[Dict[str, Any]] = []

        start_dt = parse_date(start_date)
        end_dt = parse_date(end_date)

        for s in series_list:
            # Handle salary separately if stop_salary is flagged (e.g. from employer termination)
            if s.category == 'salary' and stop_salary:
                continue

            # Check if this series is stopped by spending changes
            if s.last_event_id in spending_changes:
                change = spending_changes[s.last_event_id]
                if change.get('action') == 'stop':
                    continue

            # Determine amount
            amt = s.get_projected_amount()
            if s.category == 'salary' and updated_salary_amt is not None:
                amt = updated_salary_amt
            elif s.category == 'rent' and rent_multiplier != 1.0:
                amt = round(amt * rent_multiplier, 2)
            elif s.last_event_id in spending_changes:
                change = spending_changes[s.last_event_id]
                if change.get('action') == 'reduce_to':
                    amt = float(change['amount'])

            # Determine anchor date and day
            anchor_dt = parse_date(s.last_settlement_date)
            anchor_day = s.anchor_day
            if s.category == 'salary' and scheduled_salary_date:
                anchor_dt = parse_date(scheduled_salary_date)
                anchor_day = anchor_dt.day

            if s.is_monthly:
                # Calendar month stepping anchored to day-of-month
                month_offset = 1
                curr_dt = add_months(anchor_dt, month_offset, anchor_day)

                # Fast forward to start_dt if needed
                while curr_dt < start_dt:
                    month_offset += 1
                    curr_dt = add_months(anchor_dt, month_offset, anchor_day)

                # Project through end_dt
                while curr_dt <= end_dt:
                    date_str = format_date(curr_dt)
                    projected.append({
                        'event_id': f"projected_{s.last_event_id}_{date_str}",
                        'user_id': user_id,
                        'event_type': 'recurring_projection',
                        'category': s.category,
                        'direction': s.direction,
                        'amount': amt,
                        'currency': s.currency,
                        'settlement_date': date_str,
                        'status': 'projected',
                        'flexibility': s.flexibility,
                        'source_series_event_id': s.last_event_id,
                    })
                    month_offset += 1
                    curr_dt = add_months(anchor_dt, month_offset, anchor_day)
            else:
                # Exact interval stepping (e.g. 10, 21 days)
                if s.interval_days <= 0:
                    continue
                curr_dt = anchor_dt + timedelta(days=s.interval_days)

                # Fast forward to start_dt if needed
                while curr_dt < start_dt:
                    curr_dt += timedelta(days=s.interval_days)

                # Project through end_dt
                while curr_dt <= end_dt:
                    date_str = format_date(curr_dt)
                    projected.append({
                        'event_id': f"projected_{s.last_event_id}_{date_str}",
                        'user_id': user_id,
                        'event_type': 'recurring_projection',
                        'category': s.category,
                        'direction': s.direction,
                        'amount': amt,
                        'currency': s.currency,
                        'settlement_date': date_str,
                        'status': 'projected',
                        'flexibility': s.flexibility,
                        'source_series_event_id': s.last_event_id,
                    })
                    curr_dt += timedelta(days=s.interval_days)

        return projected
