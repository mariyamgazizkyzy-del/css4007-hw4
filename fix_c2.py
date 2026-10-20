"""Replace the S2 paragraph in C2 with the version that quotes the real log, and fix the AI-assistance file list."""
import re
from pathlib import Path

p = Path("SUBMISSION.md")
t = p.read_text(encoding="utf-8")

new = """**S2 — Q-17 (both runs): wrong.** Log lines: run 1 `predicted=('harrowfield', 888.9228)`, run 2 `predicted=('harrowfield', 887.8973)`, expected 884 (S3 got 884.4572). The reasoning saved in `outputs/run1_S2.json` (`final_text` of Q-17) shows what happened:

```text
Harrowfield water cost per resident = 7,146,000 × 142.35 ÷ 90,212 = 11,278.3973 tenge
Ossbridge water cost per resident = 3,862,000 × 142.35 ÷ 52,904 = 10,389.4745 tenge
Difference = 888.9228 tenge per resident
```

The set-up is right (correct water use, populations, tariff and formula), but the arithmetic is wrong. I checked it with Python: 7,146,000 × 142.35 ÷ 90,212 = 11,276.03 (not 11,278.40) and 3,862,000 × 142.35 ÷ 52,904 = 10,391.57 (not 10,389.47), so the true difference is 884.46, the same as S3. The model wrote numbers with four decimals that look exact but are wrong already in the units digit: it did a big multiplication and a long division in text, with no calculator. (My first guess was that rounding of intermediate values caused it; the log shows that the formula and the inputs were fine and the digits of the division were not.) Voting over 5 samples helps when the wrong samples are different and the right value is the most common one; here the answers of the two runs are both a few tenge too high, and Q-05 (14327.583 and 14332.8 against 14235) and Q-20 (2998.16 and 2998.67 against 2993) also have wrong answers that are close to each other in both runs (I did not read the reasoning of these two). So voting fixed some questions (Q-12 and Q-18 were wrong in run 1 and right in run 2) but not Q-05, Q-17, Q-20."""

pat = re.compile(r"\*\*S2 — Q-17 \(both runs\): wrong\.\*\*.*?(?=\n\n\*\*S3 — Q-18)", re.S)
t, n = pat.subn(lambda m: new, t)
assert n == 1, "S2 paragraph not found"

old_list = "(`tools.py`, `tests/`, `strategies.py`, `run.py`, `cost.py`, `extras.py`)"
new_list = "(`tools.py`, `tests/`, `strategies.py`, `run.py`, `cost.py`, `extras.py`, `patch_submission.py`, `set_prices.py`)"
t = t.replace(old_list, new_list)
p.write_text(t, encoding="utf-8")
print("done")
