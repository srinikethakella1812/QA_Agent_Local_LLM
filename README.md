# Q&A Agent (local LLM)

A small agent that answers natural-language questions about data in an Excel file. It
reads the sheet, asks a **local LLM** (qwen2.5-coder:3b) to write pandas code, checks the code for
safety, runs it, and returns a short business-friendly summary. The model runs on
laptop through [Ollama](https://ollama.com), so the data never leaves the machine.

## How it works

1. **Load and clean** the workbook: parse dates, rename columns, normalise
   category labels to uppercase, and add a `month` column (e.g. `2026-03`)
   that is easy for a small model to group on.
3. **Describe the schema** to the model: column types, allowed values of
   low-cardinality text columns, the date range and two sample rows. The model never
   sees the full data.
4. **Give it a curated view.** Business rules live in the data layer, not only in
   the prompt: the agent gets `df` (every withdrawal) and `spend` (the same data
   without non-spending categories such as investments and loan repayments).
5. **Generate pandas code** with a small local model (`qwen2.5-coder:3b`), guided by a
   few worked examples and rules in the system prompt.
6. **Check the pandas code** with an AST whitelist before running it: only pandas/numpy
   imports; no `open`, `eval`, `exec`, dunder attributes, or file read/write calls.
7. **Execute**: if the pandas code fails, the error plus an error-specific repair hint is
   sent back to the LLM (retries use a little temperature so they can vary).
8. **Summarise** only the computed result, so figures in the answer come from the
   data. The generated code is shown for review.

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
| 1 | 110-row statement | 13/14 | Added group-by rule/example; retries at temperature 0.3 |
| 2 | 110-row statement | 17/17 | Error-specific repair hints; date-filter rule and example |
| 3 | 868-row year-to-date statement | 15/21 | New, larger and messier data exposed new failures |
| 4 | 868-row year-to-date statement | 24/24 | Fixed a wrong test; added the `spend` view and an "average per month" rule |


## Limitations

- The test set is small, so score of 24/24 is optimistic. A properly held-out set and more paraphrased questions are needed.
- A 3B model can fail on multi-step questions and ambiguous wording.
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
eval.py            evaluation setup (24 questions)
statement.xlsx     anonymised sample data
requirements.txt   dependencies
```
