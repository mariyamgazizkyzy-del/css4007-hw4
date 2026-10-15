"""Fill the TODO places in SUBMISSION.md from outputs/*.json.
Usage: python patch_submission.py <USD per 1M input tokens> <USD per 1M output tokens>
Run it ONCE on the SUBMISSION.md that still has the TODOs."""
import json
import re
import sys
from pathlib import Path

pin, pout = float(sys.argv[1]), float(sys.argv[2])
TOOL_TOKENS = 485          # measured by extras.py (usage.prompt_tokens with tools minus without)

def summ(run, s):
    return json.loads(Path(f"outputs/run{run}_{s}.json").read_text(encoding="utf-8"))["summary"]

def cost(d):
    return (d["input_tokens"] * pin + d["output_tokens"] * pout) / 1e6

p = Path("SUBMISSION.md")
t = p.read_text(encoding="utf-8")
if "TODO" not in t:
    sys.exit("No TODO left in SUBMISSION.md: nothing to do.")

# 1. cost column (rows in the order run1 S1,S2,S3, run2 S1,S2,S3)
order = [(1, "S1"), (1, "S2"), (1, "S3"), (2, "S1"), (2, "S2"), (2, "S3")]
lines = t.split("\n")
k = 0
for i, line in enumerate(lines):
    if line.startswith("| ") and line.endswith("| TODO |") and k < 6:
        run, s = order[k]
        lines[i] = line[:-len("TODO |")] + f"{cost(summ(run, s)):.4f} |"
        k += 1
    if line.startswith("**Per question (run 1):**"):
        lines.insert(i, f"Prices used for the cost column: ${pin} per 1M input tokens and ${pout} per 1M output tokens.\n")
        break
t = "\n".join(lines)
assert k == 6, "expected 6 table rows with TODO"

r1 = cost(summ(1, "S2")) / cost(summ(1, "S1"))
r2 = cost(summ(2, "S2")) / cost(summ(2, "S1"))

# 2. final questions 3, 4, 5
t = t.replace("3. TODO: the two tool definitions add **TODO tokens**", f"3. The two tool definitions add **{TOOL_TOKENS} tokens**")
t = t.replace("The cost ratio S2/S1 was TODO× (from `cost.py`)",
              f"The cost ratio S2/S1 was {r1:.2f}× in run 1 and {r2:.2f}× in run 2 (from `cost.py`, at ${pin} per 1M input and ${pout} per 1M output tokens)")
t = re.sub(r"^5\. TODO.*$",
           "5. No single question: many questions tied at the maximum of **4 rounds** in both runs (for example Q-01, Q-03, Q-04, Q-07 and Q-09 in run 1), and no question needed more (`extras.py`). The model asks all the lookups of one step in a single round (parallel tool calls), then the calculations, then the last combination, and then it answers, which makes 4 API calls. Q-20 had the most tool calls (10 in run 1) but still only 4 rounds, because its calls were sent in parallel.",
           t, flags=re.M)

# 3. B3 round-limit sentence: add what was observed
t = t.replace("The hardest question (Q-20) needed 10 tool calls in run 1, so 12 leaves room for a model that calls tools one at a time, but it still stops a model that loops forever and wastes tokens.",
              "In my runs no question needed more than 4 rounds (Q-20 made 10 tool calls but in only 4 rounds, because the model sends the calls of one step in parallel), so 12 is three times what I saw. It leaves room for a model that calls tools one at a time, but it still stops a model that loops forever and wastes tokens.")
p.write_text(t, encoding="utf-8")
print("done; TODO left:", t.count("TODO"))
