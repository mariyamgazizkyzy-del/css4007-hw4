"""Print the B4 table (with cost) from outputs/run*_S*.json.
Usage: python cost.py <USD per 1M input tokens> <USD per 1M output tokens>"""
import json
import sys
from pathlib import Path

pin, pout = float(sys.argv[1]), float(sys.argv[2])
names = {"S1": "S1 direct", "S2": "S2 think and vote (k = 5)", "S3": "S3 tools"}
print("| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |")
print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
costs = {}
for run in (1, 2):
    for s in ("S1", "S2", "S3"):
        d = json.loads(Path(f"outputs/run{run}_{s}.json").read_text(encoding="utf-8"))["summary"]
        c = (d["input_tokens"] * pin + d["output_tokens"] * pout) / 1e6
        costs[(run, s)] = c
        print(f"| {run} | {names[s]} | {d['correct']} | {d['unanswered']} | {d['input_tokens']} | "
              f"{d['output_tokens']} | {d['median_seconds']} | {d['total_seconds']} | {c:.4f} |")
for run in (1, 2):
    print(f"run {run}: S2 cost / S1 cost = {costs[(run, 'S2')] / costs[(run, 'S1')]:.2f}x ; "
          f"S3 cost / S1 cost = {costs[(run, 'S3')] / costs[(run, 'S1')]:.2f}x")
