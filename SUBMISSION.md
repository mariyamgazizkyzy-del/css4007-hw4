# HW4 — submission

**AI assistance:** I used Claude (Anthropic) to help plan Part A (steps, tool definitions, the Q-09 walkthrough), to write and review the code (`tools.py`, `tests/`, `strategies.py`, `run.py`, `cost.py`, `extras.py`, `patch_submission.py`, `set_prices.py`) and to draft the explanations in Part C. I ran all the code on my own computer with my own API key. Every number below comes from my own runs, saved in `outputs/`.

---

## Part A — Plan on paper (Easy)

> Commit this whole part before any `.py` file exists.

### A1 — The steps

| # | Step | What goes in (types) | What comes out (types) | When it goes wrong | Tool, loop, or model? |
|---|---|---|---|---|---|
| 1 | **Understand** the question | `question: str` | a plan: districts `list[str]`, metric(s), operation (difference / ratio / growth / compare) | district not named or metric unclear → model answers `ANSWER: unknown \| 0` rather than guess | model |
| 2 | **Fetch one fact** | `district: str`, `field: str` | `{district, field, value: float\|int, unit: str, source: str}` | unknown district / field → `{"error": ...}` with suggestions; archived-only data → error, never used | tool `lookup` |
| 3 | **Calculate** | `expression: str` | `{"expression": str, "result": float}` | bad syntax, forbidden node, division by zero, exponent too big, result too big → `{"error": ...}` | tool `calculate` |
| 4 | **Dispatch** (run tools safely) | `tool_calls: list` (each `id`, `name`, `arguments: str` JSON) | one `role="tool"` message per `id` (`content: str` JSON) | invalid JSON / unknown tool name / missing argument → error JSON for that `id`; round limit hit → question marked *unanswered* | loop (my code) |
| 5 | **Compare and answer** | the numbers from steps 2–3 | final line `ANSWER: <name or yes/no> \| <number>` | numbers missing → say so, no invented answer | model |

**How the steps connect:**

```text
question ──► [1 Understand] ──► for each fact needed:
                                  [4 Dispatch] ──► [2 lookup] ──► value + source ─┐
                                                                                   ▼
                                  [4 Dispatch] ──► [3 calculate] ◄── expression built from the values
                                                         │
                                                         ▼
                                                  [5 Compare and answer] ──► ANSWER: name | number
```

Steps 2 and 3 are independent of each other (lookup knows nothing about arithmetic, calculate knows nothing about documents). Step 4 is the only thing that connects the model to them.

**What I am assuming:**

- Only the **2025 profiles** (NR-01 … NR-12) are used. **NR-13 and NR-14 are ARCHIVED (2019)** and are never returned by `lookup`.
- **NR-16 overrides NR-05**: Brightwater area = **921.4 km²** (not 912.4). `lookup` applies this itself and says so in `source`.
- **Water**: Lindenmoor (NR-08) gives cubic metres, all others give megalitres. `lookup` returns water use in **cubic metres for every district** (megalitres × 1000) and states the conversion in `source`.
- Population = 2025 census unless the field name says 2020. Budget = 2025, million tenge. Schools/pupils = 2025/26.
- Tariff 2025 = 142.35 tenge/m³ (NR-15), not the 2024 one (131.80). The model asks for it with `field="water_tariff_tenge_per_m3"` (district not needed → `district="Region"`).
- **Rounding only at the very end**, in step 5. `calculate` never rounds; the model reports the number with enough decimals (the unit in the question tells how many).
- District names must match **exactly** (case-insensitive). No automatic guessing: Ossbridge ≠ Ossford.
- Most sensitive assumption: **`lookup` applies the archive/correction rules itself**, so the model never sees the wrong numbers. If I got this wrong, every question with Brightwater, Tarnvale or Kelmarsh fails.

### A2 — The two tools

#### `lookup`

```json
{
  "type": "function",
  "function": {
    "name": "lookup",
    "description": "Get ONE current (2025) fact about ONE district of the Nine Rivers Region, or the regional water tariff. Returns a single number, its unit and the source document. Archived 2019 profiles are never used and corrections are already applied. Call it once per district per field. For the tariff use district='Region' and field='water_tariff_tenge_per_m3'. Fields: population_2025, population_2020, area_km2, founded_year, schools, pupils, budget_million_tenge, water_use_m3 (cubic metres per year, same unit for all districts), paved_road_km, water_tariff_tenge_per_m3. District must be spelled exactly, e.g. 'Ossbridge' and 'Ossford' are different districts.",
    "parameters": {
      "type": "object",
      "properties": {
        "district": {"type": "string", "description": "Exact district name, e.g. 'Millbrook', or 'Region' for the tariff"},
        "field": {"type": "string", "enum": ["population_2025","population_2020","area_km2","founded_year","schools","pupils","budget_million_tenge","water_use_m3","paved_road_km","water_tariff_tenge_per_m3"]}
      },
      "required": ["district", "field"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"district":"Millbrook","field":"population_2025","value":37203,"unit":"residents","source":"NR-11"}` |
| Brightwater area | `{"district":"Brightwater","field":"area_km2","value":921.4,"unit":"km2","source":"NR-05, corrected by NR-16"}` |
| Lindenmoor water | `{"value":2151400,"unit":"m3 per year","source":"NR-08 (given in m3)"}`; others: `"source":"NR-04 (1,739 ML x 1000)"` |
| unknown district | `{"error":"no district named Ossbrige; did you mean Ossbridge or Ossford?"}` |
| unknown field | `{"error":"unknown field 'popul'; valid fields: population_2025, ..."}` |
| archived only / not in 2025 profile | `{"error":"no 2025 value for <field>; archived 2019 profiles are not used"}` |
| missing / wrong-type argument | `{"error":"argument 'field' is required and must be a string"}` |

**Worst thing it could do with strange or dangerous input:** nothing harmful. It only reads a dict built from the corpus at start-up (no file path, no shell, no regex built from input), so a strange string gives an error. The worst case is a *wrong-looking but valid* answer (e.g. model picks `population_2020` by mistake); I limit the output to one short JSON object, so a huge input cannot make it return a huge output.

#### `calculate`

```json
{
  "type": "function",
  "function": {
    "name": "calculate",
    "description": "Evaluate ONE arithmetic expression and return the exact result. Use it for ALL arithmetic (divisions, differences, percentages, products) instead of computing in your head. Allowed: numbers, + - * / ** and parentheses, e.g. '44675 / 921.4' or '(37203 - 34590) / 34590 * 100'. Percentage = write the formula yourself, there is no % operator. No variables, no functions, no text.",
    "parameters": {
      "type": "object",
      "properties": {
        "expression": {"type": "string", "description": "Arithmetic expression, at most 200 characters"}
      },
      "required": ["expression"],
      "additionalProperties": false
    }
  }
}
```

| Case | What the tool returns |
|---|---|
| success | `{"expression":"44675 / 921.4","result":48.48599956587801}` |
| division by zero | `{"error":"division by zero"}` |
| forbidden syntax (names, calls, attributes, strings, `__import__`, `(1).__class__`) | `{"error":"not allowed: Call"}` (node type named; nothing executed) |
| syntax error | `{"error":"cannot parse expression"}` |
| too long (> 200 chars) | `{"error":"expression too long"}` |
| `9**9**9`, huge exponent (> 100) or \|result\| > 1e15 | `{"error":"number too large"}` |
| missing / non-string argument | `{"error":"argument 'expression' is required and must be a string"}` |

**Worst thing it could do with strange or dangerous input:** with `eval` the model (or text hidden in a document) could run any Python (delete files, read the API key). I parse with `ast.parse(mode="eval")` and walk the tree: only `Constant` (int/float), `BinOp` (+ - * / **), `UnaryOp` (+ -). Anything else is refused before it runs. Remaining risk: slow or huge arithmetic, which is stopped by the length limit, the exponent limit and the size limit. The model can still *misuse* it (wrong formula), and the tool cannot notice that.

### A3 — Q-09 by hand

Question: *Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?*
(NR-05 says area 912.4, but NR-16 corrects it to **921.4**.)

```json
[
  {"role": "user", "content": "Which district has the higher population density in 2025, Brightwater or Millbrook, and by how many residents per square kilometre?"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"population_2025\"}"}},
    {"id": "call_2", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Brightwater\", \"field\": \"area_km2\"}"}},
    {"id": "call_3", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"population_2025\"}"}},
    {"id": "call_4", "type": "function", "function": {"name": "lookup", "arguments": "{\"district\": \"Millbrook\", \"field\": \"area_km2\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_1", "content": "{\"district\":\"Brightwater\",\"field\":\"population_2025\",\"value\":44675,\"unit\":\"residents\",\"source\":\"NR-05\"}"},
  {"role": "tool", "tool_call_id": "call_2", "content": "{\"district\":\"Brightwater\",\"field\":\"area_km2\",\"value\":921.4,\"unit\":\"km2\",\"source\":\"NR-05, corrected by NR-16\"}"},
  {"role": "tool", "tool_call_id": "call_3", "content": "{\"district\":\"Millbrook\",\"field\":\"population_2025\",\"value\":37203,\"unit\":\"residents\",\"source\":\"NR-11\"}"},
  {"role": "tool", "tool_call_id": "call_4", "content": "{\"district\":\"Millbrook\",\"field\":\"area_km2\",\"value\":758.6,\"unit\":\"km2\",\"source\":\"NR-11\"}"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_5", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"44675 / 921.4\"}"}},
    {"id": "call_6", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"37203 / 758.6\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_5", "content": "{\"expression\":\"44675 / 921.4\",\"result\":48.48599956587801}"},
  {"role": "tool", "tool_call_id": "call_6", "content": "{\"expression\":\"37203 / 758.6\",\"result\":49.041655681518584}"},

  {"role": "assistant", "content": null, "tool_calls": [
    {"id": "call_7", "type": "function", "function": {"name": "calculate", "arguments": "{\"expression\": \"49.041655681518584 - 48.48599956587801\"}"}}
  ]},
  {"role": "tool", "tool_call_id": "call_7", "content": "{\"expression\":\"49.041655681518584 - 48.48599956587801\",\"result\":0.5556561156405735}"},

  {"role": "assistant", "content": "Brightwater: 44,675 / 921.4 = 48.49 residents/km2 (area from NR-05 corrected by NR-16). Millbrook: 37,203 / 758.6 = 49.04 residents/km2. Millbrook is denser by about 0.6 residents/km2.\nANSWER: Millbrook | 0.6"}
]
```

**My arithmetic:**

- Brightwater: 44,675 / 921.4 = 48.486 residents/km²
- Millbrook: 37,203 / 758.6 = 49.042 residents/km²
- Difference: 49.042 − 48.486 = 0.556 → **0.6** (1 decimal) → **Millbrook, 0.6**. Matches `questions.json`.
- Trap check: with the uncorrected area 912.4, Brightwater = 48.964 and the difference would be 0.077 → 0.1, which is wrong. So applying NR-16 is what makes the answer right.

### A4 — Why I split it this way

Another split: **one tool per calculation** (`density(a, b)`, `growth_pct(district)`, `budget_per_pupil(...)`, ...), with lookup hidden inside. I did not choose it because (1) there are many question types, so I would need ~10 tools and the model would have to pick the right one from a long list, (2) each new question type needs new code, while one generic `calculate` covers all 20 questions and new ones, (3) the model cannot see the inputs it used, so errors (wrong field, wrong year) are harder to find in the log. The price of my split is more rounds (more tokens), but each step is small and checkable.

---

## Part B — Build it and run it (Medium)

### What I changed from Part A while coding

- The two tool definitions are the same as in A2 (same names, descriptions, parameters).
- I added a small `run_tool(name, arguments)` function in `tools.py`. It is step 4 (Dispatch) from A1: it parses the `arguments` JSON string, checks that it is an object, and calls `lookup` or `calculate`; on bad input it returns an error JSON instead of crashing.
- I set `reasoning_effort="none"` for all three strategies. The API refused function tools with `gpt-5.6-luna` in Chat Completions when reasoning was on (error 400), so I fixed it to `"none"` everywhere to keep the comparison fair. In S2 the step-by-step thinking comes from the prompt.
- Water use from `lookup` is in m³ per year for every district (as planned in A1); the unit conversion is written in the `source` field.

### B2 — Tests

```text
============================== test session starts ===============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\Huawei\Downloads\css4007-hw4
plugins: anyio-4.15.1, platformdirs-4.12.2
collected 24 items

tests\test_tools.py ........................                                [100%]

=============================== 24 passed in 0.09s ===============================
```

### B3 — The loop

- Round limit, and why: **12 rounds** (`MAX_ROUNDS` in `strategies.py`). By hand (A3) Q-09 needs 3 tool rounds plus the final answer. In my runs no question needed more than 4 rounds (Q-20 made 10 tool calls but in only 4 rounds, because the model sends the calls of one step in parallel), so 12 is three times what I saw. It leaves room for a model that calls tools one at a time, but it still stops a model that loops forever and wastes tokens. If the limit is reached the question is marked unanswered. This never happened: S3 had 0 unanswered questions in run 1, run 2 and the vague test.
- Where the logs are: `outputs/logs/run<N>_S3_<question id>.json` (every tool call with its inputs, result and seconds, plus tokens and seconds of each API call). The totals and per-question results are in `outputs/run<N>_<strategy>.json`.
- Real Q-09 conversation compared with my A3 version, what is different (log: `outputs/logs/run1_S3_Q-09.json`):
  - **Same:** round 1 was four parallel `lookup` calls (Brightwater population and area, Millbrook population and area), with the corrected area 921.4 and source "NR-05, corrected by NR-16". Round 2 was two parallel `calculate` calls, `44675 / 921.4` and `37203 / 758.6`, with exactly my results (48.48599956587801 and 49.041655681518584). Total 7 tool calls and 4 API calls, like my A3.
  - **Different:** in round 3 the model did not subtract the two results I had pasted in A3. It sent one expression with the original numbers, `37203 / 758.6 - 44675 / 921.4`, and got the same result 0.5556561156405735. This is better than my version, because it does not copy long decimals by hand. The final line was `ANSWER: Millbrook | 0.5557`, with 4 decimals because my prompt asks for that, and my A3 line had `0.6`. The scoring rule rounds to 0.6, so it is correct.

### B4 — Three strategies

**What I kept the same:**

- Model `gpt-5.6-luna`, Chat Completions API, `reasoning_effort="none"` in all strategies.
- The same system prompt and the same final line `ANSWER: <name or yes/no> | <number>` in all strategies. The number is not rounded early (4 decimals if it is not whole).
- The same 20 questions from `data/questions.json`, in the same order. Correct answers are never put in a prompt.
- S1 and S2 get all 17 documents in the prompt (the same text, about 2,200 tokens). S3 gets no documents, only the two tools from A2. S3 round limit: 12.
- S1: one call, "give the final answer directly". S2: "think step by step", k = 5 samples, temperature 1.0, majority vote on (name, number to 3 significant figures). Whether the API accepted `temperature` is saved in `outputs/run1_S2.json` (`temperature_accepted`); the S2 wrong answers differ between samples and runs (for example Q-05: 14327.583 in run 1 and 14332.8 in run 2), so the sampling did vary. S1 and S3 use the default temperature.
- Tokens are counted from the `usage` field of every call (all 5 samples in S2, every round in S3). Time is measured with `time.perf_counter` around the API calls (plus the tool calls in S3). Cost = input tokens × input price + output tokens × output price (prices per 1M tokens, computed by `cost.py`).
- Why 20 questions and this rule: 20 is what the homework gives; it is enough to see the huge gap between S1 and the others, but too small for close differences (see C4). The rule needs the exact name, because "which district" is half of the question, and allows ±1 in the last digit, because the answers are rounded and tools and model may round at different places.

**My rule for a correct answer** (written before the first full run):

An answer is correct if the name equals `answer` (case-insensitive) and the number, rounded to `decimals`, is within 1 unit of the last digit of `value`. For yes/no questions the name is yes/no. The answer is read from the last `ANSWER:` line; if it is missing, the question counts as unanswered and wrong.

| Run | Strategy | Correct /20 | Unanswered | Input tokens | Output tokens | Median seconds per question | Total seconds | Cost ($) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | S1 direct | 3 | 1 | 44579 | 258 | 1.21 | 25.8 | 0.0461 |
| 1 | S2 think and vote (k = 5) | 15 | 0 | 222895 | 10466 | 8.78 | 177.9 | 0.2857 |
| 1 | S3 tools | 20 | 0 | 63952 | 4349 | 5.12 | 103.2 | 0.0900 |
| 2 | S1 direct | 2 | 1 | 44579 | 263 | 1.23 | 26.2 | 0.0462 |
| 2 | S2 think and vote (k = 5) | 16 | 0 | 222895 | 10141 | 8.72 | 174.8 | 0.2837 |
| 2 | S3 tools | 19 | 0 | 64071 | 4509 | 5.18 | 101.2 | 0.0911 |

Prices used for the cost column: $1.0 per 1M input tokens and $6.0 per 1M output tokens.

**Per question (run 1):**

| Question | S1 | S2 | S3 |
|---|:---:|:---:|:---:|
| Q-01 | ✗ | ✓ | ✓ |
| Q-02 | ✗ | ✓ | ✓ |
| Q-03 | ✗ | ✓ | ✓ |
| Q-04 | ✗ | ✓ | ✓ |
| Q-05 | ✗ | ✗ | ✓ |
| Q-06 | ✗ | ✓ | ✓ |
| Q-07 | ✗ | ✓ | ✓ |
| Q-08 | ✗ | ✓ | ✓ |
| Q-09 | ✗ | ✓ | ✓ |
| Q-10 | ✓ | ✓ | ✓ |
| Q-11 | ✗ | ✓ | ✓ |
| Q-12 | ✗ | ✗ | ✓ |
| Q-13 | ✓ | ✓ | ✓ |
| Q-14 | ✗ | ✓ | ✓ |
| Q-15 | ✗ | ✓ | ✓ |
| Q-16 | ✓ | ✓ | ✓ |
| Q-17 | ✗ | ✗ | ✓ |
| Q-18 | ✗ | ✗ | ✓ |
| Q-19 | ✗ | ✓ | ✓ |
| Q-20 | ✗ | ✗ | ✓ |

Run 2 (from `outputs/run2_*.json`): S1 was correct only on Q-10 and Q-16; S2 failed Q-05, Q-15, Q-17, Q-20; S3 failed only Q-18.

---

## Part C — Explain and choose (Hard)

### C1 — Does the tool description matter?

I changed only the `description` of `lookup` to `"Looks things up."` (the parameter schema with the field list was not changed) and ran S3 on Q-01, Q-09, Q-13, Q-18, Q-20 (`outputs/run1_S3_vague.json`). "Calls" are tool calls (from the logs). Compared with run 1 of S3.

| Question | Calls (your description) | Calls (vague) | Answer (yours) | Answer (vague) |
|---|---:|---:|---|---|
| Q-01 | 7 | 7 | ossbridge 4.5702 ✓ | ossbridge 4.5702 ✓ |
| Q-09 | 7 | 7 | millbrook 0.5557 ✓ | millbrook 0.5557 ✓ |
| Q-13 | 9 | 9 | coldharbour 4.1589 ✓ | coldharbour 4.159 ✓ |
| Q-18 | 3 | 3 | yes 40013.3914 ✓ | millbrook 40013.3914 ✗ |
| Q-20 | 10 | 10 | ashgrove 2993.3428 ✓ | ashgrove 2993.3428 ✓ |

What changed: almost nothing. The number of calls was the same on all five questions and the numbers in the answers are the same. Input tokens went down from 17013 to 14121 (about 17% less), because the long description is sent again in every round: Q-09 used 3691 tokens with my description and 3055 with the vague one over 4 API calls, so my description costs about 160 tokens per request.

The only different answer is Q-18, where the vague version wrote `millbrook` instead of `yes`. But the same mistake happened with my own description in run 2 (see C2), so I cannot blame the vague description. Why so little change: the parameter schema was still there (`field` is an enum of the 10 field names and the `district` description gives an example), and the tool name is clear, so the model could still guess how to use `lookup`. Limits of this test: only 5 questions, and none of them needs the tariff (Q-08, Q-17), where the description sentence about `district='Region'` matters most (the `district` parameter description still mentions 'Region'). I would expect a vague description to hurt more for a tool with a less obvious interface.

### C2 — Three mistakes explained

**S1 — Q-09 (run 1): wrong.** Log line: `run1_S1 Q-09: BAD predicted=('brightwater', 1.6) expected=['Millbrook', 0.6] ... out=12`. The model wrote only 12 output tokens, which is just the `ANSWER:` line, so it had no place to do any step of the calculation (two divisions and a subtraction). The number is a guess made in one pass. Evidence that it is a guess and not a small slip: in run 2 the same question gave `('brightwater', 1.5894)`, and Q-06 (a sum of two populations) gave 14117 in run 1 and 1317 in run 2, while the correct value is 14069. The model also does not know it is guessing, so it does not say so.

**S2 — Q-17 (both runs): wrong.** Log lines: run 1 `predicted=('harrowfield', 888.9228)`, run 2 `predicted=('harrowfield', 887.8973)`, expected 884 (S3 got 884.4572). The reasoning saved in `outputs/run1_S2.json` (`final_text` of Q-17) shows what happened:

```text
Harrowfield water cost per resident = 7,146,000 × 142.35 ÷ 90,212 = 11,278.3973 tenge
Ossbridge water cost per resident = 3,862,000 × 142.35 ÷ 52,904 = 10,389.4745 tenge
Difference = 888.9228 tenge per resident
```

The set-up is right (correct water use, populations, tariff and formula), but the arithmetic is wrong. I checked it with Python: 7,146,000 × 142.35 ÷ 90,212 = 11,276.03 (not 11,278.40) and 3,862,000 × 142.35 ÷ 52,904 = 10,391.57 (not 10,389.47), so the true difference is 884.46, the same as S3. The model wrote numbers with four decimals that look exact but are wrong already in the units digit: it did a big multiplication and a long division in text, with no calculator. (My first guess was that rounding of intermediate values caused it; the log shows that the formula and the inputs were fine and the digits of the division were not.) Voting over 5 samples helps when the wrong samples are different and the right value is the most common one; here the answers of the two runs are both a few tenge too high, and Q-05 (14327.583 and 14332.8 against 14235) and Q-20 (2998.16 and 2998.67 against 2993) also have wrong answers that are close to each other in both runs (I did not read the reasoning of these two). So voting fixed some questions (Q-12 and Q-18 were wrong in run 1 and right in run 2) but not Q-05, Q-17, Q-20.

**S3 — Q-18 (run 2): wrong, and the tools were not the problem.** Final text from `outputs/run2_S3.json`: "2030 projection: 40,013.3914 residents. Yes, it would exceed 40,000 residents." and then `ANSWER: Millbrook | 40013.3914`. The number is right (it came from `calculate`), and the text says "Yes", but the last line has a district name where my rule needs `yes`. The question asks both a yes/no and a number, and my prompt says "district name or yes/no", so the model sometimes chose the name. In run 1 the same question was right (`yes`), so it is sampling noise in the last line. S1 made the same name mistake on Q-18 in run 2. Tools cannot fix a formatting choice.

Questions from the homework:

- **Why voting fixes some mistakes but not others:** majority vote reduces the variance of independent errors, so it works when the mistakes are random and different in each sample (Q-12, Q-18). It does not reduce bias: if the same wrong habit appears in every sample (Q-05, Q-17, Q-20) the vote keeps it. It also costs k times more: S2 used 222895 input tokens against 44579 for S1 (5.0×).
- **Why the calculator removes mistakes the model cannot avoid:** the model writes digits one token at a time and has no exact multiplication inside it, so its error on a long division has no upper bound (S1 gave 1.6, 1.5894, 14117, 1317...). `calculate` runs real floating-point arithmetic, for example `44675 / 921.4 = 48.48599956587801`, where the error is about 1e-16. What is left are other kinds of mistakes: a wrong formula, wrong field, or a wrong final line like Q-18. The limit of this argument is that the calculator is only as good as the expression the model writes, and the `lookup` log lets me check that.
- **Why the loop needs several rounds and why each round costs more:** the model cannot call `calculate` on a number it has not seen yet, so the work goes in steps (Q-09: lookups, then divisions, then the subtraction = 4 API calls). The API does not remember anything, so every round sends the system prompt, the tool definitions, the question and all earlier messages and tool results again; each round is longer than the one before. This is why S3 input tokens are 63952 even though it has no documents.
- **A prediction that the runs confirmed:** questions that need only one simple step should be answered by S1. Q-10 (difference of two founding years) was correct in S1 in both runs and Q-16 (sum of two areas minus a third) too, while the questions with division and percentages were almost never correct.

### C3 — Which strategy I would use, and what would change it

I would use **S3 (tools)**. Run 1 / run 2: 20/20 and 19/20 correct against 15/20 and 16/20 for S2 and 3/20 and 2/20 for S1. S3 also used 63952 input tokens against 222895 for S2 (3.5× fewer) and 103 s in total against 178 s.

- **Why not S2:** it is less accurate and more expensive. It sends all the documents five times for each question, and the mistakes that remained (Q-05, Q-17, Q-20 in both runs) are not random, so more samples would not fix them.
- **Why not S1:** it is by far the cheapest and fastest (median 1.2 s, 44579 input tokens), but it is right only on 2 or 3 of 20 questions, so its answers cannot be trusted. It only does well on questions with one easy step.
- **What would change my choice:**
  1. *1,000 times more documents:* S1 and S2 cannot even work, because the documents would not fit in the prompt (17 documents are about 2,200 tokens, 1,000 times more is about 2.2 million). S3 with a search-based `lookup` is the only one that scales.
  2. *A strict time limit* (for example an answer in under 2 seconds) *or a very small budget, with questions that need no arithmetic:* S1 (about 1.2 s and one cheap call); I would accept that hard questions fail.
  3. *Questions with no arithmetic and few documents:* S1 would be enough, as Q-10 and Q-16 show, and a tool loop only adds cost.
  4. *If `calculate` could not be trusted or the task had no tool for the hard part:* then S2 would be my second choice, because voting at least reduces random errors.

### C4 — How sure I can be

- **How different were my two runs?** By 1 question for every strategy: S1 3 and 2, S2 15 and 16, S3 20 and 19. The questions that changed were few (S3: Q-18 only; S2: Q-12 and Q-18 became right, Q-15 became wrong).
- **Is the difference between my two best strategies bigger than that?** S3 was ahead of S2 by 5 questions in run 1 and by 3 in run 2, always bigger than the run-to-run difference of 1. Counting question by question, S3 was right where S2 was wrong 9 times (5 + 4) and S2 was right where S3 was wrong only once (Q-18 in run 2). That points to S3, but the same few questions (Q-05, Q-17, Q-20) make most of the gap, so I effectively have 3 or 4 hard questions, not 20 independent ones. The gap between S1 and the others (at least 12 questions) is so large that it is clear even with 20.
- **How many questions to trust the result?** With 20 questions the sampling error of a score near 80% is about ±9 percentage points (about ±2 questions). To see a 15-point difference (for example 80% against 95%) between two strategies I would need roughly 75 questions per strategy if I treat them as independent (a paired comparison on the same questions needs fewer); I would want at least 60 to 100 questions with different kinds of arithmetic.
- **What this cannot settle:** one model, one made-up corpus built with traps, two runs, and a strict scoring rule (S3 would be 20/20 in run 2 if Q-18 were scored by the number only). I also did not test other temperatures or other prompts for S1 and S2, so a better prompt might make them stronger.

### Final questions

1. When the model sends a `tool_calls` message, **nothing has run yet.** The model only produced text that says "please call `lookup` with these arguments". My code (`run_tool`) runs the function and sends the result back as a `tool` message.
2. `arguments` is a string because the model generates text, and the API passes the JSON as it was written. It can be invalid JSON, have a missing key or an extra key, or be of the wrong type. If I passed it straight into my function, I would get a `TypeError` or `KeyError` crash, or the model could pick any argument. So `run_tool` does `json.loads`, checks that the result is an object, and returns an error message (as a tool result) when something is wrong.
3. The two tool definitions add **485 tokens** to every S3 request (measured with `extras.py`: one call with the tools and one without, difference of `usage.prompt_tokens`). A second sign: replacing my `lookup` description with the 3-word vague one saved about 160 tokens per request (Q-09: 3691 → 3055 over 4 calls).
4. S2 used 222895 input tokens against 44579 for S1 in run 1 (5.0×) and 10466 output tokens against 258 (40.6×). The cost ratio S2/S1 was 6.19× in run 1 and 6.15× in run 2 (from `cost.py`, at $1.0 per 1M input and $6.0 per 1M output tokens), and S2 took 6.9× more time (177.9 s against 25.8 s). The reason is that S2 sends the whole document set 5 times per question and writes a long step-by-step answer 5 times, while S1 writes only the answer line.
5. No single question: many questions tied at the maximum of **4 rounds** in both runs (for example Q-01, Q-03, Q-04, Q-07 and Q-09 in run 1), and no question needed more (`extras.py`). The model asks all the lookups of one step in a single round (parallel tool calls), then the calculations, then the last combination, and then it answers, which makes 4 API calls. Q-20 had the most tool calls (10 in run 1) but still only 4 rounds, because its calls were sent in parallel.
6. With 100,000 documents I would not read every document with regular expressions when the program starts. I would build an index: a table of (entity, field, value, source, status) filled once, with the "archived" and "corrected by" information as columns, so that old data can be filtered by the database, plus a search index (keyword or embedding) that returns only the top few short snippets for a phrase. The tool must still return a limited amount of text and the source of each fact.
7. `calculate` parses the text with `ast.parse(mode="eval")` and walks the tree; it accepts only numbers, `+ - * / **` and unary plus or minus, so names, calls, attributes, strings and `__import__` are refused before anything runs. It also limits the length (200), the exponent (100) and the size of the result (1e15), and my tests check `__import__('os').system('echo hi')`, `(1).__class__` and `9**9**9`. The model can still make it misbehave in the sense of wrong use: a wrong formula, wrong numbers copied into it, or many pointless calls (stopped only by the round limit). The tool cannot know that an expression is meaningless.
8. Tools helped most with questions that need several divisions, percentages or products with long decimals: Q-05, Q-17 and Q-20 were wrong in S2 in both runs but right in S3 (for example Q-05 14235.3145). They helped least, in fact not at all, with simple questions such as Q-10 (difference of two years) and Q-16 (sum of two areas), which S1 already got right, and with formatting mistakes such as Q-18 in run 2, where the number was right and the final line was wrong.
