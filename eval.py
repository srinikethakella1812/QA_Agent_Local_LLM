import re

from agent import ask, load_data, NON_SPEND

dfs = load_data("statement.xlsx")
d = dfs["Sheet1"]
spend = d[~d["category"].isin(NON_SPEND)]

TESTS = [
    ("How many transactions are there?",
     len(d)),

    ("What is the total amount withdrawn?",
     d["amount"].sum()),

    ("What is the total spending?",
     spend["amount"].sum()),

    ("How much was spent on FOOD in total?",
     d.loc[d["category"] == "FOOD", "amount"].sum()),

    ("How many FOOD transactions are there?",
     (d["category"] == "FOOD").sum()),

    ("Which category has the highest spending?",
     spend.groupby("category")["amount"].sum().idxmax()),

    ("What is the largest single transaction amount?",
     d["amount"].max()),

    ("What was the total withdrawn in September 2026?",
     d.loc[d["date"] >= "2026-09-01", "amount"].sum()),

    ("What is the average FOOD transaction amount?",
     d.loc[d["category"] == "FOOD", "amount"].mean()),

    ("Which category has the lowest spending?",
     spend.groupby("category")["amount"].sum().idxmin()),

    ("Which person made the most transactions?",
     d["name"].value_counts().idxmax()),

    ("What is the total amount for AUTO and FOOD together?",
     d.loc[d["category"].isin(["AUTO", "FOOD"]), "amount"].sum()),

    ("How much was withdrawn in August 2026?",
     d.loc[d["month"] == "2026-08", "amount"].sum()),

    ("How many transactions were made between 1 September and 10 September 2026?",
     ((d["date"] >= "2026-09-01") & (d["date"] <= "2026-09-10")).sum()),

    ("How much did Person_B spend on FOOD?",
     d.loc[(d["name"] == "Person_B") & (d["category"] == "FOOD"), "amount"].sum()),

    ("What was the total spending in March 2026?",
     spend.loc[spend["month"] == "2026-03", "amount"].sum()),

    ("Which month (in YYYY-MM format) had the highest spending?",
     spend.groupby("month")["amount"].sum().idxmax()),

    ("What is the total spending from January to June 2026?",
     spend.loc[(spend["date"] >= "2026-01-01") & (spend["date"] <= "2026-06-30"), "amount"].sum()),

    ("What is the average monthly spending?",
     spend.groupby("month")["amount"].sum().mean()),

    ("What was the total FOOD spending in May 2026?",
     d.loc[(d["category"] == "FOOD") & (d["month"] == "2026-05"), "amount"].sum()),
     
    ("How much did Person_B spend in total?",
     spend.loc[spend["name"] == "Person_B", "amount"].sum()),

    ("What is the average monthly FOOD spending?",
     d[d["category"] == "FOOD"].groupby("month")["amount"].sum().mean()),

    ("What is the total amount in the INVESTMENT category?",
     d.loc[d["category"] == "INVESTMENT", "amount"].sum()),

    ("How much was spent in total in June 2026?",
     spend.loc[spend["month"] == "2026-06", "amount"].sum()),
]


def passed(out, expected):
    if out is None:
        return False
    if isinstance(expected, str):
        return expected.lower() in out.lower()
    nums = [float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*\.?\d*", out)]
    return any(abs(n - expected) <= max(0.01 * abs(expected), 0.01) for n in nums)


score = 0
for q, expected in TESTS:
    _, code, out = ask(q, dfs, summarise=False)
    ok = passed(out, expected)
    score += ok
    print(f"{'PASS' if ok else 'FAIL'} | {q}\n       expected={expected}  got={out}\n")

print(f"Score: {score}/{len(TESTS)}")