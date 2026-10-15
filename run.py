"""Run strategies on the 20 questions and save results to outputs/.

Examples:
  python run.py --run 1 --strategy S3 --questions Q-09        # test on one question first
  python run.py --run 1 --strategy all --price-in 1.0 --price-out 4.0   # $ per 1M tokens (from the price page)
  python run.py --run 1 --strategy S3 --vague --questions Q-01,Q-09,Q-13,Q-18,Q-20   # C1
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

import strategies as S

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"


def get_client():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(ROOT / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is missing: put it in .env (never commit .env).")
    return OpenAI()


def run_strategy(client, name, questions, run_no, vague, price_in, price_out):
    fn = {"S1": S.s1_direct, "S2": S.s2_vote, "S3": lambda c, q: S.s3_tools(c, q, vague=vague)}[name]
    tag = f"run{run_no}_{name}{'_vague' if vague else ''}"
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    records = []
    for q in questions:
        res = fn(client, q)
        parsed = S.parse_answer(res["text"])
        ok = S.is_correct(parsed, q)
        rec = {"id": q["id"], "correct": ok, "unanswered": res["unanswered"], "predicted": parsed,
               "expected": [q["answer"], q["value"]], "seconds": round(res["seconds"], 3),
               "input_tokens": sum(c["input"] for c in res["calls"]),
               "output_tokens": sum(c["output"] for c in res["calls"]),
               "n_calls": len(res["calls"]), "rounds": res.get("rounds"), "votes": res.get("votes"),
               "final_text": res["text"]}
        records.append(rec)
        if name == "S3":
            (OUT / "logs" / f"{tag}_{q['id']}.json").write_text(
                json.dumps({"question": q["question"], "tool_calls": res["log"], "api_calls": res["calls"],
                            "final_text": res["text"], "note": res.get("note")}, indent=2, ensure_ascii=False),
                encoding="utf-8")
        print(f"{tag} {q['id']}: {'OK ' if ok else 'BAD'} predicted={parsed} expected={rec['expected']} "
              f"{rec['seconds']}s in={rec['input_tokens']} out={rec['output_tokens']}")
        save(tag, records, run_no, name, vague, price_in, price_out)     # save after every question
    return tag, records


def summarize(records, price_in, price_out):
    tin = sum(r["input_tokens"] for r in records)
    tout = sum(r["output_tokens"] for r in records)
    secs = [r["seconds"] for r in records]
    cost = (tin * price_in + tout * price_out) / 1e6 if price_in is not None else None
    return {"correct": sum(r["correct"] for r in records), "n": len(records),
            "unanswered": sum(r["unanswered"] for r in records), "input_tokens": tin, "output_tokens": tout,
            "median_seconds": round(statistics.median(secs), 2), "total_seconds": round(sum(secs), 1),
            "cost_usd": None if cost is None else round(cost, 4)}


def save(tag, records, run_no, name, vague, price_in, price_out):
    meta = {"model": S.MODEL, "strategy": name, "run": run_no, "vague_lookup": vague, "k": S.K, "reasoning_effort": S.REASONING_EFFORT,
            "s2_temperature": S.S2_TEMPERATURE, "temperature_accepted": S.STATE["temp_ok"],
            "max_rounds": S.MAX_ROUNDS, "price_in_per_1m": price_in, "price_out_per_1m": price_out,
            "saved_at": datetime.now().isoformat(timespec="seconds")}
    (OUT / f"{tag}.json").write_text(
        json.dumps({"meta": meta, "summary": summarize(records, price_in, price_out), "records": records},
                   indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, required=True, help="run number: 1 or 2")
    ap.add_argument("--strategy", default="all", choices=["S1", "S2", "S3", "all"])
    ap.add_argument("--questions", default="all", help="e.g. Q-09,Q-01 (default: all 20)")
    ap.add_argument("--vague", action="store_true", help="S3 with the one-line vague lookup description (C1)")
    ap.add_argument("--price-in", type=float, default=None, help="USD per 1M input tokens")
    ap.add_argument("--price-out", type=float, default=None, help="USD per 1M output tokens")
    a = ap.parse_args()

    qs = json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))
    if a.questions != "all":
        want = set(a.questions.split(","))
        qs = [q for q in qs if q["id"] in want]
    names = ["S1", "S2", "S3"] if a.strategy == "all" else [a.strategy]
    client = get_client()

    rows = []
    for n in names:
        tag, recs = run_strategy(client, n, qs, a.run, a.vague and n == "S3", a.price_in, a.price_out)
        s = summarize(recs, a.price_in, a.price_out)
        rows.append((tag, s))
    print("\n| Run | Strategy | Correct | Unanswered | Input tokens | Output tokens | Median s | Total s | Cost $ |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for tag, s in rows:
        print(f"| {tag} | | {s['correct']}/{s['n']} | {s['unanswered']} | {s['input_tokens']} | "
              f"{s['output_tokens']} | {s['median_seconds']} | {s['total_seconds']} | {s['cost_usd']} |")
    if not S.STATE["temp_ok"]:
        print("\nNOTE: the model rejected `temperature`; S2 ran without it (say this in SUBMISSION.md).")


if __name__ == "__main__":
    main()
