
from __future__ import annotations

import json
import math
import posixpath
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

try:
    from src.plugins.sdk.schema_digest import SCHEMA_DIR
except ImportError:
    SCHEMA_DIR = Path(__file__).resolve().parent / "extension_schemas"

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
_MAX_SCHEMA_DEPTH = 64
_INT_KEYWORDS = ("minLength", "maxLength", "minItems", "maxItems")
_NUM_KEYWORDS = ("minimum", "maximum")
_SUBSCHEMA_KEYWORDS = ("items", "additionalProperties", "unevaluatedProperties", "propertyNames", "not", "if", "then", "else")


def _is_schema_pointer(tokens: List[str]) -> bool:
    state = "schema"
    for tok in tokens:
        if state == "schema":
            if tok in ("properties", "patternProperties", "$defs"):
                state = "map"
            elif tok in ("allOf", "anyOf", "oneOf"):
                state = "list"
            elif tok in _SUBSCHEMA_KEYWORDS:
                state = "schema"
            else:
                return False
        elif state == "map":
            state = "schema"
        elif state == "list":
            if not tok.isdigit():
                return False
            state = "schema"
    return state == "schema"


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

    def check_schemas(self, *, allow_external_refs: bool = True) -> List[str]:
        found: List[str] = []
        verified_clean: Dict[Tuple[str, int], int] = {}
        walked_schemas: Set[Tuple[str, int]] = set()
        walking_schemas: Set[Tuple[str, int]] = set()

        def check_ref_cycle_root(root_node: Any, root_doc: str, root_where: str) -> None:
            dfs_cyclic: Set[Tuple[str, int]] = set()
            dfs_truncated: Dict[Tuple[str, int], int] = {}

            def _dfs(
                node: Any,
                doc_name: str,
                where: str,
                active: FrozenSet[Tuple[str, str]],
                depth: int,
            ) -> Tuple[bool, int, bool]:
                if depth > _MAX_SCHEMA_DEPTH:
                    found.append(f"{where}: schema $ref depth exceeded")
                    return False, 0, True
                if not isinstance(node, dict):
                    return True, 0, False
                node_key = (doc_name, id(node))
                if node_key in verified_clean:
                    sub_h = verified_clean[node_key]
                    if depth + sub_h > _MAX_SCHEMA_DEPTH:
                        found.append(f"{where}: schema $ref depth exceeded")
                        return False, sub_h, True
                    return True, sub_h, False
                if node_key in dfs_cyclic:
                    return False, 0, False
                if node_key in dfs_truncated and depth >= dfs_truncated[node_key]:
                    return False, 0, True

                clean = True
                max_h = 0
                truncated = False

                ref = node.get("$ref")
                if isinstance(ref, str) and ref.strip():
                    if allow_external_refs or ref.startswith("#"):
                        try:
                            t_doc, target = _Walker(self, doc_name)._resolve(ref)
                        except SchemaError:
                            pass
                        else:
                            ptr = "/".join(t for t in ref.partition("#")[2].split("/") if t)
                            key = (t_doc, ptr)
                            if key in active:
                                found.append(f"{where}/$ref: cyclic $ref {ref!r}")
                                return False, 0, False
                            c, h, tr = _dfs(target, t_doc, f"{where}/$ref", active | {key}, depth + 1)
                            if not c:
                                clean = False
                            if tr:
                                truncated = True
                            max_h = max(max_h, 1 + h)

                for k in ("allOf", "anyOf", "oneOf"):
                    subs = node.get(k)
                    if isinstance(subs, list):
                        for i, sub in enumerate(subs):
                            c, h, tr = _dfs(sub, doc_name, f"{where}/{k}/{i}", active, depth + 1)
                            if not c:
                                clean = False
                            if tr:
                                truncated = True
                            max_h = max(max_h, 1 + h)

                for k in ("not", "if", "then", "else"):
                    if k in node:
                        c, h, tr = _dfs(node[k], doc_name, f"{where}/{k}", active, depth + 1)
                        if not c:
                            clean = False
                        if tr:
                            truncated = True
                        max_h = max(max_h, 1 + h)

                if clean and not truncated:
                    verified_clean[node_key] = max_h
                elif not clean and not truncated:
                    dfs_cyclic.add(node_key)
                elif not clean and truncated:
                    prev_d = dfs_truncated.get(node_key)
                    dfs_truncated[node_key] = depth if prev_d is None else min(prev_d, depth)
                return clean, max_h, truncated

            _dfs(root_node, root_doc, root_where, frozenset(), 0)

        def walk(node: Any, where: str, doc_name: str, depth: int = 0) -> None:
            if depth > _MAX_SCHEMA_DEPTH:
                found.append(f"{where}: schema nesting depth exceeded")
                return
            if isinstance(node, bool):
                return
            if not isinstance(node, dict):
                found.append(f"{where}: schema must be an object or boolean")
                return
            nkey = (doc_name, id(node))
            if nkey in walked_schemas or nkey in walking_schemas:
                return
            walking_schemas.add(nkey)
            try:
                for key, value in node.items():
                    if key not in SUPPORTED_KEYWORDS:
                        found.append(f"{where}/{key}: unsupported keyword")
                    elif key == "type":
                        if isinstance(value, str):
                            if value not in _TYPES:
                                found.append(f"{where}/type: unknown type {value!r}")
                        elif isinstance(value, list) and value and all(isinstance(t, str) and t in _TYPES for t in value) and len(set(value)) == len(value):
                            pass
                        else:
                            found.append(f"{where}/type: invalid type specification")
                    elif key == "enum":
                        if not isinstance(value, list) or not value:
                            found.append(f"{where}/enum: must be a non-empty list")
                    elif key == "pattern":
                        if not isinstance(value, str):
                            found.append(f"{where}/pattern: must be a string")
                        else:
                            try:
                                re.compile(value)
                            except re.error as exc:
                                found.append(f"{where}/pattern: invalid regex ({exc})")
                    elif key in _INT_KEYWORDS:
                        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                            found.append(f"{where}/{key}: must be a non-negative integer")
                    elif key in _NUM_KEYWORDS:
                        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                            found.append(f"{where}/{key}: must be a finite number")
                    elif key == "uniqueItems":
                        if not isinstance(value, bool):
                            found.append(f"{where}/uniqueItems: must be a boolean")
                    elif key == "required":
                        if not isinstance(value, list) or not all(isinstance(k, str) for k in value):
                            found.append(f"{where}/required: must be a list of strings")
                    elif key in ("properties", "$defs"):
                        if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
                            found.append(f"{where}/{key}: must be an object mapping strings to schemas")
                        else:
                            for sub_name, sub in value.items():
                                walk(sub, f"{where}/{key}/{sub_name}", doc_name, depth + 1)
                    elif key == "patternProperties":
                        if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
                            found.append(f"{where}/patternProperties: must be an object mapping regexes to schemas")
                        else:
                            for pat, sub in value.items():
                                try:
                                    re.compile(pat)
                                except re.error as exc:
                                    found.append(f"{where}/patternProperties/{pat}: invalid regex ({exc})")
                                walk(sub, f"{where}/patternProperties/{pat}", doc_name, depth + 1)
                    elif key in ("allOf", "anyOf", "oneOf"):
                        if not isinstance(value, list) or not value:
                            found.append(f"{where}/{key}: must be a non-empty list of schemas")
                        else:
                            for i, sub in enumerate(value):
                                walk(sub, f"{where}/{key}/{i}", doc_name, depth + 1)
                    elif key in _SUBSCHEMA_KEYWORDS:
                        walk(value, f"{where}/{key}", doc_name, depth + 1)
                    elif key == "$ref":
                        if not isinstance(value, str) or not value.strip():
                            found.append(f"{where}/$ref: must be a non-empty string")
                        elif not allow_external_refs and not value.startswith("#"):
                            found.append(f"{where}/$ref: external $ref {value!r} is not allowed")
                        else:
                            try:
                                t_doc, target = _Walker(self, doc_name)._resolve(value)
                            except SchemaError as exc:
                                found.append(f"{where}/$ref: {exc}")
                            else:
                                ptr_tokens = [t for t in value.partition("#")[2].split("/") if t]
                                if not _is_schema_pointer(ptr_tokens):
                                    found.append(f"{where}/$ref: target {value!r} is not a schema")
                                elif not isinstance(target, (dict, bool)):
                                    found.append(f"{where}/$ref: target {value!r} must be an object or boolean")
                                else:
                                    walk(target, f"{where}/$ref", t_doc, 0)
                                    check_ref_cycle_root(node, doc_name, where)
            finally:
                walking_schemas.discard(nkey)
            walked_schemas.add(nkey)

        for name, doc in self.documents.items():
            walk(doc, name, name)
        return found

    def validate(self, name: str, instance: Any) -> List[str]:
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

    def __init__(
        self,
        schemas: SchemaSet,
        document: str,
        memo: Optional[Dict[Tuple[str, int, int, str], Tuple[List[str], Set[str], int]]] = None,
    ) -> None:
        self.schemas, self.document = schemas, document
        self._memo: Dict[Tuple[str, int, int, str], Tuple[List[str], Set[str], int]] = {} if memo is None else memo
        self._deepest: int = 0

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

    def run(
        self,
        schema: Any,
        value: Any,
        path: str,
        depth: int = 0,
        active_refs: FrozenSet[Tuple[str, str, str]] = frozenset(),
    ) -> _Result:
        if depth > _MAX_SCHEMA_DEPTH:
            raise SchemaError(f"{self.document}: schema nesting depth exceeded at {path}")
        if schema is True:
            self._deepest = max(self._deepest, depth)
            return [], set(value) if isinstance(value, dict) else set()
        if schema is False:
            self._deepest = max(self._deepest, depth)
            return [f"{path}: not allowed"], set()
        if not isinstance(schema, dict):
            raise SchemaError(f"{self.document}: a schema must be an object or a boolean, got {type(schema).__name__}")
        mkey = (self.document, id(schema), id(value), path)
        if mkey in self._memo:
            c_errs, c_seen, sub_h = self._memo[mkey]
            if depth + sub_h > _MAX_SCHEMA_DEPTH:
                raise SchemaError(f"{self.document}: schema nesting depth exceeded at {path}")
            self._deepest = max(self._deepest, depth + sub_h)
            return list(c_errs), set(c_seen)
        unknown = set(schema) - SUPPORTED_KEYWORDS
        if unknown:
            raise SchemaError(f"{self.document}: unsupported keyword(s) {sorted(unknown)}")
        prev_deepest = self._deepest
        self._deepest = depth
        errors: List[str] = []
        seen: Set[str] = set()
        self._simple(schema, value, path, errors)
        self._combine(schema, value, path, errors, seen, depth, active_refs)
        if isinstance(value, dict):
            self._object(schema, value, path, errors, seen, depth, active_refs)
        elif isinstance(value, list):
            self._array(schema, value, path, errors, depth, active_refs)
        if "unevaluatedProperties" in schema and isinstance(value, dict):
            rule = schema["unevaluatedProperties"]
            for key in sorted(set(value) - seen):
                if rule is False:
                    errors.append(f"{path}: unknown property '{key}'")
                else:
                    errors.extend(self.run(rule, value[key], f"{path}.{key}", depth + 1, active_refs)[0])
                seen.add(key)
        if len(errors) > 1:
            errors = list(dict.fromkeys(errors))
        sub_h = max(0, self._deepest - depth)
        self._memo[mkey] = (list(errors), set(seen), sub_h)
        self._deepest = max(prev_deepest, self._deepest)
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

    def _combine(
        self,
        schema: Dict[str, Any],
        value: Any,
        path: str,
        errors: List[str],
        seen: Set[str],
        depth: int = 0,
        active_refs: FrozenSet[Tuple[str, str, str]] = frozenset(),
    ) -> None:
        if "$ref" in schema:
            ref = schema["$ref"]
            if not isinstance(ref, str) or not ref.strip():
                raise SchemaError(f"{self.document}: invalid $ref at {path}")
            name, target = self._resolve(ref)
            ptr = "/".join(t for t in ref.partition("#")[2].split("/") if t)
            ref_key = (name, ptr, path)
            if ref_key in active_refs:
                raise SchemaError(f"{self.document}: cyclic $ref {ref!r} at {path}")
            child = _Walker(self.schemas, name, memo=self._memo)
            sub, props = child.run(target, value, path, depth + 1, active_refs | {ref_key})
            self._deepest = max(self._deepest, child._deepest)
            errors.extend(sub)
            seen |= props
        for part in schema.get("allOf", []):
            sub, props = self.run(part, value, path, depth + 1, active_refs)
            errors.extend(sub)
            seen |= props
        if "anyOf" in schema:
            results = [self.run(part, value, path, depth + 1, active_refs) for part in schema["anyOf"]]
            passing = [r for r in results if not r[0]]
            if not passing:
                errors.append(f"{path}: matches none of the allowed shapes")
            for _, props in passing:
                seen |= props
        if "oneOf" in schema:
            results = [self.run(part, value, path, depth + 1, active_refs) for part in schema["oneOf"]]
            passing = [r for r in results if not r[0]]
            if len(passing) != 1:
                errors.append(f"{path}: must match exactly one allowed shape (matches {len(passing)})")
            for _, props in passing[:1]:
                seen |= props
        if "not" in schema and not self.run(schema["not"], value, path, depth + 1, active_refs)[0]:
            errors.append(f"{path}: matches a shape that is not allowed")
        if "if" in schema:
            cond_errors, cond_props = self.run(schema["if"], value, path, depth + 1, active_refs)
            branch = schema.get("then") if not cond_errors else schema.get("else")
            if not cond_errors:
                seen |= cond_props
            if branch is not None:
                sub, props = self.run(branch, value, path, depth + 1, active_refs)
                errors.extend(sub)
                seen |= props

    def _object(
        self,
        schema: Dict[str, Any],
        value: Dict[str, Any],
        path: str,
        errors: List[str],
        seen: Set[str],
        depth: int = 0,
        active_refs: FrozenSet[Tuple[str, str, str]] = frozenset(),
    ) -> None:
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property '{key}'")
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for key, item in value.items():
            matched = False
            if key in props:
                matched = True
                errors.extend(self.run(props[key], item, f"{path}.{key}", depth + 1, active_refs)[0])
            for pattern, sub_schema in patterns.items():
                if re.search(pattern, key):
                    matched = True
                    errors.extend(self.run(sub_schema, item, f"{path}.{key}", depth + 1, active_refs)[0])
            if matched:
                seen.add(key)
            elif "additionalProperties" in schema:
                seen.add(key)
                extra = schema["additionalProperties"]
                if extra is False:
                    errors.append(f"{path}: unknown property '{key}'")
                else:
                    errors.extend(self.run(extra, item, f"{path}.{key}", depth + 1, active_refs)[0])
            if "propertyNames" in schema:
                errors.extend(self.run(schema["propertyNames"], key, f"{path}.<name {key}>", depth + 1, active_refs)[0])

    def _array(
        self,
        schema: Dict[str, Any],
        value: List[Any],
        path: str,
        errors: List[str],
        depth: int = 0,
        active_refs: FrozenSet[Tuple[str, str, str]] = frozenset(),
    ) -> None:
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} item(s)")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errors.append(f"{path}: items must be unique")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(self.run(schema["items"], item, f"{path}[{i}]", depth + 1, active_refs)[0])


@lru_cache(maxsize=1)
def schemas() -> SchemaSet:
    return SchemaSet.load(SCHEMA_DIR)


def validate_document(document: Any) -> List[str]:
    if not isinstance(document, dict):
        return ["$: a sidecar must be an object"]
    kind = document.get("kind")
    name = f"{kind}.schema.json"
    if not isinstance(kind, str) or name not in schemas().documents:
        return [f"$.kind: {kind!r} is not a kind of the contract"]
    return schemas().validate(name, document)
