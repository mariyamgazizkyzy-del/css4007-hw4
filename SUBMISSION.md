# HW4 — submission

**AI assistance:** I used Claude (Anthropic) to help plan Part A (steps, tool definitions, the Q-09 walkthrough) and to write and review the code (`tools.py`, `tests/`, `strategies.py`, `run.py`). I read and checked the plan and the code myself, ran everything on my own computer with my own API key, and the numbers in the tables come from my own runs in `outputs/`.

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
- I added a small `run_tool(name, arguments)` function in `tools.py`. It is step 4 (Dispatch) from A1: it parses the `arguments` JSON string, checks it is an object, and calls `lookup` or `calculate`; on bad input it returns an error JSON instead of crashing.
- I set `reasoning_effort="none"` for all three strategies. The API refused to use function tools with `gpt-5.6-luna` in Chat Completions when reasoning was on (error 400), so I fixed it to `"none"` everywhere to keep the comparison fair. In S2 the step-by-step thinking comes from the prompt.
- Water use from `lookup` is in m³ per year for every district (as planned in A1); I wrote the unit conversion into the `source` field.

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

- Round limit, and why: **12 rounds** (`MAX_ROUNDS` in `strategies.py`). By hand (A3), Q-09 needs 3 rounds with parallel tool calls and the hardest questions need more, so 12 leaves room for a model that calls tools one by one, but it still stops a model that loops forever and wastes tokens. If the limit is reached, the question is marked unanswered.
- Where the logs are: `outputs/logs/run<N>_S3_<question id>.json` (every tool call with its inputs, result and seconds, plus tokens and seconds of