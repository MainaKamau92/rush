import ast
from collections import Counter
from collections.abc import Iterator
from pathlib import PurePosixPath

from app.schemas.investigation import Relationship

Binding = tuple[str, tuple[str, ...], str | None]


def _module_paths(module: str, package: PurePosixPath) -> tuple[str, ...]:
    path = package / module.replace(".", "/")
    return (str(path.with_suffix(".py")), str(path / "__init__.py"))


def _imports(tree: ast.Module, source_path: str) -> list[Binding]:
    bindings: list[Binding] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "." in alias.name and alias.asname is None:
                    continue
                bindings.append(
                    (
                        alias.asname or alias.name.split(".")[0],
                        _module_paths(alias.name, PurePosixPath()),
                        None,
                    )
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            package = PurePosixPath()
            if node.level:
                package = PurePosixPath(source_path).parent
                if node.level > len(package.parts):
                    continue
                for _ in range(node.level - 1):
                    package = package.parent
            for alias in node.names:
                bindings.append(
                    (
                        alias.asname or alias.name,
                        (
                            *_module_paths(node.module, package),
                            *_module_paths(f"{node.module}.{alias.name}", package),
                        ),
                        alias.name,
                    )
                )
    counts = Counter(binding[0] for binding in bindings)
    global_assignments = _assigned(
        [
            node
            for node in tree.body
            if not isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            )
        ]
    )
    global_assignments.update(
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    )
    return [
        binding
        for binding in bindings
        if "*" not in global_assignments
        and counts[binding[0]] == 1
        and binding[0] not in global_assignments
    ]


def _relevant(tree: ast.Module, start: int, end: int) -> list[ast.AST]:
    selected: list[ast.AST] = []
    pending = list(tree.body)
    while pending:
        node = pending.pop(0)
        if node.lineno > end or (node.end_lineno or node.lineno) < start:
            continue
        if isinstance(node, ast.ClassDef):
            pending.extend(node.body)
            if start <= node.lineno <= end:
                selected.extend(node.bases)
        else:
            selected.append(node)
    return selected


def _calls(nodes: list[ast.AST]) -> set[tuple[str, str | None]]:
    calls: set[tuple[str, str | None]] = set()
    for node in nodes:
        for item in _scoped_walk(node):
            if not isinstance(item, ast.Call):
                continue
            if isinstance(item.func, ast.Name):
                calls.add((item.func.id, None))
            elif isinstance(item.func, ast.Attribute) and isinstance(
                item.func.value, ast.Name
            ):
                calls.add((item.func.value.id, item.func.attr))
    return calls


def _configuration(
    tree: ast.Module, nodes: list[ast.AST], source_path: str, target: str
) -> bool:
    imports = _imports(tree, source_path)
    assigned = _assigned(list(tree.body))
    if "*" in assigned:
        return False
    names = (
        {"open"}
        - assigned
        - {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }
    )
    if any(local == "open" for local, _, _ in imports):
        names.discard("open")
    if any(
        local == "Path" and "pathlib.py" in paths and symbol == "Path"
        for local, paths, symbol in imports
    ):
        names.add("Path")
    names -= _assigned(nodes)
    for root in nodes:
        for node in _scoped_walk(root):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            value = node.args[0]
            if (
                name in names
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and PurePosixPath(target).suffix
                in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
                and target
                in {value.value, str(PurePosixPath(source_path).parent / value.value)}
            ):
                return True
    return False


def verifies_relationship(
    source_path: str,
    source: str,
    target: str,
    relationship: Relationship,
    start: int,
    end: int,
    target_source: str | None = None,
) -> bool:
    if not source_path.endswith(".py"):
        return False
    try:
        tree = ast.parse(source)
        nodes = _relevant(tree, start, end)
        if relationship == "configuration":
            return _configuration(tree, nodes, source_path, target)
        if relationship in {"caller", "test"}:
            return _reverse_link(tree, nodes, source_path, target, target_source)
        return _forward_link(tree, nodes, source_path, target, relationship)
    except (SyntaxError, ValueError, RecursionError):
        return False


def _forward_link(
    tree: ast.Module,
    nodes: list[ast.AST],
    source_path: str,
    target: str,
    relationship: Relationship,
) -> bool:
    used = {
        item.id
        for root in nodes
        for item in _scoped_walk(root)
        if isinstance(item, ast.Name)
    }
    calls = _calls(nodes)
    for local, paths, _ in _imports(tree, source_path):
        if (
            target in paths
            and local in used
            and local not in _assigned(nodes)
            and (relationship != "callee" or any(name == local for name, _ in calls))
        ):
            return True
    if relationship == "callee" and source_path == target:
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        return any(name in functions - _assigned(nodes) for name, _ in calls)
    return False


def _reverse_link(
    source_tree: ast.Module,
    nodes: list[ast.AST],
    source_path: str,
    target: str,
    target_source: str | None,
) -> bool:
    if target_source is None or not target.endswith(".py"):
        return False
    exports = {
        node.name
        for node in nodes
        if node in source_tree.body
        and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    tree = ast.parse(target_source)
    calls = _calls(list(tree.body))
    for local, paths, symbol in _imports(tree, target):
        if source_path not in paths:
            continue
        if local in _assigned(list(tree.body)):
            continue
        if symbol in exports and (local, None) in calls:
            return True
        if symbol is None and any((local, name) in calls for name in exports):
            return True
    return False


def _assigned(nodes: list[ast.AST]) -> set[str]:
    result = set()
    for root in nodes:
        for node in _scoped_walk(root):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                result.add(node.id)
            elif isinstance(node, ast.arg):
                result.add(node.arg)
            elif (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and node is not root
            ):
                result.add(node.name)
            elif isinstance(node, ast.Import | ast.ImportFrom) and (
                node is not root or any(alias.name == "*" for alias in node.names)
            ):
                result.update(
                    alias.asname or alias.name.split(".")[0] for alias in node.names
                )
            elif (
                isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar)
                and node.name
            ):
                result.add(node.name)
    return result


def _scoped_walk(root: ast.AST) -> Iterator[ast.AST]:
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        if node is root or not isinstance(
            node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda
        ):
            pending.extend(ast.iter_child_nodes(node))
