"""HW4 strategies: S1 direct, S2 think-and-vote (k samples), S3 tool loop."""
import copy
import json
import re
import time
from collections import Counter

from tools import TOOL_DEFINITIONS, run_tool

# ---- settings kept FIXED for every strategy (write them in SUBMISSION.md) ----
MODEL = "gpt-5.6-luna"
REASONING_EFFORT = "none"  # fixed for ALL strategies: Chat Completions rejects tools with reasoning on
K = 5                 # S2 samples
S2_TEMPERATURE = 1.0  # S2 only; dropped automatically if the model refuses it
MAX_ROUNDS = 12       # S3: model <-> tools round trips before "unanswered"
STATE = {"temp_ok": True}   # set to False if the model rejects `temperature`

FORMAT_RULE = (
    "End your reply with exactly one final line in this format:\n"
    "ANSWER: <district name or yes/no> | <number>\n"
    "The number is the amount the question asks for, as a plain number: no units, no thousands "
    "separators. Do not round early; if the number is not whole, give 4 decimal places."
)
SYSTEM = ("You answer questions about the Nine Rivers Region, a made-up place. "
          "Any fact you use must come from the provided sources, not from memory. " + FORMAT_RULE)

_corpus_text = None


def corpus_text():
    global _corpus_text
    if _corpus_text is None:
        from pathlib import Path
        rows = [json.loads(l) for l in (Path(__file__).parent / "data" / "corpus.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        _corpus_text = "\n\n".join(f"[{r['id']}] {r['title']}\n{r['text']}" for r in rows)
    return _corpus_text


# ------------------------------------------------------------------ API call
def chat(client, messages, tools=None, temperature=None):
    """One Chat Completions call with retries. Returns (response, seconds, usage dict)."""
    kwargs = {"model": MODEL, "messages": messages, "reasoning_effort": REASONING_EFFORT}
    if tools:
        kwargs["tools"] = tools
    if temperature is not None and STATE["temp_ok"]:
        kwargs["temperature"] = temperature
    for attempt in range(5):
        try:
            t0 = time.perf_counter()
            r = client.chat.completions.create(**kwargs)
            dt = time.perf_counter() - t0
            u = r.usage
            return r, dt, {"input": u.prompt_tokens, "output": u.completion_tokens, "seconds": round(dt, 3)}
        except Exception as e:
            name = type(e).__name__
            if name == "BadRequestError" and "temperature" in str(e) and "temperature" in kwargs:
                STATE["temp_ok"] = False
                kwargs.pop("temperature")
                continue
            if name in ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"):
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("API call failed after 5 attempts")


# ------------------------------------------------------- answer parse + score
ANSWER_RE = re.compile(r"ANSWER:\s*(.+?)\s*\|\s*(-?[\d][\d,]*\.?\d*)", re.IGNORECASE)


def parse_answer(text):
    """Return (name, number) from the LAST 'ANSWER:' line, or None."""
    if not text:
        return None
    found = ANSWER_RE.findall(text)
    if not found:
        return None
    name, num = found[-1]
    try:
        return name.strip().strip("*`").lower(), float(num.replace(",", ""))
    except ValueError:
        return None


def is_correct(parsed, q):
    """RULE: name equal (case-insensitive) AND round(number, decimals) within 1 unit of the last digit of `value`."""
    if parsed is None:
        return False
    name, num = parsed
    step = 10 ** -q["decimals"]
    return name == q["answer"].lower() and abs(round(num, q["decimals"]) - q["value"]) <= step * 1.0001


# ---------------------------------------------------------------- strategies
def s1_direct(client, q):
    user = (f"Documents:\n\n{corpus_text()}\n\nQuestion: {q['question']}\n\n"
            "Give the final answer directly, without showing your reasoning.")
    r, dt, usage = chat(client, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
    text = r.choices[0].message.content
    return {"text": text, "calls": [usage], "seconds": dt, "unanswered": parse_answer(text) is None, "log": []}


def s2_vote(client, q, k=K):
    user = (f"Documents:\n\n{corpus_text()}\n\nQuestion: {q['question']}\n\n"
            "Think step by step, then give the final answer.")
    samples, calls, total = [], [], 0.0
    for _ in range(k):
        r, dt, usage = chat(client, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                            temperature=S2_TEMPERATURE)
        text = r.choices[0].message.content
        samples.append({"text": text, "parsed": parse_answer(text)})
        calls.append(usage)
        total += dt
    # vote on (name, number to 3 significant figures)
    keys = [(s["parsed"][0], float(f"{s['parsed'][1]:.3g}")) for s in samples if s["parsed"]]
    if not keys:
        return {"text": None, "calls": calls, "seconds": total, "unanswered": True, "log": [], "samples": samples}
    winner, votes = Counter(keys).most_common(1)[0]
    text = next(s["text"] for s in samples if s["parsed"] and
                (s["parsed"][0], float(f"{s['parsed'][1]:.3g}")) == winner)
    return {"text": text, "calls": calls, "seconds": total, "unanswered": False, "log": [],
            "votes": f"{votes}/{k}", "samples": [{"parsed": s["parsed"]} for s in samples]}


def s3_tools(client, q, vague=False, max_rounds=MAX_ROUNDS):
    tools = copy.deepcopy(TOOL_DEFINITIONS)
    if vague:
        tools[0]["function"]["description"] = "Looks things up."
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Question: {q['question']}\n\nUse the tools lookup (facts) "
                                            "and calculate (all arithmetic). You have no documents."}]
    calls, log, total = [], [], 0.0
    for rnd in range(1, max_rounds + 1):
        r, dt, usage = chat(client, messages, tools=tools)
        calls.append(usage)
        total += dt
        msg = r.choices[0].message
        if not msg.tool_calls:                          # final answer
            text = msg.content
            return {"text": text, "calls": calls, "seconds": total, "rounds": rnd,
                    "unanswered": parse_answer(text) is None, "log": log}
        messages.append(msg.model_dump(exclude_none=True))   # the model's message, unchanged
        for tc in msg.tool_calls:                       # answer EVERY tool_call_id
            t0 = time.perf_counter()
            result = run_tool(tc.function.name, tc.function.arguments)
            tdt = time.perf_counter() - t0
            total += tdt
            log.append({"round": rnd, "id": tc.id, "tool": tc.function.name,
                        "arguments": tc.function.arguments, "result": result, "seconds": round(tdt, 5)})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    return {"text": None, "calls": calls, "seconds": total, "rounds": max_rounds,
            "unanswered": True, "log": log, "note": "round limit reached"}
