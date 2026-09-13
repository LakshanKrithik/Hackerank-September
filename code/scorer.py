"""
scorer.py
Evaluates predicted output against dataset/sample_requests.csv ground truth.
Includes divide-by-zero protection on amount_safe_to_pay and detailed mismatch diagnostics.
"""

import sys
import os
import argparse
import pandas as pd
from typing import Dict, List, Any, Tuple


def normalize_val(val: Any) -> str:
    if pd.isna(val) or val is None:
        return ''
    s = str(val).strip()
    if s.lower() == 'nan':
        return ''
    return s


def normalize_spending_changes(val: Any) -> set:
    s = normalize_val(val)
    if not s or s == 'none':
        return {'none'}
    return set(s.split('|'))


def normalize_plan(val: Any) -> str:
    s = normalize_val(val)
    if not s or s == 'none':
        return 'none'
    # Normalize each date:amount pair
    parts = s.split('|')
    norm_parts = []
    for p in parts:
        sub = p.split(':')
        if len(sub) == 2:
            dt = sub[0].strip()
            try:
                amt = float(sub[1].strip())
                norm_parts.append(f"{dt}:{amt:.2f}")
            except ValueError:
                norm_parts.append(p.strip())
        else:
            norm_parts.append(p.strip())
    return '|'.join(norm_parts)


def score_single(pred_row: Dict[str, Any], truth_row: Dict[str, Any]) -> Dict[str, bool]:
    results = {}

    # 1. affordability_status
    p_status = normalize_val(pred_row.get('affordability_status'))
    t_status = normalize_val(truth_row.get('affordability_status'))
    results['affordability_status'] = (p_status == t_status)

    # 2. recommended_payment_method
    p_method = normalize_val(pred_row.get('recommended_payment_method'))
    t_method = normalize_val(truth_row.get('recommended_payment_method'))
    results['recommended_payment_method'] = (p_method == t_method)

    # 3. amount_safe_to_pay (with divide-by-zero fix)
    try:
        p_safe = float(pred_row.get('amount_safe_to_pay', 0))
        t_safe = float(truth_row.get('amount_safe_to_pay', 0))
        diff = abs(p_safe - t_safe)
        tol = max(1.0, 0.01 * abs(t_safe))
        results['amount_safe_to_pay'] = (diff <= tol)
    except (ValueError, TypeError):
        results['amount_safe_to_pay'] = False

    # 4. earliest_date_for_full_payment
    p_date = normalize_val(pred_row.get('earliest_date_for_full_payment'))
    t_date = normalize_val(truth_row.get('earliest_date_for_full_payment'))
    results['earliest_date_for_full_payment'] = (p_date == t_date)

    # 5. payment_plan (normalized)
    p_plan = normalize_plan(pred_row.get('payment_plan'))
    t_plan = normalize_plan(truth_row.get('payment_plan'))
    results['payment_plan'] = (p_plan == t_plan)

    # 6. spending_changes_needed (order-independent set match)
    p_changes = normalize_spending_changes(pred_row.get('spending_changes_needed'))
    t_changes = normalize_spending_changes(truth_row.get('spending_changes_needed'))
    results['spending_changes_needed'] = (p_changes == t_changes)

    return results


def evaluate_predictions(pred_df: pd.DataFrame, truth_df: pd.DataFrame) -> Dict[str, Any]:
    truth_by_id = {row['request_id']: row.to_dict() for _, row in truth_df.iterrows()}
    pred_by_id = {row['request_id']: row.to_dict() for _, row in pred_df.iterrows()}

    matched_ids = [rid for rid in truth_by_id if rid in pred_by_id]
    if not matched_ids:
        print("ERROR: No matching request_ids found between predictions and ground truth!")
        return {}

    field_scores = {
        'affordability_status': 0,
        'recommended_payment_method': 0,
        'amount_safe_to_pay': 0,
        'earliest_date_for_full_payment': 0,
        'payment_plan': 0,
        'spending_changes_needed': 0,
    }
    fully_correct = 0
    mismatches = []

    for rid in matched_ids:
        p_row = pred_by_id[rid]
        t_row = truth_by_id[rid]
        res = score_single(p_row, t_row)

        all_ok = True
        failed_fields = []
        for field, ok in res.items():
            if ok:
                field_scores[field] += 1
            else:
                all_ok = False
                failed_fields.append((field, p_row.get(field), t_row.get(field)))

        if all_ok:
            fully_correct += 1
        else:
            mismatches.append((rid, failed_fields))

    n = len(matched_ids)

    # Classify failures by upstream root cause
    failure_taxonomy = {
        'SPENDING_INTERVENTION_MISMATCH': [],
        'TIMING_OR_METHOD_RANKING': [],
        'VARIABLE_EXPENSE_HEADROOM': [],
        'MESSAGE_OR_DATA_AMENDMENT': [],
    }

    per_request_diffs = []

    for rid, fails in mismatches:
        failed_fields_dict = {f[0]: (f[1], f[2]) for f in fails}
        p_row = pred_by_id[rid]
        t_row = truth_by_id[rid]

        # Categorize
        if 'spending_changes_needed' in failed_fields_dict:
            cause = 'SPENDING_INTERVENTION_MISMATCH'
        elif 'affordability_status' in failed_fields_dict or 'recommended_payment_method' in failed_fields_dict:
            cause = 'TIMING_OR_METHOD_RANKING'
        elif len(failed_fields_dict) == 1 and 'amount_safe_to_pay' in failed_fields_dict:
            cause = 'VARIABLE_EXPENSE_HEADROOM'
        else:
            cause = 'MESSAGE_OR_DATA_AMENDMENT'

        failure_taxonomy[cause].append({
            'request_id': rid,
            'failed_fields': fails,
            'pred': p_row,
            'truth': t_row,
        })

    summary = {
        'total_requests': n,
        'fully_correct_requests': fully_correct,
        'full_match_accuracy': fully_correct / n,
        'field_accuracies': {f: count / n for f, count in field_scores.items()},
        'mismatches': mismatches,
        'failure_taxonomy': failure_taxonomy,
    }
    return summary


def print_report(summary: Dict[str, Any]):
    n = summary['total_requests']
    print("\n" + "=" * 75)
    print(f"EVALUATION SUMMARY ({n} sample requests)")
    print("=" * 75)
    print(f"Overall Exact Match (All 6 fields): {summary['fully_correct_requests']}/{n} ({summary['full_match_accuracy']*100:.1f}%)")
    print("-" * 75)
    print("Per-Field Accuracies:")
    for f, acc in summary['field_accuracies'].items():
        print(f"  - {f:<32}: {acc*100:5.1f}%")
    print("-" * 75)

    tax = summary.get('failure_taxonomy', {})
    print("UPSTREAM FAILURE TAXONOMY:")
    for cat, items in tax.items():
        rids = [item['request_id'] for item in items]
        print(f"  * {cat:<32}: {len(items)} requests -> {rids}")

    print("-" * 75)
    if summary['mismatches']:
        print(f"Detailed Mismatches ({len(summary['mismatches'])} requests):")
        for rid, fails in summary['mismatches']:
            print(f"\n[{rid}]")
            for field, p_val, t_val in fails:
                print(f"  - {field:<30}: Pred: '{p_val}' | Truth: '{t_val}'")
    else:
        print("PERFECT 100% MATCH ACROSS ALL SAMPLE REQUESTS!")
    print("=" * 75 + "\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Evaluate predicted output.csv against sample_requests.csv")
    parser.add_argument('--pred-file', default='output.csv', help="Path to predicted output.csv")
    parser.add_argument('--sample-file', default='dataset/sample_requests.csv', help="Path to sample_requests.csv")
    args = parser.parse_args()

    if not os.path.exists(args.pred_file):
        print(f"Prediction file not found: {args.pred_file}")
        sys.exit(1)
    if not os.path.exists(args.sample_file):
        print(f"Sample ground truth file not found: {args.sample_file}")
        sys.exit(1)

    pred_df = pd.read_csv(args.pred_file)
    sample_df = pd.read_csv(args.sample_file)

    summary = evaluate_predictions(pred_df, sample_df)
    print_report(summary)
