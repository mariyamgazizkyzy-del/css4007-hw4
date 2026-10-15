"""Small measurements for the final questions. Uses 2 tiny API calls (almost free)."""
import json
from pathlib import Path

for run in (1, 2):
    d = json.loads(Path(f"outputs/run{run}_S3.json").read_text(encoding="utf-8"))
    top = sorted(d["records"], key=lambda r: -(r["rounds"] or 0))[:5]
    print(f"run {run} S3, most rounds (id, rounds, api calls):", [(r["id"], r["rounds"], r["n_calls"]) for r in top])
print("S2 temperature accepted by the API:",
      json.loads(Path("outputs/run1_S2.json").read_text(encoding="utf-8"))["meta"]["temperature_accepted"])

from run import get_client
from strategies import chat
from tools import TOOL_DEFINITIONS
client = get_client()
msgs = [{"role": "user", "content": "Say hi."}]
_, _, u0 = chat(client, msgs)
_, _, u1 = chat(client, msgs, tools=TOOL_DEFINITIONS)
print("input tokens without tools:", u0["input"], "| with both tools:", u1["input"],
      "| the two tool definitions add:", u1["input"] - u0["input"])
