import ast
import contextlib
import io
import re
import sys

import numpy as np
import pandas as pd
import requests

MODEL = "qwen2.5-coder:3b"
OLLAMA_URL = "http://localhost:11434/api/chat"
MAX_RETRIES = 3
NON_SPEND = ["EMI", "INVESTMENT"]
FENCE = "`" * 3  # three backticks, built here so this file stays easy to paste


# ---------- LLM: the only provider-specific function ----------
def llm(messages, temperature=0):
    r = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": temperature, "num_ctx": 4096},
        },
        timeout=600,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


# ---------- Data ----------
def clean(d):
    d = d.rename(columns={
        "Date": "date", "Withdrawal Amt.": "amount", "Name": "name", "Category": "category"})
    d["date"] = pd.to_datetime(d["date"], format="%d/%m/%y")
    d["category"] = d["category"].str.strip().str.upper()
    d["month"] = d["date"].dt.strftime("%Y-%m")  # e.g. '2026-03', easy for a small model to group on
    return d


def load_data(path):
    sheets = pd.read_excel(path, sheet_name=None)
    return {name: clean(d) for name, d in sheets.items()}


def describe_schema(dfs, n=2):
    parts = []
    for name, d in dfs.items():
        lines = [f"Sheet '{name}': {d.shape[0]} rows x {d.shape[1]} cols",
                 "Columns and dtypes:", d.dtypes.to_string()]
        for col in d.columns:
            if pd.api.types.is_datetime64_any_dtype(d[col]):
                lines.append(f"Range of '{col}': {d[col].min().date()} to {d[col].max().date()}")
            elif pd.api.types.is_string_dtype(d[col]) and d[col].nunique() <= 80:
                lines.append(f"Allowed values of '{col}': {list(d[col].value_counts().index)}")
        lines.append("Sample rows:")
        lines.append(d.head(n).to_string(max_colwidth=30))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ---------- Safety check (demo-level guardrail, not a true sandbox) ----------
ALLOWED_IMPORTS = {"pandas", "numpy"}
BANNED_CALLS = {"open", "exec", "eval", "compile", "__import__", "input",
                "globals", "locals", "getattr", "setattr", "delattr"}
BANNED_ATTRS = {"to_csv", "to_excel", "to_pickle", "to_parquet", "to_sql", "to_json"}


def check_code(code):
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise ValueError(f"Import not allowed: {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                raise ValueError(f"Import not allowed: {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                raise ValueError(f"Call not allowed: {node.func.id}")
        elif isinstance(node, ast.Attribute):
            if (node.attr.startswith("__") or node.attr.startswith("read_")
                    or node.attr in BANNED_ATTRS):
                raise ValueError(f"Attribute not allowed: {node.attr}")


# ---------- Execution ----------
def run_code(code, dfs):
    check_code(code)
    first = next(iter(dfs.values()))
    env = {"pd": pd, "np": np, "dfs": dfs, "df": first,
           "spend": first[~first["category"].isin(NON_SPEND)].copy(),
           "result": None}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(code, env)
    res = env.get("result")
    if res is None:
        res = buf.getvalue() or None
    if res is None:
        raise ValueError("Code did not set a variable named `result`.")
    if isinstance(res, (pd.DataFrame, pd.Series)):
        res = res.head(50).to_string()
    return str(res)


def extract_code(reply):
    m = re.search(FENCE + r"(?:python)?\s*(.*?)" + FENCE, reply, re.S)
    return (m.group(1) if m else reply).strip()


# ---------- Agent loop ----------

DATA_NOTES = f"""About this data (a bank account statement, amounts in INR, covering several months):
- Two DataFrames are ready to use, with the same columns:
  * `df` = every withdrawal. Use it for "withdrawn", "transactions", "money out", and for questions about the EMI or INVESTMENT categories.
  * `spend` = `df` without the non-spending categories {NON_SPEND}. Use it for every question about "spending", "spent", "expenses" or "cost".
- Each row is one withdrawal. `amount` is the amount withdrawn. `name` is the person who made it.
- `category` is always UPPERCASE. 'HDFC CC' and 'ICICI CC' are credit card bill payments and count as spending (card purchases do not appear separately in this statement). {NON_SPEND} are loan repayments and money moved into investments, so they are not spending.
- `month` is a text label like '2026-03'. 'This month', 'last month' and 'latest' are relative to the newest date in the data (df['date'].max()), not today's date.
- Match category values exactly as listed in the schema."""

SYSTEM = f"""You are a careful data analyst. Write Python (pandas) code that answers the user's question.
Rules:
- Data is already loaded: `dfs` (dict of sheet name -> DataFrame), `df` and `spend` (see the notes below). Never read files.
- Only import pandas and numpy.
- Put the final answer in a variable named `result`.
- Use only columns that exist in the schema below.
- Questions about spending / spent / expenses / cost: use `spend`. Questions about withdrawals, transactions, or the EMI and INVESTMENT categories: use `df`.
- For "which / top / highest / lowest" questions: first filter, then groupby(...)["amount"].sum(), then use idxmax(), idxmin() or sort_values().
- For "average per month" questions: group by `month` and sum first, then take .mean() of the monthly totals.
- Combine conditions with & and | (each in parentheses), never with 'and' / 'or'. For months, prefer the `month` column; otherwise use df["date"].dt.year and df["date"].dt.month, or compare with a string like "2026-09-10".
- Reply with ONLY one code block that starts with {FENCE}python and ends with {FENCE}.

{DATA_NOTES}

Example question: Total amount by category?
Example reply:
{FENCE}python
result = df.groupby("category")["amount"].sum().sort_values(ascending=False)
{FENCE}

Example question: What is the total spending?
Example reply:
{FENCE}python
# spending questions use `spend`
result = spend["amount"].sum()
{FENCE}

Example question: Which person spent the most?
Example reply:
{FENCE}python
# filter first (spend already is), then group, sum, and pick the largest
result = spend.groupby("name")["amount"].sum().idxmax()
{FENCE}

Example question: How many FOOD transactions did Person_B make after 10 September 2026?
Example reply:
{FENCE}python
# combine conditions with & and put each condition in parentheses
result = len(df[(df["category"] == "FOOD") & (df["name"] == "Person_B") & (df["date"] > "2026-09-10")])
{FENCE}

Example question: What was the total spending in each month?
Example reply:
{FENCE}python
result = spend.groupby("month")["amount"].sum()
{FENCE}

Example question: What is the average monthly investment amount?
Example reply:
{FENCE}python
# sum within each month first, then average the monthly totals
monthly = df[df["category"] == "INVESTMENT"].groupby("month")["amount"].sum()
result = monthly.mean()
{FENCE}
"""


def repair_hint(e):
    msg = str(e)
    if "truth value of a Series is ambiguous" in msg:
        return ("Do not use 'and', 'or', 'not' or 'if' on a column. Combine conditions "
                "with & and | and put each condition in parentheses, e.g. "
                "df[(df['a'] > 1) & (df['b'] < 5)]. For dates use df['date'].dt.year "
                "and df['date'].dt.month.")
    if "has no attribute" in msg:
        return ("Check what type the object is: a single number cannot be grouped "
                "or sorted. Filter and group the DataFrame first.")
    if type(e).__name__ == "KeyError":
        return "Use only the column names listed in the schema, exactly as written."
    return ""


def ask(question, dfs, summarise=True):
    messages = [
        {"role": "system", "content": SYSTEM + "\n" + describe_schema(dfs)},
        {"role": "user", "content": question},
    ]
    code, out = "", None
    for attempt in range(1, MAX_RETRIES + 1):
        reply = llm(messages, temperature=0 if attempt == 1 else 0.3)
        code = extract_code(reply)
        try:
            out = run_code(code, dfs)
            break
        except Exception as e:
            print(f"  [attempt {attempt} failed: {type(e).__name__}: {e}]")
            print("  --- code that failed ---\n" + code + "\n  ------")
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": f"That code failed with "
                 f"{type(e).__name__}: {e}. {repair_hint(e)} "
                 f"Return the full corrected code block."},
            ]

    if out is None:
        return "I couldn't produce working code for that question.", code, None
    if not summarise:
        return "", code, out
    summary = llm([
        {"role": "system", "content": "Summarise the result for a business user in 2-4 sentences."
         "Amounts are in Indian rupees. Use ONLY the numbers in the result; do not invent figures."},
        {"role": "user", "content": f"Question: {question}\nCode:\n{code}\nResult:\n{out}"},
    ])
    return summary, code, out


if __name__ == "__main__":
    dfs = load_data(sys.argv[1])
    print("Loaded sheets:", list(dfs))
    while True:
        q = input("\nQuestion (or 'quit'): ").strip()
        if q.lower() in {"quit", "exit"}:
            break
        answer, code, out = ask(q, dfs)
        print("\n--- Code ---\n" + code + "\n--- Raw result ---\n" + str(out)
              + "\n--- Answer ---\n" + answer)