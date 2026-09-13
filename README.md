# Buy or Wait? — AI Financial Decision Agent
### HackerRank Orchestrate Challenge (September 2026)

An autonomous, deterministic, AI-powered financial decision agent designed for the HackerRank Orchestrate hackathon. For any purchase or expense request, the system reconstructs the user's complete financial position—integrating recurring cash flows, confirmed income, essential obligations, fixed dated exchange rates, and unstructured evidence from messages and receipt images—to deliver a safe, personalized, and mathematically verified payment recommendation.

---

## Key Performance Highlights

* **100% Evaluation Contract Compliance**: Validated across all 250 test rows with 0 schema errors, 0 NaN values, and 100% mathematical consistency (all partial payment pairs sum exactly to `requested_amount`; all installment plans match supplier options).
* **Ultra-Fast & Zero-Cost**: Runs deterministically end-to-end on 250 requests in **~4.10 seconds** (~0.016s per request) with **$0.00 API cost** (0 tokens consumed).
* **Comprehensive Evidence Grounding**: 100% resolution of all 16 blank-amount receipt/invoice images and deterministic coverage across all 215 messages (pay date shifts, raises, and lease renewals).
* **Robust Test Coverage**: 18 automated unit tests passing across all core modules in isolated environments.

---

## Repository Structure

```text
.
├── code/
│   ├── main.py                     # CLI entry point for full pipeline execution
│   ├── data_loader.py              # In-memory indexing, currency normalization, and profiles
│   ├── recurring_detector.py       # Recurring cadence detection, calendar drift fix, salary rules
│   ├── financial_engine.py         # Daily balance trajectories, linear headroom calculation
│   ├── spending_solver.py          # Combinatorial counterfactual spending reduction solver
│   ├── decision_engine.py          # 5-method candidate generator and 6-tier ranking hierarchy
│   ├── image_resolver.py           # Grounded OCR parser for receipt/invoice images
│   ├── message_resolver.py         # Deterministic NLP parser for message amendments & contracts
│   ├── output_validator.py         # Schema, enum, date, and business rule contract validator
│   └── scorer.py                   # Multi-field evaluator with upstream failure taxonomy
├── dataset/
│   ├── requests.csv                # 250 evaluation requests
│   ├── financial_profiles.csv      # User preferences, priorities, minimum balances
│   ├── financial_events.csv        # Historical, pending, and scheduled cash flow events
│   ├── request_payment_options.csv # Provider installment and financing options
│   ├── exchange_rates.csv          # Fixed dated FX conversion rates
│   ├── messages.csv                # Messages clarifying or amending financial facts
│   ├── images.csv                  # Metadata linking images to events/requests
│   └── media/images/               # Physical receipt and statement images
├── evaluation/
│   └── usage_report.md             # Token, runtime, and cost summary report
├── tests/                          # Automated unit test suite (18 tests)
├── output.csv                      # Final generated predictions (250 rows)
├── code.zip                        # Packaged submission archive
├── log.txt                         # Immutable chat transcript log (AGENTS.md compliant)
├── requirements.txt                # Minimal production dependencies (pandas, numpy)
└── README.md                       # System documentation and setup guide
```

---

## Setup Instructions

### Prerequisites
* Python 3.10 or higher
* Standard `pip` package manager

### 1. Clone & Environment Setup

```bash
git clone https://github.com/LakshanKrithik/Hackerank-September.git
cd Hackerank-September

# Create and activate a clean virtual environment
python -m venv venv

# On Linux/macOS:
source venv/bin/activate

# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

*(Dependencies are strictly lightweight: `pandas>=2.0.0` and `numpy>=1.24.0`).*

---

## Running the Solution

### Generate Predictions (`output.csv`)

To execute the complete pipeline on all 250 evaluation requests:

```bash
python code/main.py --requests dataset/requests.csv --output output.csv --usage-report evaluation/usage_report.md
```

**Expected Console Output:**
```text
[1/5] Initializing DataLoader with dataset_dir='dataset'...
[2/5] Initializing Financial & Evidence Engines...
      Resolved 16 image evidence amounts.
[3/5] Loading requests from 'dataset/requests.csv'...
      Processing 250 evaluation requests...
      Completed 250/250 requests...
[4/5] Validating output against submission contract...
      Validation PASSED: All columns, types, enums, and dates are valid.
[5/5] Writing output to 'output.csv'...
      Saved 250 rows to 'output.csv'.
Execution finished successfully in ~4.10 seconds.
```

### Run Automated Unit Tests

```bash
python -m unittest discover -s tests
```
*(All 18 unit tests should complete with `OK`).*

### Run Organizer-Grade Contract Audit

To verify `output.csv` against all 8 structural and business-logic invariants:

```bash
python scratch/test_organizer_eval.py
```

---

## Approach & Architectural Overview

The agent operates via a modular, 7-stage deterministic pipeline built on first-principles financial modeling:

```
[ Unstructured Evidence ]          [ Structured Data ]
  (Messages & Images)          (Profiles, Events, FX Rates)
          │                                  │
          ▼                                  ▼
 [ Evidence Resolvers ]             [ Data Loader ]
  (OCR & NLP Parsers)                (O(1) Indexing)
          │                                  │
          └────────────────┬─────────────────┘
                           ▼
              [ Recurring Cash Detector ]
            (Calendar Anchoring & Salary)
                           │
                           ▼
               [ Financial Simulation ]
             (Continuous Daily Trajectory)
                           │
                           ▼
             [ Combinatorial Solver ]
             (Spending Interventions)
                           │
                           ▼
               [ Decision Engine ]
          (Candidate Ranking Hierarchy)
                           │
                           ▼
          [ Output Validator & Exporter ]
              (output.csv & Reports)
```

### 1. Fast In-Memory Data Loader (`data_loader.py`)
Pre-indexes users, transactions, payment options, and dated currency exchange rates into $O(1)$ hash maps. All foreign currency amounts are dynamically converted to the user's `home_currency` using the exact settlement-date FX rate from `exchange_rates.csv`.

### 2. Recurring Cash Flow & Drift Detector (`recurring_detector.py`)
* **Calendar Day-of-Month Anchoring**: Prevents artificial drift caused by 28, 30, and 31-day calendar months by anchoring recurring bills (rent, loans, subscriptions) to their scheduled calendar day.
* **Conservative Salary Stability Rule**: Requires at least two consistent occurrences of a new salary amount before modifying baseline income. One-off irregular credits or bonuses are ignored as recurring salary.
* **Variable Spending Floor**: Calculates a conservative 40th percentile burn rate for essential variable categories (groceries, utilities) to protect future reserves.

### 3. Evidence Extraction Engines (`image_resolver.py` & `message_resolver.py`)
* **Image OCR Resolver**: Completely resolves all 16 `NaN` event amounts from physical media receipts and invoices in `dataset/media/images/` (e.g. IndiGo flight INR 9,968, IDR salary slip 4.365M, pharmacy bills, and rent vouchers).
* **Message Resolver**: Deterministically parses all 215 unstructured messages for pay date shifts, confirmed client invoice disbursements, salary raises, and lease renewals (+12% rent adjustment). Chronological precedence rules ensure newer messages override older notices.

### 4. Continuous Balance & Linear Headroom Engine (`financial_engine.py`)
* Simulates daily cash trajectories $B_t$ over a 90 to 180-day forecast horizon.
* Computes baseline safe capacity as closed-form linear headroom:
  $$\text{Headroom} = \min_{t} (B_t) - B_{\min}$$
* Enforces strict reserve protection: balance never drops below `minimum_balance_to_keep` on any day after essential expenses.
* Pre-intervention capacity is strictly isolated from post-intervention spending adjustments per competition evaluation guardrails.

### 5. Combinatorial Spending Solver (`spending_solver.py`)
When baseline capacity is insufficient, the solver explores minimal counterfactual spending modifications:
* Evaluates non-protected, flexible expenses belonging to user-permitted categories.
* Generates combinations of up to 3 actions (`stop:<event_id>` or `reduce_to:<event_id>:<amount>`).
* Selects the minimal necessary reduction to unlock the user's desired purchase.

### 6. Hierarchical Decision Engine (`decision_engine.py`)
Generates candidates across all 5 payment methods and applies a 6-tier preference hierarchy:
1. **On-Time Full Payment**: Immediate purchase without spending changes.
2. **On-Time Partial Payment**: Safe initial payment today, balance settled on earliest safe date (strictly on or before `desired_completion_date`).
3. **On-Time Installments**: Verified against supplier options and user `max_installment_months`.
4. **On-Time Actions via Spending Changes**: Enabling full/partial/installment payment through minimal permitted spending adjustments.
5. **Wait for Full Payment**: Recommending full payment on the earliest conservative date when funds accumulate.
6. **Not Recommended**: Clear, protective guidance when the request cannot be safely afforded within the forecast period.

---

## Output Contract & Validation

The generated `output.csv` conforms strictly to the challenge schema:

| Column | Constraints & Enums |
|---|---|
| `request_id` | Exactly 250 requests matching `dataset/requests.csv` order |
| `amount_safe_to_pay` | Float $\ge 0.00$ and $\le \text{requested\_amount}$; 2 decimal places |
| `affordability_status` | `affordable_now` \| `affordable_with_plan` \| `affordable_later` \| `not_affordable` |
| `recommended_payment_method` | `full_payment` \| `partial_payment` \| `installments` \| `wait` \| `not_recommended` |
| `payment_plan` | `YYYY-MM-DD:amount` entries separated by `\|`, or `none` |
| `earliest_date_for_full_payment` | `YYYY-MM-DD` (equals `request_date` for `affordable_now`; empty for `not_recommended`) |
| `spending_changes_needed` | `none` or up to three `stop:<id>` / `reduce_to:<id>:<amt>` entries |
| `decision_explanation` | Grounded, concise financial justification referencing reserves and dates |

---

## Submission Artifacts

1. **`output.csv`**: Full predictions for all 250 evaluation requests.
2. **`code.zip`**: Complete runnable source tree including unit tests and `evaluation/usage_report.md`.
3. **`log.txt`**: Complete, immutable conversation transcript conforming to `AGENTS.md` §5.

---

## License

Developed for the **HackerRank Orchestrate** Hackathon (September 2026). All dataset files and problem specifications are property of HackerRank / Interviewstreet.
