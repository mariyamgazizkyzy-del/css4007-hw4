"""HW4 tools: lookup (facts from the corpus) and calculate (safe arithmetic)."""
import ast
import difflib
import json
import math
import operator
import re
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "data" / "corpus.jsonl"

FIELDS = [
    "population_2025", "population_2020", "area_km2", "founded_year", "schools",
    "pupils", "budget_million_tenge", "water_use_m3", "paved_road_km",
    "water_tariff_tenge_per_m3",
]
UNITS = {
    "population_2025": "residents", "population_2020": "residents", "area_km2": "km2",
    "founded_year": "year", "schools": "schools", "pupils": "pupils",
    "budget_million_tenge": "million tenge", "water_use_m3": "m3 per year",
    "paved_road_km": "km", "water_tariff_tenge_per_m3": "tenge per m3",
}


def _num(s):
    s = s.replace(",", "")
    return float(s) if "." in s else int(s)


def _first(pattern, text):
    m = re.search(pattern, text)
    return _num(m.group(1)) if m else None


def _parse_profile(text):
    """Pull every field out of one 2025 profile. Three sentence templates exist."""
    f = {}
    f["area_km2"] = _first(r"([\d,]+\.\d) square kilometres", text)
    f["budget_million_tenge"] = _first(r"([\d,]+\.\d) million tenge", text)
    f["founded_year"] = _first(r"[Ff]ounded in (\d{4})", text)
    f["schools"] = _first(r"(\d+) schools", text)
    f["pupils"] = _first(r"([\d,]+) pupils", text)
    f["paved_road_km"] = _first(r"([\d,]+\.\d) km", text)
    # population: three templates
    m = (re.search(r"recorded ([\d,]+) residents; the 2020 census had recorded ([\d,]+)", text)
         or re.search(r"counted ([\d,]+) residents, up from ([\d,]+) at the 2020", text))
    if m:
        f["population_2025"], f["population_2020"] = _num(m.group(1)), _num(m.group(2))
    else:
        m = re.search(r"([\d,]+) in 2020 and ([\d,]+) in 2025", text)
        if m:
            f["population_2020"], f["population_2025"] = _num(m.group(1)), _num(m.group(2))
    # water: megalitres for most districts, cubic metres for one -> always m3
    ml = _first(r"([\d,]+) megalitres", text)
    if ml is not None:
        f["water_use_m3"] = ml * 1000
        f["_water_src"] = f"{ml:,} ML x 1000"
    else:
        f["water_use_m3"] = _first(r"([\d,]+) cubic metres of water", text)
        f["_water_src"] = "given in m3"
    return f


def _load():
    """Build {district: {field: (value, source)}} once. Archived profiles are skipped."""
    docs = [json.loads(line) for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    data, tariff = {}, None
    for d in docs:
        title, text = d["title"], d["text"]
        if "ARCHIVED" in title or text.startswith("ARCHIVED"):
            continue                                   # superseded 2019 profiles
        if title.endswith("district profile (2025)"):
            name = title.split()[0]
            parsed = _parse_profile(text)
            wsrc = parsed.pop("_water_src")
            data[name] = {}
            for k, v in parsed.items():
                if v is not None:
                    src = d["id"] if k != "water_use_m3" else f"{d['id']} ({wsrc})"
                    data[name][k] = (v, src)
        elif title.startswith("Household water tariff"):
            tariff = (_first(r"is ([\d.]+) tenge per cubic metre", text), d["id"])
    for d in docs:                                     # corrections take precedence
        if d["title"].startswith("Correction notice"):
            name = d["title"].split("-")[-1].strip()
            m = re.search(r"correct area is ([\d,.]+) square kilometres", d["text"])
            if name in data and m:
                data[name]["area_km2"] = (_num(m.group(1)), f"{data[name]['area_km2'][1]}, corrected by {d['id']}")
    return data, tariff


_DATA, _TARIFF = _load()


def lookup(district, field):
    """Return ONE fact as a dict. Never raises."""
    try:
        if not isinstance(district, str) or not district.strip():
            return {"error": "argument 'district' is required and must be a string"}
        if not isinstance(field, str) or not field.strip():
            return {"error": "argument 'field' is required and must be a string"}
        field = field.strip()
        if field not in FIELDS:
            return {"error": f"unknown field '{field[:40]}'; valid fields: {', '.join(FIELDS)}"}
        name = district.strip()
        if field == "water_tariff_tenge_per_m3":
            if name.lower() != "region":
                return {"error": "the tariff is the same in every district; use district='Region'"}
            return {"district": "Region", "field": field, "value": _TARIFF[0],
                    "unit": UNITS[field], "source": _TARIFF[1]}
        match = next((k for k in _DATA if k.lower() == name.lower()), None)
        if match is None:
            close = difflib.get_close_matches(name, list(_DATA), n=2, cutoff=0.6)
            hint = f"; did you mean {' or '.join(close)}?" if close else f"; districts: {', '.join(_DATA)}"
            return {"error": f"no district named {name[:40]}{hint}"}
        if field not in _DATA[match]:
            return {"error": f"no 2025 value for {field}; archived 2019 profiles are not used"}
        value, source = _DATA[match][field]
        return {"district": match, "field": field, "value": value, "unit": UNITS[field], "source": source}
    except Exception as e:                             # last line of defence
        return {"error": f"lookup failed: {type(e).__name__}"}


# ---------------------------------------------------------------- calculate
MAX_LEN, MAX_EXP, MAX_ABS = 200, 100, 1e15
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class _Refuse(Exception):
    pass


def _check(x):
    if not math.isfinite(x) or abs(x) > MAX_ABS:
        raise _Refuse("number too large")
    return x


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _check(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _check(_UN[type(node.op)](_eval(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > MAX_EXP:
            raise _Refuse("number too large")
        if isinstance(node.op, ast.Div) and b == 0:
            raise _Refuse("division by zero")
        if isinstance(node.op, ast.Pow) and a == 0 and b < 0:
            raise _Refuse("division by zero")
        r = _BIN[type(node.op)](a, b)
        if isinstance(r, complex):
            raise _Refuse("result is not a real number")
        return _check(r)
    raise _Refuse(f"not allowed: {type(node).__name__}")


def calculate(expression):
    """Evaluate arithmetic with ast (no eval/exec). Never raises."""
    try:
        if not isinstance(expression, str):
            return {"error": "argument 'expression' is required and must be a string"}
        expr = expression.strip()
        if not expr:
            return {"error": "argument 'expression' is required and must be a string"}
        if len(expr) > MAX_LEN:
            return {"error": "expression too long"}
        try:
            tree = ast.parse(expr, mode="eval")
        except (SyntaxError, ValueError):
            return {"error": "cannot parse expression"}
        return {"expression": expr, "result": float(_eval(tree))}
    except _Refuse as e:
        return {"error": str(e)}
    except (OverflowError, ZeroDivisionError):
        return {"error": "number too large"}
    except RecursionError:
        return {"error": "expression too deeply nested"}
    except Exception as e:
        return {"error": f"calculate failed: {type(e).__name__}"}


# ------------------------------------------------- definitions + safe dispatch
TOOL_DEFINITIONS = [
    {"type": "function", "function": {
        "name": "lookup",
        "description": (
            "Get ONE current (2025) fact about ONE district of the Nine Rivers Region, or the regional "
            "water tariff. Returns a single number, its unit and the source document. Archived 2019 "
            "profiles are never used and corrections are already applied. Call it once per district per "
            "field. For the tariff use district='Region' and field='water_tariff_tenge_per_m3'. Fields: "
            "population_2025, population_2020, area_km2, founded_year, schools, pupils, "
            "budget_million_tenge, water_use_m3 (cubic metres per year, same unit for all districts), "
            "paved_road_km, water_tariff_tenge_per_m3. District must be spelled exactly, e.g. "
            "'Ossbridge' and 'Ossford' are different districts."),
        "parameters": {"type": "object", "properties": {
            "district": {"type": "string", "description": "Exact district name, e.g. 'Millbrook', or 'Region' for the tariff"},
            "field": {"type": "string", "enum": FIELDS}},
            "required": ["district", "field"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "calculate",
        "description": (
            "Evaluate ONE arithmetic expression and return the exact result. Use it for ALL arithmetic "
            "(divisions, differences, percentages, products) instead of computing in your head. Allowed: "
            "numbers, + - * / ** and parentheses, e.g. '44675 / 921.4' or '(37203 - 34590) / 34590 * 100'. "
            "Percentage = write the formula yourself, there is no % operator. No variables, no functions, no text."),
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "Arithmetic expression, at most 200 characters"}},
            "required": ["expression"], "additionalProperties": False}}},
]


def run_tool(name, arguments):
    """Safe dispatcher for the loop: `arguments` is the raw JSON STRING from the model."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (json.JSONDecodeError, TypeError):
        return {"error": "arguments is not valid JSON"}
    if not isinstance(args, dict):
        return {"error": "arguments must be a JSON object"}
    if name == "lookup":
        return lookup(args.get("district"), args.get("field"))
    if name == "calculate":
        return calculate(args.get("expression"))
    return {"error": f"unknown tool '{str(name)[:40]}'; available: lookup, calculate"}
