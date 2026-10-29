
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.reviewboard.layers.models import MAX_CHOICES, MAX_ITEMS, MAX_LINES, MAX_OPTIONS, MAX_ROWS

LAYER_KINDS = ("canvas", "questions", "rows")
ITEM_KINDS = ("yesno", "choice", "multi", "rank", "toggle", "text", "longtext", "number", "date")
PAGELESS_KINDS = frozenset({"questions", "rows"})

_ITEM: Dict[str, Any] = {
    "type": "object", "required": ["id", "kind", "label"],
    "properties": {
        "id": {"type": "string", "description": "lowercase id, letters digits - _ (the key of the owner's answer)"},
        "kind": {"type": "string", "enum": list(ITEM_KINDS),
                 "description": "yesno: true or false, or unanswered; choice: one option id; multi: a list of option ids; toggle: on or off (false unless default); text: one line; longtext: a paragraph"},
        "label": {"type": "string", "maxLength": 300},
        "help": {"type": "string", "maxLength": 600},
        "anchor": {"type": "string", "description": "an anchor id this question is about; declare it in anchors and tag the part data-rb-anchor"},
        "group": {"type": "string", "maxLength": 120, "description": "consecutive items sharing a group get one heading"},
        "required": {"type": "boolean", "description": "counted as 'n unanswered' in the header; never blocks Send"},
        "options": {"type": "array", "maxItems": MAX_OPTIONS, "description": "for choice and multi", "items": {
            "type": "object", "required": ["id", "label"], "properties": {"id": {"type": "string"}, "label": {"type": "string", "maxLength": 120}}}},
        "min": {"type": "integer", "description": "multi: advisory minimum, shown as unanswered below it; never enforced"},
        "max": {"type": "integer", "description": "multi: the most the owner may pick (enforced)"},
        "placeholder": {"type": "string", "maxLength": 120, "description": "text and longtext"},
        "default": {"description": "what the field shows until the owner edits it: a bool, an option id, a list of ids, or a string by kind"}}}

_CHOICE: Dict[str, Any] = {
    "type": "object", "required": ["id", "label"],
    "properties": {"id": {"type": "string"}, "label": {"type": "string", "maxLength": 120},
                   "tone": {"type": "string", "enum": ["ok", "push", "later", "none"], "description": "only the color of the pick"}}}

_ROW: Dict[str, Any] = {
    "type": "object", "required": ["id", "title"],
    "properties": {
        "id": {"type": "string", "description": "lowercase id, letters digits - _ (the key of the owner's pick)"},
        "title": {"type": "string", "maxLength": 200},
        "tag": {"type": "string", "maxLength": 40, "description": "a small status chip"},
        "lines": {"type": "array", "maxItems": MAX_LINES, "description": "labeled plain-text lines (you had / now / my take)", "items": {
            "type": "object", "required": ["label", "text"], "properties": {"label": {"type": "string", "maxLength": 60}, "text": {"type": "string", "maxLength": 1000}}}},
        "meta": {"type": "string", "maxLength": 80, "description": "a mono footnote such as a sha"},
        "group": {"type": "string", "maxLength": 120, "description": "consecutive rows sharing a group get one heading"},
        "anchor": {"type": "string", "description": "an anchor id of your page this row is about (declared in anchors)"},
        "choices": {"type": "array", "minItems": 1, "maxItems": MAX_CHOICES, "items": _CHOICE, "description": "this row's own picks; overrides the layer's choices"},
        "suggest": {"type": "string", "description": "a choice id marked as your take; never picked for the owner"},
        "default": {"description": "a carried pick: a choice id, or a list of ids when the layer picks several"}}}

LAYER: Dict[str, Any] = {
    "type": "object", "required": ["kind"],
    "description": ("Fill the board's frame with a prebuilt layer instead of writing the controls yourself. kind questions: a list of questions (yesno, choice, "
                    "multi, toggle, text, longtext), each with a note key; html is optional (your page as context, its parts tagged data-rb-anchor) and a "
                    "question with an anchor is drawn right under that part. kind canvas: your own payload page (same as payload_mode true). the owner's answer comes "
                    "back in revision.draft and the round's payload as {layer, v, values: {item id: value}, notes: {item id: text}}; an unanswered item has no key. "
                    "kind rows: a list of rows to review (title, tag, labeled lines, meta, group), each with its own picks from `choices` "
                    "(the layer's, or the row's own) and a note; pick one or several; `suggest` marks your take without picking it. For rows the answer is "
                    "values: {row id: choice id, or a list of ids when pick is several}. No prompts with a layer."),
    "properties": {
        "kind": {"type": "string", "enum": list(LAYER_KINDS)},
        "v": {"type": "integer", "enum": [1], "description": "required for questions and rows"},
        "title": {"type": "string", "maxLength": 120, "description": "required for questions and rows"},
        "intro": {"type": "string", "maxLength": 600},
        "placement": {"type": "string", "enum": ["inline", "float"], "description": "inline (default): each question under its part, the rest in an end section; float: one panel at the frame's edge"},
        "items": {"type": "array", "minItems": 1, "maxItems": MAX_ITEMS, "items": _ITEM, "description": "required for questions"},
        "pick": {"type": "string", "enum": ["one", "several"], "description": "rows: whether a row takes one pick (default) or several"},
        "choices": {"type": "array", "minItems": 1, "maxItems": MAX_CHOICES, "items": _CHOICE, "description": "rows: the picks every row offers unless it names its own"},
        "rows": {"type": "array", "minItems": 1, "maxItems": MAX_ROWS, "items": _ROW, "description": "required for rows"}}}


def allows_no_page(args: Dict[str, Any]) -> bool:
    layer = args.get("layer")
    return isinstance(layer, dict) and layer.get("kind") in PAGELESS_KINDS
