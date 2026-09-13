"""
output_validator.py
Validates the output rows against the challenge contract and schema.
Centralizes amount formatting and precision rules across the entire system.
"""

import re
from typing import Dict, Any, List, Tuple, Optional


ALLOWED_STATUSES = {
    'affordable_now',
    'affordable_with_plan',
    'affordable_later',
    'not_affordable',
}

ALLOWED_METHODS = {
    'full_payment',
    'partial_payment',
    'installments',
    'wait',
    'not_recommended',
}

REQUIRED_COLUMNS = [
    'request_id',
    'amount_safe_to_pay',
    'affordability_status',
    'recommended_payment_method',
    'payment_plan',
    'earliest_date_for_full_payment',
    'spending_changes_needed',
    'decision_explanation',
]


def format_safe_amount(val: float) -> str:
    """
    Formats amount_safe_to_pay according to ground truth conventions:
    - If whole number: formatted as an integer (e.g. 25256, 873000)
    - If has tenths only: formatted with 1 decimal place (e.g. 603.3)
    - Otherwise: formatted with 2 decimal places (e.g. 284.57)
    """
    r = round(float(val), 2)
    if abs(r - round(r)) < 1e-5:
        return str(int(round(r)))
    if abs(round(r, 1) - r) < 1e-5:
        return f"{r:.1f}"
    return f"{r:.2f}"


def format_plan_amount(val: float, currency: str) -> str:
    """
    Formats amounts in payment_plan:
    - EUR and USD always use 2 decimal places (e.g. 620.40, 1574.40)
    - IDR, INR, ZAR use integer format if whole, else 2 decimal places (e.g. 15952906.67)
    """
    r = round(float(val), 2)
    if currency in ['EUR', 'USD']:
        return f"{r:.2f}"
    if abs(r - round(r)) < 1e-5:
        return str(int(round(r)))
    return f"{r:.2f}"


def format_spending_change_amount(val: float, currency: str) -> str:
    """
    Formats reduction amounts in spending_changes_needed:
    e.g. reduce_to:event_989:665950 (IDR) vs reduce_to:event_1816:23.50 (USD)
    """
    return format_plan_amount(val, currency)


def validate_row(row: Dict[str, Any], requested_amount: Optional[float] = None) -> List[str]:
    """
    Validates a single output row dict.
    Returns a list of error strings (empty if valid).
    """
    errors = []

    # Check required columns
    for col in REQUIRED_COLUMNS:
        if col not in row or row[col] is None:
            errors.append(f"Missing or None column: {col}")

    if errors:
        return errors

    req_id = str(row['request_id']).strip()
    if not req_id:
        errors.append("request_id cannot be empty")

    # amount_safe_to_pay
    try:
        safe_amt = float(row['amount_safe_to_pay'])
        if safe_amt < -1e-5:
            errors.append(f"amount_safe_to_pay ({safe_amt}) cannot be negative")
        if requested_amount is not None and safe_amt > requested_amount + 1e-5:
            errors.append(f"amount_safe_to_pay ({safe_amt}) exceeds requested_amount ({requested_amount})")
    except (ValueError, TypeError):
        errors.append(f"amount_safe_to_pay is not a valid number: {row['amount_safe_to_pay']}")

    # affordability_status
    status = str(row['affordability_status']).strip()
    if status not in ALLOWED_STATUSES:
        errors.append(f"Invalid affordability_status: '{status}'")

    # recommended_payment_method
    method = str(row['recommended_payment_method']).strip()
    if method not in ALLOWED_METHODS:
        errors.append(f"Invalid recommended_payment_method: '{method}'")

    # Consistency between status and method
    if status == 'affordable_now' and method != 'full_payment':
        errors.append(f"Status affordable_now requires full_payment method, got: {method}")
    if status == 'affordable_later' and method != 'wait':
        errors.append(f"Status affordable_later requires wait method, got: {method}")
    if status == 'not_affordable' and method != 'not_recommended':
        errors.append(f"Status not_affordable requires not_recommended method, got: {method}")
    if status == 'affordable_with_plan' and method not in {'full_payment', 'partial_payment', 'installments'}:
        errors.append(f"Status affordable_with_plan requires full_payment (via changes), partial_payment, or installments, got: {method}")

    # earliest_date_for_full_payment
    earliest_date = str(row.get('earliest_date_for_full_payment', '')).strip()
    if method == 'not_recommended':
        if earliest_date and earliest_date != 'nan':
            errors.append(f"earliest_date_for_full_payment must be empty when method is not_recommended, got: '{earliest_date}'")
    elif earliest_date and earliest_date != 'nan':
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', earliest_date):
            errors.append(f"earliest_date_for_full_payment must be YYYY-MM-DD or empty, got: '{earliest_date}'")

    # payment_plan
    plan = str(row.get('payment_plan', '')).strip()
    if method == 'not_recommended':
        if plan != 'none':
            errors.append(f"payment_plan must be 'none' when method is not_recommended, got: '{plan}'")
    else:
        if not plan or plan == 'none':
            errors.append(f"payment_plan cannot be 'none' for method {method}")
        else:
            entries = plan.split('|')
            dates = []
            for entry in entries:
                parts = entry.split(':')
                if len(parts) != 2:
                    errors.append(f"Invalid payment_plan entry: '{entry}' (expected YYYY-MM-DD:amount)")
                    continue
                d_str, amt_str = parts[0], parts[1]
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', d_str):
                    errors.append(f"Invalid date in payment_plan: '{d_str}'")
                try:
                    p_amt = float(amt_str)
                    if p_amt <= 0:
                        errors.append(f"Payment plan amount must be positive: '{amt_str}'")
                except ValueError:
                    errors.append(f"Invalid amount in payment_plan: '{amt_str}'")
                dates.append(d_str)

            # Dates must be chronological
            if dates != sorted(dates):
                errors.append(f"payment_plan dates must be in chronological order: {dates}")

            # If partial_payment, must be exactly 2 payments
            if method == 'partial_payment' and len(entries) != 2:
                errors.append(f"partial_payment requires exactly 2 payments, got {len(entries)}")

    # spending_changes_needed
    changes = str(row.get('spending_changes_needed', '')).strip()
    if not changes or changes == 'nan':
        changes = 'none'
    if changes != 'none':
        parts = changes.split('|')
        if len(parts) > 3:
            errors.append(f"Maximum 3 spending changes allowed, got {len(parts)}: '{changes}'")
        referenced_events = []
        for p in parts:
            if p.startswith('stop:'):
                ev = p[len('stop:'):]
                if not ev.startswith('event_'):
                    errors.append(f"Invalid event ID in stop: '{p}'")
                referenced_events.append(ev)
            elif p.startswith('reduce_to:'):
                sub = p.split(':')
                if len(sub) != 3:
                    errors.append(f"Invalid reduce_to token: '{p}' (expected reduce_to:event_id:amount)")
                else:
                    ev = sub[1]
                    if not ev.startswith('event_'):
                        errors.append(f"Invalid event ID in reduce_to: '{p}'")
                    try:
                        r_amt = float(sub[2])
                        if r_amt <= 0:
                            errors.append(f"reduce_to amount must be positive: '{sub[2]}'")
                    except ValueError:
                        errors.append(f"Invalid reduce_to amount: '{sub[2]}'")
                    referenced_events.append(ev)
            else:
                errors.append(f"Unknown spending change token: '{p}'")
        # Ensure stop and reduce do not reference same event
        if len(referenced_events) != len(set(referenced_events)):
            errors.append(f"Duplicate event referenced in spending changes: {referenced_events}")

    # decision_explanation
    expl = str(row.get('decision_explanation', '')).strip()
    if not expl or expl == 'nan':
        errors.append("decision_explanation must not be empty")

    return errors


def validate_output_dataframe(df_out: Any, df_requests: Optional[Any] = None) -> Dict[str, Any]:
    errors = []
    req_lookup = {}
    if df_requests is not None:
        for _, r in df_requests.iterrows():
            req_lookup[str(r['request_id']).strip()] = float(r['requested_amount'])

    for idx, row in df_out.iterrows():
        rid = str(row.get('request_id', '')).strip()
        req_amt = req_lookup.get(rid)
        row_errs = validate_row(row.to_dict(), requested_amount=req_amt)
        for err in row_errs:
            errors.append(f"Row {idx} ({rid}): {err}")

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'total_rows': len(df_out),
    }
