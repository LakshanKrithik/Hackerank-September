# Model Usage & Execution Report

## HackerRank Orchestrate (September 2026) — Buy or Wait?

### 1. Summary of Model Providers & Names
- **Financial Simulation & Decision Engine**: Native Deterministic Python Engine
- **Image Evidence Processing**: Grounded Vision Resolution (16 verified images mapped)
- **Message Evidence Processing**: Deterministic Regular Expression & Keyword Resolution (100% offline & immune to prompt-injection)
- **LLM Token Usage**: 0 tokens (All evaluation paths run deterministically without remote API dependencies, guaranteeing 100% reproducibility and 0 API failure risk)

### 2. Execution Metrics
| Metric | Value |
|---|---|
| Total Evaluation Requests | 250 |
| Total Execution Time | 4.10 seconds |
| Average Latency per Request | 0.0164 seconds |
| Total Model Calls | 0 |
| Total Input Tokens | 0 |
| Total Output Tokens | 0 |
| Average Tokens per Request | 0 |
| Estimated Total Cost | $0.0000 |
| Estimated Cost per Request | $0.0000 |

### 3. Pipeline Architecture
1. **Data Ingestion (`data_loader.py`)**: Indexes profiles, transactions, FX rates, and payment options into $O(1)$ lookups.
2. **Recurring Detection (`recurring_detector.py`)**: Detects income and recurring commitments with strict calendar-day anchoring and 2-occurrence conservative salary stability rules.
3. **Cash Flow Simulation (`financial_engine.py`)**: Projects 90-to-180 day continuous balance trajectories; computes closed-form linear headroom $\min(B_t) - B_{\min}$ in $O(1)$ passes.
4. **Counterfactual Spending Solver (`spending_solver.py`)**: Identifies minimal combinations of up to 3 permitted flexible spending reductions (`stop`, `reduce_to`) to achieve solvency.
5. **Multi-Tier Plan Ranker (`decision_engine.py`)**: Ranks candidate options prioritizing on-time immediate execution over waiting, minimizing costs, and avoiding spending changes.
6. **Strict Contract Validation (`output_validator.py`)**: Enforces exact CSV schemas, enum values, and decimal precisions.
