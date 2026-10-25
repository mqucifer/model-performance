"""Scoring one answer: valid in its form, empty, cut off or run away, and how it thought.

The form is the request's own, as production sent it (the operator, 2026-10-25):

- `json_schema`: the answer parses and the request's own JSON schema holds
  (`jsonschema`). Where the pinned crew still has the answer's model with the same
  schema, the answer must also be valid by that model and not cut at a quote, as
  crew's call layer refuses (`crew_org.calls.ask`). The step's own rules beyond
  the schema aren't run: they need the step's state.
- `two_part`: E1's grammar (ADR 0026 in mqucifer/crew): a JSON object, then blocks
  from `@@@ bN @@@` to `@@@ end @@@`, each named by exactly one field, and every
  field holding a block's name answered by one. The pinned crew retired its
  parser, so the rule is written here from the grammars the spend log holds.
- `free`: no form asked; valid when not empty.

In every JSON form a value cut at a double quote is refused, as crew refuses it
(`crew_org.cut_text`, crew#618): a string ending on a space or a colon, where a
quoted value would have begun. Crew's `cut_fields` reads a model, which a dated
case no longer has, so its rule is applied here to the parsed JSON.

A case is `dated` when the pinned crew no longer asks for that form: the model is
gone, its schema changed, or the form is `two_part`. It is scored all the same,
and flagged.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from functools import cache
from typing import Any

import jsonschema
from crew_org.calls import RUNAWAY_CHARS, response_format

# A line in a block is any line that doesn't start with "@@@".
BLOCK = re.compile(r"@@@ (b[0-9]+) @@@\n(?:(?!@@@)[^\n]*\n)*@@@ end @@@\n")
BLOCK_NAME = re.compile(r"b[0-9]+")
# Hedges in the thinking (model-fit-29's README): turns back on itself, per 10k characters.
HEDGES = re.compile(
    r"\b(?:wait|actually|hmm|alternatively|on second thought|"
    r"let me (?:re-?check|double-check|reconsider|re-?think|verify again))\b",
    re.IGNORECASE,
)


def form(request: dict[str, Any]) -> str:
    if (request.get("response_format") or {}).get("type") == "json_schema":
        return "json_schema"
    if "ebnf" in (request.get("extra_body") or {}):
        return "two_part"
    return "free"


@cache
def pinned_models() -> dict[str, Any]:
    """The pinned crew's answer models by name, from its crews' modules."""
    from crew_org import crews  # noqa: PLC0415
    from pydantic import BaseModel  # noqa: PLC0415

    found: dict[str, Any] = {}
    for info in pkgutil.iter_modules(crews.__path__):
        module = importlib.import_module(f"{crews.__name__}.{info.name}")
        for name, value in vars(module).items():
            if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
                found.setdefault(name, value)
    return found


def current_model(request: dict[str, Any], schema: str) -> Any:
    """The pinned crew's model for the answer, if it still asks with the same schema."""
    model = pinned_models().get(schema)
    if model is None or form(request) != "json_schema":
        return None
    return model if response_format(model) == request["response_format"] else None


def dated(request: dict[str, Any], schema: str) -> bool:
    return form(request) != "free" and current_model(request, schema) is None


def _json_schema(request: dict[str, Any], text: str, model: Any) -> str | None:
    try:
        found = json.loads(text)
    except ValueError:
        return "not_json"
    schema = request["response_format"].get("json_schema", {}).get("schema", {})
    try:
        jsonschema.validate(found, schema)
    except jsonschema.ValidationError:
        return "schema"
    except jsonschema.SchemaError:
        return "bad_schema"
    if model is not None:
        from pydantic import ValidationError  # noqa: PLC0415

        try:
            model.model_validate_json(text)
        except ValidationError:
            return "model"
    return "cut_at_quote" if cut_at_quote(found) else None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def cut_at_quote(value: Any) -> bool:
    """A string that ends where a quoted value would have begun (crew's `cut_fields`)."""
    return any(s.endswith(" ") or s.rstrip().endswith(":") for s in _strings(value) if s)


def _two_part(text: str) -> str | None:
    try:
        head, end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return "not_json"
    if not isinstance(head, dict):
        return "not_json"
    rest = text[end:].lstrip("\n")
    names: list[str] = []
    while rest:
        block = BLOCK.match(rest)
        if not block:
            return "blocks"
        names.append(block.group(1))
        rest = rest[block.end() :]
    named = [s for s in _strings(head) if BLOCK_NAME.fullmatch(s)]
    if sorted(named) != sorted(set(names)) or len(names) != len(set(names)):
        return "block_names"
    return "cut_at_quote" if cut_at_quote(head) else None


def score(request: dict[str, Any], schema: str, text: str, finish: str | None) -> dict[str, Any]:
    """The answer's verdict: valid, and why not in a word, with empty, cut and runaway."""
    empty = not text.strip()
    runaway = finish == "runaway"
    cut = finish == "length"
    why: str | None
    if empty:
        why = "empty"
    elif runaway:
        why = "runaway"
    elif cut:
        why = "length"
    elif form(request) == "json_schema":
        why = _json_schema(request, text, current_model(request, schema))
    elif form(request) == "two_part":
        why = _two_part(text)
    else:
        why = None
    return {"valid": why is None, "why": why, "empty": empty, "runaway": runaway, "cut": cut}


def hedges_per_10k(thinking: str) -> float | None:
    """Hedges per 10k characters of thinking, or None with none to read."""
    if not thinking:
        return None
    return round(len(HEDGES.findall(thinking)) * 10_000 / len(thinking), 2)


def ran_away(text: str) -> bool:
    """Whitespace at the end past crew's limit: an answer run on as whitespace."""
    return len(text) - len(text.rstrip()) >= RUNAWAY_CHARS
