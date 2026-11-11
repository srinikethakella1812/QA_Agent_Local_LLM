# Q&A Agent (local LLM, pandas, no cloud)

A small agent that answers natural-language questions about data in an Excel file. It
reads the sheet, asks a **local LLM** (qwen2.5-coder:3b) to write pandas code, checks the code for
safety, runs it, and returns a short business-friendly summary. The model runs on
laptop through [Ollama](https://ollama.com), so the data never leaves the machine.

## How it works

1. **Load and clean** the workbook: parse dates, rename columns, normalise
   category labels to uppercase (64 raw labels become 45), and add a `month`
   column (e.g. `2026-03`) that is easy for a small model to group on.
2. **Describe the schema** to the model: column types, allowed values of
   low-cardinality text columns, the date range and two sample rows. The model never
   sees the full data.
3. **Give it a curated view.** Business rules live in the data layer, not only in
   the prompt: the agent gets `df` (every withdrawal) and `spend` (the same data
   without non-spending categories such as investments and loan repayments).
4. **Generate code** with a small local model (`qwen2.5-coder:3b`), guided by a
   few worked examples and rules in the system prompt.
5. **Check the code** with an AST whitelist before running it: only pandas/numpy
   imports; no `open`, `eval`, `exec`, dunder attributes, or file read/write calls.
6. **Execute**; if the code fails, the error plus an error-specific repair hint is
   sent back to the model (retries use a little temperature so they can vary).
7. **Summarise** only the computed result, so figures in the answer come from the
   data. The generated code is always shown for auditability.

## Quick start

Prerequisites: Python 3.10+, Ollama, about 8 GB RAM (it runs on CPU).

```powershell
ollama pull qwen2.5-coder:3b
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python agent.py statement.xlsx
```

Example questions: *What is the total spending?*, *Which month had the highest
spending?*, *How much did Person_B spend on FOOD?*

## The data

`statement.xlsx` is an anonymised bank-statement export: 868 withdrawals from
1 Jan to 25 Sep 2026, with columns `Date`, `Withdrawal Amt.`, `Name`, `Category`.
Names are replaced by `Person_A` / `Person_B`. To use your own file, adapt `clean()`
and `DATA_NOTES` in `agent.py` to your schema.

## Evaluation

`eval.py` holds 24 questions whose expected answers are computed directly with
pandas, so the check does not depend on the model. It runs the agent without the
summary step and compares the raw result.

```powershell
python eval.py
```

| Run | Dataset | Score | What changed |
|-----|---------|-------|--------------|
| 1 | synthetic cards data | 9/10 | First version: schema + one worked example |
| 2 | 110-row statement | 13/14 | Added group-by rule/example; retries at temperature 0.3 |
| 3 | 110-row statement | 17/17 | Error-specific repair hints; date-filter rule and example |
| 4 | 868-row year-to-date statement | 15/21 | New, larger and messier data exposed new failures |
| 5 | 868-row year-to-date statement | 24/24 | Fixed a wrong test; added the `spend` view and an "average per month" rule |

## Learnings:

- **A leaky prompt example caused a repeated failure.** An example that ended in
  `.sum()` led the model to try sorting a single number. Prompt examples and test
  questions should be different questions.
- **Deterministic retries repeat mistakes.** At temperature 0 the same bad code was
  generated three times. The first attempt stays deterministic; retries add variety.
- **Tell the model how to fix an error, not just what it was.** One failure was
  `dt.year == 2026 & dt.month == 9`: `&` binds tighter than `==`, so each condition
  needs parentheses. A targeted hint fixed it on the next attempt.
- **Silent wrong answers are the real risk.** On the year-to-date data the agent
  returned valid but wrong numbers (it forgot to exclude non-spending categories).
  The retry loop only catches code that crashes, so these were only found because
  the evaluation answers were computed independently.
- **Move business rules into the data layer.** Instead of hoping a 3B model
  remembers a filter, the `spend` DataFrame applies it deterministically.
- **Tests can be wrong too.** One failing test was a bug in my expected value
  (the agent's answer was correct), so I now check failures in both directions.

## Limitations

- The test set is small, written by me, and I tuned the prompt against it, so
  24/24 is optimistic. A properly held-out set and more paraphrased questions are needed.
- A 3B model can fail on multi-step questions and ambiguous wording.
- The AST whitelist is a guardrail, not a sandbox. Do not run untrusted input against it.
- One sheet of 868 rows. Larger data would need SQL pushdown or Spark.
- Which categories count as "spending" is a judgement call encoded in `NON_SPEND`.

## Next steps

- Run generated code in an isolated subprocess/container with time and memory limits
- Log queries and track first-attempt accuracy vs accuracy after retries
- Add reconciliation checks (e.g. spend + excluded = total) and a verification pass
- Held-out evaluation set; multi-sheet joins; a clarifying-question step

## Files

```
agent.py           the agent (load/clean, schema, safety check, retry loop)
eval.py            evaluation suite (24 questions)
statement.xlsx     anonymised sample data
requirements.txt   dependencies
```
