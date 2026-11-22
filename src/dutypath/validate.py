"""Input checks, before any rule is read.

A shipment is written by hand, so it arrives with the mistakes hands make: a
value copied as ``"480,000"``, a weight share copied as ``"62%"``, a negative
amount left over from a credit note.  Those are not rule questions, and a
traceback is not an answer either.

Two things happen here, and they are different on purpose:

* a number written with separators or a percent sign is read as the number it
  clearly is, so the assessment goes ahead;
* a number that cannot mean what the field says (a negative declared value, a
  value share above 100 percent, a shipment with no declared value at all) is
  an input error, named with the field and the value, and the caller reports it
  as such.  The engine does not price a shipment whose own amount is nonsense.

A material value that is simply absent is not an error.  It is a fact the bill
of materials does not carry, and the rule that needs it answers ``UNDECIDABLE``
with the material named.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class InputError(ValueError):
    """A shipment field that cannot be used as written."""


def number(value, field: str, *, positive: bool = False, allow_none: bool = False) -> float | None:
    """Read one number out of JSON that a person typed."""
    if value is None or value == "":
        if allow_none:
            return None
        raise InputError("%s is missing" % field)
    if isinstance(value, bool):
        raise InputError("%s is %r, not a number" % (field, value))
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip().replace(",", "").replace("_", "").replace(" ", "")
        percent = text.endswith("%")
        if percent:
            text = text[:-1]
        match = NUMBER.fullmatch(text)
        if match is None:
            raise InputError("%s is %r, which is not a number" % (field, value))
        result = float(match.group(0))
    if result != result or result in (float("inf"), float("-inf")):
        raise InputError("%s is not a finite number" % field)
    if positive and result <= 0:
        raise InputError("%s must be greater than zero" % field)
    return result


def shipment(payload: dict, *, require_declared: bool = True) -> dict:
    """The shipment with its numbers read, or an ``InputError`` that names why.

    The returned object is a copy.  The caller's file is never rewritten, so the
    report and the input can be read side by side.  ``require_declared`` is off
    only on the origin path, where a rule that asks no value question does not
    need one.
    """
    if not isinstance(payload, dict):
        raise InputError("the shipment is not a JSON object")
    out = dict(payload)
    goods = dict(payload.get("goods") or {})
    if not goods:
        raise InputError("the shipment has no goods")
    raw = goods.get("declared_value", goods.get("fob"))
    if raw is None and not require_declared:
        goods["declared_value"] = None
    else:
        goods["declared_value"] = number(raw, "goods.declared_value", positive=True)
    if goods.get("fob") is not None:
        goods["fob"] = number(goods["fob"], "goods.fob", positive=True)
    out["goods"] = goods

    materials = payload.get("materials")
    if materials is None:
        materials = []
    if not isinstance(materials, list):
        raise InputError("materials is not a list")
    cleaned = []
    for index, item in enumerate(materials, start=1):
        if not isinstance(item, dict):
            raise InputError("material %d is not a JSON object" % index)
        entry = dict(item)
        entry.setdefault("id", "M%d" % index)
        entry["value"] = number(
            item.get("value"), "materials[%s].value" % entry["id"], allow_none=True
        )
        if entry["value"] is not None and entry["value"] < 0:
            raise InputError("materials[%s].value is negative" % entry["id"])
        cleaned.append(entry)
    out["materials"] = cleaned

    attributes = payload.get("attributes")
    if isinstance(attributes, dict):
        attributes = dict(attributes)
        if attributes.get("originating_polymer_weight_percent") is not None:
            share = number(
                attributes["originating_polymer_weight_percent"],
                "attributes.originating_polymer_weight_percent",
            )
            if share < 0 or share > 100:
                raise InputError(
                    "attributes.originating_polymer_weight_percent must be between 0 and 100"
                )
            attributes["originating_polymer_weight_percent"] = share
        out["attributes"] = attributes
    return out
