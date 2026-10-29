
import ast
import builtins
import pathlib

from tests.helpers.guard_fold import assert_no_offenders

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
BUILTINS = set(dir(builtins))

MODULE_DUNDERS = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__path__",
}


def _collect_bindings(tree: ast.AST) -> set:
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            args = getattr(node, "args", None)
            if args is not None:
                for a in (
                    list(args.args)
                    + list(args.posonlyargs)
                    + list(args.kwonlyargs)
                    + [args.vararg, args.kwarg]
                ):
                    if a is not None:
                        bound.add(a.arg)
        elif isinstance(node, ast.Lambda):
            a = node.args
            for x in (
                list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs)
                + [a.vararg, a.kwarg]
            ):
                if x is not None:
                    bound.add(x.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
    return bound


def _unresolved(path: pathlib.Path) -> list:
    tree = ast.parse(path.read_text(), filename=str(path))
    bound = _collect_bindings(tree) | BUILTINS | MODULE_DUNDERS
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in bound:
                bad.append((node.id, node.lineno))
    return bad


ALL_SOURCES = sorted(SRC.rglob("*.py"))


def _check_bound(path: pathlib.Path) -> None:
    bad = _unresolved(path)
    assert not bad, (
        "name(s) used but bound nowhere in the file - "
        + ", ".join(f"{n!r} (line {ln})" for n, ln in bad)
        + ". This is a NameError that no syntax check can see."
    )


def test_every_loaded_name_is_bound_somewhere():
    assert_no_offenders(
        "every loaded name is bound", ALL_SOURCES, _check_bound,
        label=lambda p: str(p.relative_to(SRC.parent)),
    )


def test_the_check_can_actually_fail():
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write("def f():\n    return not_bound_anywhere(1)\n")
        tmp = pathlib.Path(fh.name)
    try:
        bad = _unresolved(tmp)
        assert [n for n, _ in bad] == ["not_bound_anywhere"]
    finally:
        tmp.unlink()
