
from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

_ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "$defs", "title", "description", "default", "examples", "format", "deprecated"})
_APPLIED = frozenset({
    "type", "enum", "const", "pattern", "minLength", "maxLength", "minimum", "maximum", "required", "properties",
    "additionalProperties", "patternProperties", "propertyNames", "items", "minItems", "maxItems", "uniqueItems", "allOf",
    "anyOf", "oneOf", "not", "if", "then", "else", "$ref", "unevaluatedProperties",
})
SUPPORTED_KEYWORDS = _ANNOTATIONS | _APPLIED
_TYPES = {
    "object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list), "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "boolean": lambda v: isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "null": lambda v: v is None,
}
_Result = Tuple[List[str], Set[str]]


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class SchemaSet:

    documents: Dict[str, Any]

    @classmethod
    def load(cls, folder: Path) -> "SchemaSet":
        docs: Dict[str, Any] = {}
        for path in sorted(folder.rglob("*.schema.json")):
            try:
                docs[path.relative_to(folder).as_posix()] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SchemaError(f"{path}: unreadable schema ({type(exc).__name__})") from exc
        if not docs:
            raise SchemaError(f"{folder}: no *.schema.json files")
        return cls(docs)

    def check_keywords(self) -> List[str]:
        found: List[str] = []

        def walk(node: Any, where: str) -> None:
            if not isinstance(node, dict):
                return
            for key, value in node.items():
                if key not in SUPPORTED_KEYWORDS:
                    found.append(f"{where}/{key}")
                elif key in ("properties", "patternProperties", "$defs") and isinstance(value, dict):
                    for name, sub in value.items():
                        walk(sub, f"{where}/{key}/{name}")
                elif key in ("allOf", "anyOf", "oneOf") and isinstance(value, list):
                    for i, sub in enumerate(value):
                        walk(sub, f"{where}/{key}/{i}")
                elif key in ("items", "additionalProperties", "unevaluatedProperties", "propertyNames", "not", "if", "then", "else"):
                    walk(value, f"{where}/{key}")

        for name, doc in self.documents.items():
            walk(doc, name)
        return found

    def validate(self, name: str, instance: Any) -> List[str]:
        """Validate ``instance`` against the schema file ``name``. Output: error messages (empty list means valid).

        Raises SchemaError for an unknown file, an unresolvable ``$ref`` or an unsupported keyword.
        Example: SchemaSet.load(folder).validate("item.schema.json", {}) -> ["$: missing required property 'kind'", ...]
        """
        if name not in self.documents:
            raise SchemaError(f"no schema named {name}")
        errors, _ = _Walker(self, name).run(self.documents[name], instance, "$")
        return errors

    def validate_def(self, name: str, def_name: str, instance: Any, path: str = "$") -> List[str]:
        defs = self.documents.get(name, {}).get("$defs", {}) if isinstance(self.documents.get(name), dict) else {}
        if def_name not in defs:
            raise SchemaError(f"{name}: no definition named {def_name}")
        errors, _ = _Walker(self, name).run(defs[def_name], instance, path)
        return errors


class _Walker:

    def __init__(self, schemas: SchemaSet, document: str) -> None:
        self.schemas, self.document = schemas, document

    def _resolve(self, ref: str) -> Tuple[str, Any]:
        file_part, _, pointer = ref.partition("#")
        name = self.document
        if file_part:
            name = posixpath.normpath(posixpath.join(posixpath.dirname(self.document), file_part))
        if name not in self.schemas.documents:
            raise SchemaError(f"$ref {ref} in {self.document}: no such schema file ({name})")
        node: Any = self.schemas.documents[name]
        for token in [t for t in pointer.split("/") if t]:
            if not isinstance(node, dict) or token not in node:
                raise SchemaError(f"$ref {ref}: {token} not found")
            node = node[token]
        return name, node

    def run(self, schema: Any, value: Any, path: str) -> _Result:
        if schema is True:
            return [], set(value) if isinstance(value, dict) else set()
        if schema is False:
            return [f"{path}: not allowed"], set()
        if not isinstance(schema, dict):
            raise SchemaError(f"{self.document}: a schema must be an object or a boolean, got {type(schema).__name__}")
        unknown = set(schema) - SUPPORTED_KEYWORDS
        if unknown:
            raise SchemaError(f"{self.document}: unsupported keyword(s) {sorted(unknown)}")
        errors: List[str] = []
        seen: Set[str] = set()
        self._simple(schema, value, path, errors)
        self._combine(schema, value, path, errors, seen)
        if isinstance(value, dict):
            self._object(schema, value, path, errors, seen)
        elif isinstance(value, list):
            self._array(schema, value, path, errors)
        if "unevaluatedProperties" in schema and isinstance(value, dict):
            rule = schema["unevaluatedProperties"]
            for key in sorted(set(value) - seen):
                if rule is False:
                    errors.append(f"{path}: unknown property '{key}'")
                else:
                    errors.extend(self.run(rule, value[key], f"{path}.{key}")[0])
                seen.add(key)
        return errors, seen

    def _simple(self, schema: Dict[str, Any], value: Any, path: str, errors: List[str]) -> None:
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_TYPES[t](value) for t in types):
                errors.append(f"{path}: must be {' or '.join(types)}")
                return
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: must be one of {schema['enum']}")
        if "const" in schema and value != schema["const"]:
            errors.append(f"{path}: must be {schema['const']!r}")
        if isinstance(value, str):
            if "pattern" in schema and not re.search(schema["pattern"], value):
                errors.append(f"{path}: must match {schema['pattern']}")
            if "minLength" in schema and len(value) < schema["minLength"]:
                errors.append(f"{path}: must be at least {schema['minLength']} characters")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                errors.append(f"{path}: must be at most {schema['maxLength']} characters")
        if _TYPES["number"](value):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"{path}: must be at least {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"{path}: must be at most {schema['maximum']}")

    def _combine(self, schema: Dict[str, Any], value: Any, path: str, errors: List[str], seen: Set[str]) -> None:
        if "$ref" in schema:
            name, target = self._resolve(schema["$ref"])
            sub, props = _Walker(self.schemas, name).run(target, value, path)
            errors.extend(sub)
            seen |= props
        for part in schema.get("allOf", []):
            sub, props = self.run(part, value, path)
            errors.extend(sub)
            seen |= props
        if "anyOf" in schema:
            results = [self.run(part, value, path) for part in schema["anyOf"]]
            passing = [r for r in results if not r[0]]
            if not passing:
                errors.append(f"{path}: matches none of the allowed shapes")
            for _, props in passing:
                seen |= props
        if "oneOf" in schema:
            results = [self.run(part, value, path) for part in schema["oneOf"]]
            passing = [r for r in results if not r[0]]
            if len(passing) != 1:
                errors.append(f"{path}: must match exactly one allowed shape (matches {len(passing)})")
            for _, props in passing[:1]:
                seen |= props
        if "not" in schema and not self.run(schema["not"], value, path)[0]:
            errors.append(f"{path}: matches a shape that is not allowed")
        if "if" in schema:
            cond_errors, cond_props = self.run(schema["if"], value, path)
            branch = schema.get("then") if not cond_errors else schema.get("else")
            if not cond_errors:
                seen |= cond_props
            if branch is not None:
                sub, props = self.run(branch, value, path)
                errors.extend(sub)
                seen |= props

    def _object(self, schema: Dict[str, Any], value: Dict[str, Any], path: str, errors: List[str], seen: Set[str]) -> None:
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property '{key}'")
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for key, item in value.items():
            matched = False
            if key in props:
                matched = True
                errors.extend(self.run(props[key], item, f"{path}.{key}")[0])
            for pattern, sub_schema in patterns.items():
                if re.search(pattern, key):
                    matched = True
                    errors.extend(self.run(sub_schema, item, f"{path}.{key}")[0])
            if matched:
                seen.add(key)
            elif "additionalProperties" in schema:
                seen.add(key)
                extra = schema["additionalProperties"]
                if extra is False:
                    errors.append(f"{path}: unknown property '{key}'")
                else:
                    errors.extend(self.run(extra, item, f"{path}.{key}")[0])
            if "propertyNames" in schema:
                errors.extend(self.run(schema["propertyNames"], key, f"{path}.<name {key}>")[0])

    def _array(self, schema: Dict[str, Any], value: List[Any], path: str, errors: List[str]) -> None:
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} item(s)")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errors.append(f"{path}: items must be unique")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(self.run(schema["items"], item, f"{path}[{i}]")[0])
