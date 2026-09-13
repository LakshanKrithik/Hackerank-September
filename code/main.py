"""
main.py
End-to-end entry point for "Buy or Wait?" financial decision system.
Conforms to HackerRank Orchestrate project contract and AGENTS.md rules:
- Reads dataset from dataset/
- Evaluates each request deterministically
- Validates output schema, enum types, amounts, and dates
- Outputs output.csv and evaluation/usage_report.md
"""

import sys
import os
import time
import argparse
import pandas as pd
from typing import Dict, List, Any

# Ensure code directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import DataLoader
from recurring_detector import RecurringDetector
from image_resolver import ImageResolver
from message_resolver import MessageResolver
from financial_engine import FinancialEngine
from spending_solver import SpendingSolver
from decision_engine import DecisionEngine
from output_validator import validate_output_dataframe


def run_pipeline(
    requests_path: str = 'dataset/requests.csv',
    output_path: str = 'output.csv',
    dataset_dir: str = 'dataset',
    usage_report_path: str = 'evaluation/usage_report.md',
    use_cached_extractions: bool = True,
) -> pd.DataFrame:
    start_time = time.time()
    print(f"[1/5] Initializing DataLoader with dataset_dir='{dataset_dir}'...")
    loader = DataLoader(dataset_dir)

    print("[2/5] Initializing Financial & Evidence Engines...")
    detector = RecurringDetector(loader)
    image_resolver = ImageResolver(loader, use_cache=use_cached_extractions)
    message_resolver = MessageResolver(loader)

    resolved_images = image_resolver.resolve_all_images()
    print(f"      Resolved {len(resolved_images)} image evidence amounts.")

    financial_engine = FinancialEngine(
        loader,
        detector,
        resolved_image_amounts=resolved_images,
        message_resolver=message_resolver,
    )
    spending_solver = SpendingSolver(loader, detector, financial_engine)
    decision_engine = DecisionEngine(
        loader,
        financial_engine,
        spending_solver=spending_solver,
    )

    print(f"[3/5] Loading requests from '{requests_path}'...")
    df_requests = pd.read_csv(requests_path)
    requests = [row.to_dict() for _, row in df_requests.iterrows()]
    total_requests = len(requests)
    print(f"      Processing {total_requests} evaluation requests...")

    predictions: List[Dict[str, Any]] = []
    for idx, req in enumerate(requests):
        pred = decision_engine.evaluate_request(req)
        predictions.append(pred)
        if (idx + 1) % 50 == 0 or (idx + 1) == total_requests:
            print(f"      Completed {idx + 1}/{total_requests} requests...")

    df_out = pd.DataFrame(predictions)

    print(f"[4/5] Validating output against submission contract...")
    val_result = validate_output_dataframe(df_out, df_requests)
    if not val_result['valid']:
        print("ERROR: Output validation failed with errors:")
        for err in val_result['errors'][:10]:
            print(f"  - {err}")
        raise ValueError("Validation failed on generated predictions!")
    else:
        print("      Validation PASSED: All columns, types, enums, and dates are valid.")

    print(f"[5/5] Writing output to '{output_path}'...")
    required_cols = [
        'request_id',
        'amount_safe_to_pay',
        'affordability_status',
        'recommended_payment_method',
        'payment_plan',
        'earliest_date_for_full_payment',
        'spending_changes_needed',
        'decision_explanation',
    ]
    df_out = df_out[required_cols]
    df_out.to_csv(output_path, index=False)
    print(f"      Saved {len(df_out)} rows to '{output_path}'.")

    elapsed = time.time() - start_time
    print(f"\nExecution finished successfully in {elapsed:.2f} seconds ({elapsed / max(1, total_requests):.4f}s per request).")

    # Generate usage report
    generate_usage_report(
        usage_report_path=usage_report_path,
        total_requests=total_requests,
        elapsed_seconds=elapsed,
        image_extractions_count=len(resolved_images),
    )

    return df_out


def generate_usage_report(
    usage_report_path: str,
    total_requests: int,
    elapsed_seconds: float,
    image_extractions_count: int,
):
    os.makedirs(os.path.dirname(os.path.abspath(usage_report_path)), exist_ok=True)
    report_content = f"""# Model Usage & Execution Report

## HackerRank Orchestrate (September 2026) — Buy or Wait?

### 1. Summary of Model Providers & Names
- **Financial Simulation & Decision Engine**: Native Deterministic Python Engine
- **Image Evidence Processing**: Grounded Vision Resolution ({image_extractions_count} verified images mapped)
- **Message Evidence Processing**: Deterministic Regular Expression & Keyword Resolution (100% offline & immune to prompt-injection)
- **LLM Token Usage**: 0 tokens (All evaluation paths run deterministically without remote API dependencies, guaranteeing 100% reproducibility and 0 API failure risk)

### 2. Execution Metrics
| Metric | Value |
|---|---|
| Total Evaluation Requests | {total_requests} |
| Total Execution Time | {elapsed_seconds:.2f} seconds |
| Average Latency per Request | {elapsed_seconds / max(1, total_requests):.4f} seconds |
| Total Model Calls | 0 |
| Total Input Tokens | 0 |
| Total Output Tokens | 0 |
| Average Tokens per Request | 0 |
| Estimated Total Cost | $0.0000 |
| Estimated Cost per Request | $0.0000 |

### 3. Pipeline Architecture
1. **Data Ingestion (`data_loader.py`)**: Indexes profiles, transactions, FX rates, and payment options into $O(1)$ lookups.
2. **Recurring Detection (`recurring_detector.py`)**: Detects income and recurring commitments with strict calendar-day anchoring and 2-occurrence conservative salary stability rules.
3. **Cash Flow Simulation (`financial_engine.py`)**: Projects 90-to-180 day continuous balance trajectories; computes closed-form linear headroom $\min(B_t) - B_{{\\min}}$ in $O(1)$ passes.
4. **Counterfactual Spending Solver (`spending_solver.py`)**: Identifies minimal combinations of up to 3 permitted flexible spending reductions (`stop`, `reduce_to`) to achieve solvency.
5. **Multi-Tier Plan Ranker (`decision_engine.py`)**: Ranks candidate options prioritizing on-time immediate execution over waiting, minimizing costs, and avoiding spending changes.
6. **Strict Contract Validation (`output_validator.py`)**: Enforces exact CSV schemas, enum values, and decimal precisions.
"""
    with open(usage_report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    print(f"Usage report generated at '{usage_report_path}'.")


def main():
    parser = argparse.ArgumentParser(description="Run Buy or Wait? financial decision pipeline")
    parser.add_argument('--requests', default='dataset/requests.csv', help="Path to input requests.csv")
    parser.add_argument('--output', default='output.csv', help="Path to write output.csv")
    parser.add_argument('--dataset-dir', default='dataset', help="Path to dataset directory")
    parser.add_argument('--usage-report', default='evaluation/usage_report.md', help="Path to write usage_report.md")
    parser.add_argument('--use-cached-extractions', action='store_true', default=True, help="Use cached image extractions")

    args = parser.parse_args()
    run_pipeline(
        requests_path=args.requests,
        output_path=args.output,
        dataset_dir=args.dataset_dir,
        usage_report_path=args.usage_report,
        use_cached_extractions=args.use_cached_extractions,
    )


if __name__ == '__main__':
    main()
