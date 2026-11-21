"""The one tool both agents hold, and what each is told. Schema matches g0/common.py so live and eval agree."""

from __future__ import annotations

import json
from typing import Any

from ..types import SLOTS, Values

TOOL_NAME = "log_commitment"
TOOL: dict[str, Any] = {
    "type": "function",
    "name": TOOL_NAME,
    "description": "Record what the caller committed to on this call. Fill only the values the caller actually said.",
    "parameters": {
        "type": "object",
        "properties": {
            "amount_rupees": {
                "type": ["integer", "null"],
                "description": "Amount in rupees as a plain integer.",
            },
            "day_of_month": {
                "type": ["integer", "null"],
                "description": "Day of the month (1-31) if the caller gave a date.",
            },
            "weekday": {
                "type": ["string", "null"],
                "enum": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", None],
            },
            "phone": {
                "type": ["string", "null"],
                "description": "10-digit Indian mobile number, digits only.",
            },
        },
        "required": list(SLOTS),
    },
}

BASE = (
    "You are an assistant answering a phone call in India. Callers speak Hindi, English or a mix. "
    "When the caller states an amount, a date or a phone number, call log_commitment with those values."
)
LEFT_INSTRUCTIONS = BASE
RIGHT_INSTRUCTIONS = (
    BASE + " Speak short, natural Hinglish; one sentence at a time. Call log_commitment immediately, before "
    "saying anything, and never tell the caller a value is noted until the tool returns status committed. "
    "If the tool returns status held, say exactly the text in ask_exactly, word for word, and nothing else; "
    "when the caller answers, call log_commitment again with all the values as you now understand them. "
    "If it returns status voided, say nothing about it and keep listening. "
    "If it returns status escalated, say a colleague will call back to confirm the details and do not call the tool again."
)


def clean_args(raw: str | dict[str, Any]) -> Values:
    """Tool arguments -> typed values. Malformed phones are kept as given: the guard must see them."""
    try:
        args = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except json.JSONDecodeError:
        return {}
    out: Values = {}
    for slot in SLOTS:
        v = args.get(slot)
        if v in (None, "", "null"):
            continue
        if slot == "phone":
            digits = "".join(c for c in str(v) if c.isdigit())
            out[slot] = digits[-10:] if len(digits) > 10 and digits[:-10] in ("91", "0") else digits
        elif slot == "weekday":
            out[slot] = str(v).strip().lower()
        else:
            try:
                out[slot] = int(v)
            except (TypeError, ValueError):
                continue
    return out
