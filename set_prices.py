"""Re-write the cost column, the 'Prices used' line and the S2/S1 cost ratio in SUBMISSION.md.
Usage: python set_prices.py <USD per 1M input tokens> <USD per 1M output tokens>
Can be run many times (it replaces the old prices)."""
import json
import re
import sys
from pathlib import Path

pin, pout = float(sys.argv[1]), float(sys.argv[2])

def summ(run, s):
    return json.loads(Path(f"outputs/run{run}_{s}.json").read_text(encoding="utf-8"))["summary"]

def cost(d):
    return (d["input_tokens"] * pin + d["output_tokens"] * pout) / 1e6

p = Path("SUBMISSION.md")
t = p.read_text(encoding="utf-8")
names = {"S1": "S1 direct", "S2": "S2 think and vote (k = 5)", "S3": "S3 tools"}
for run in (1, 2):
    for s in ("S1", "S2", "S3"):
        pat = re.compile(rf"^(\| {run} \| {re.escape(names[s])} \|.*\| )[\d.]+( \|)$", re.M)
        t, n = pat.subn(lambda m: f"{m.group(1)}{cost(summ(run, s)):.4f}{m.group(2)}", t)
        assert n == 1, f"row run {run} {s} not found"
r1 = cost(summ(1, "S2")) / cost(summ(1, "S1"))
r2 = cost(summ(2, "S2")) / cost(summ(2, "S1"))
t, n1 = re.subn(r"^Prices used for the cost column:.*$",
                f"Prices used for the cost column: ${pin} per 1M input tokens and ${pout} per 1M output tokens.", t, flags=re.M)
t, n2 = re.subn(r"The cost ratio S2/S1 was [\d.]+× in run 1 and [\d.]+× in run 2 \(from `cost.py`, at \$[\d.]+ per 1M input and \$[\d.]+ per 1M output tokens\)",
                f"The cost ratio S2/S1 was {r1:.2f}× in run 1 and {r2:.2f}× in run 2 (from `cost.py`, at ${pin} per 1M input and ${pout} per 1M output tokens)", t)
assert n1 == 1 and n2 == 1, "price line or ratio sentence not found"
p.write_text(t, encoding="utf-8")
print(f"done: prices {pin} / {pout}; S2/S1 = {r1:.2f}x and {r2:.2f}x")
