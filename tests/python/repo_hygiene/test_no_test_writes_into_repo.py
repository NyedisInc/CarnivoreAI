import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[2]
ALLOWED = {
    "test_state_dir_resolution.py",
}
ROOT_NAMES = {"REPO", "ROOT", "REPO_ROOT", "PROJECT_ROOT", "CLIENT", "WEB", "SRC"}
METHODS = {"write_text", "write_bytes", "unlink", "touch", "mkdir", "rmdir", "rename"}
PATH_STEPS = {"joinpath", "resolve", "with_name", "with_suffix", "expanduser"}
CALLS = {
    "shutil": {"copy": (1,), "copy2": (1,), "copyfile": (1,), "copytree": (1,), "move": (0, 1), "rmtree": (0,)},
    "os": {"remove": (0,), "unlink": (0,), "rename": (0, 1), "makedirs": (0,), "rmdir": (0,)},
}
WRITE_MODE_CHARS = set("wax+")
PREFILTER = ("open(", *(f"{mod}.{fn}" for mod, fns in CALLS.items() for fn in fns), *(f".{m}(" for m in METHODS))


def _pathy(node: ast.AST, tainted: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _pathy(node.left, tainted)
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        return _pathy(node.value, tainted)
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in PATH_STEPS:
            return _pathy(func.value, tainted)
        if isinstance(func, ast.Name) and func.id in {"Path", "PurePath"}:
            return any(_pathy(arg, tainted) for arg in node.args)
    return False


def _write_mode(call: ast.Call, position: int) -> bool:
    mode = call.args[position] if len(call.args) > position else None
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = kw.value
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and bool(WRITE_MODE_CHARS & set(mode.value))


def _mutates_repo(call: ast.Call, tainted: set[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr in METHODS and _pathy(func.value, tainted):
            return True
        if func.attr == "open" and _pathy(func.value, tainted):
            return _write_mode(call, 0)
        if isinstance(func.value, ast.Name):
            for index in CALLS.get(func.value.id, {}).get(func.attr, ()):
                if len(call.args) > index and _pathy(call.args[index], tainted):
                    return True
    if isinstance(func, ast.Name) and func.id == "open" and call.args and _pathy(call.args[0], tainted):
        return _write_mode(call, 1)
    return False


def repo_writes(source: str) -> list[int]:
    tree = ast.parse(source)
    tainted = set(ROOT_NAMES)
    nodes = list(ast.walk(tree))
    assigns = [n for n in nodes if isinstance(n, ast.Assign)]
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if _pathy(node.value, tainted):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in tainted:
                        tainted.add(target.id)
                        changed = True
    return sorted(n.lineno for n in nodes if isinstance(n, ast.Call) and _mutates_repo(n, tainted))


RED_CASES = {
    "write_text through a variable": 'p = REPO / "a"\np.write_text("x")\n',
    "unlink on a direct path": '(ROOT / "a").unlink()\n',
    "open() for write": 'open(REPO / "a", "w")\n',
    "open() mode keyword": 'open(REPO / "a", mode="ab")\n',
    "Path.open for write": '(REPO / "a").open("w")\n',
    "shutil.copy destination": 'shutil.copy("src", REPO / "a")\n',
    "shutil.copytree destination": 'shutil.copytree("src", ROOT / "a")\n',
    "shutil.move source": 'shutil.move(REPO / "a", "dst")\n',
    "shutil.rmtree": 'shutil.rmtree(REPO / "a")\n',
    "os.remove": 'os.remove(REPO / "a")\n',
    "os.rename": 'os.rename("src", ROOT / "a")\n',
    "os.makedirs": 'os.makedirs(REPO / "a")\n',
    "Path(REPO, ...)": 'Path(REPO, "a").write_text("x")\n',
    "Path(REPO) / x": '(Path(REPO) / "a").touch()\n',
}
GREEN_CASES = {
    "tmp_path write": 'p = tmp_path / "z"\np.write_text("x")\n',
    "open() for read": 'open(REPO / "a")\nopen(REPO / "a", "r")\n',
    "Path.open for read": '(REPO / "a").open("rb")\n',
    "shutil.copy source only": 'shutil.copy(REPO / "a", tmp_path / "b")\n',
    "os.remove under tmp_path": 'os.remove(tmp_path / "a")\n',
    "str.replace on repo text": 'text = (REPO / "a").read_text().replace("x", "y")\n',
    "Path(__file__) is not a seed": 'HERE = Path(__file__).parent\n(HERE / "a").write_text("x")\n',
}


def test_check_can_go_red() -> None:
    missed = [name for name, src in RED_CASES.items() if not repo_writes(src)]
    assert missed == [], f"the check went green on: {missed}"
    flagged = [name for name, src in GREEN_CASES.items() if repo_writes(src)]
    assert flagged == [], f"the check went red on a safe shape: {flagged}"


def test_no_test_writes_into_the_repo() -> None:
    files = [p for p in TESTS.rglob("*.py") if p.name != Path(__file__).name]
    assert len(files) > 500, "the scan looked at almost nothing"
    found = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        if not any(word in text for word in PREFILTER) or not any(name in text for name in ROOT_NAMES):
            continue
        try:
            lines = repo_writes(text)
        except SyntaxError:
            continue
        rel = path.relative_to(TESTS).as_posix()
        if lines and rel not in ALLOWED:
            found[rel] = lines
    assert found == {}
