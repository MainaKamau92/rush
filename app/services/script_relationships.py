import posixpath
import re

SCRIPT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
STATIC = re.compile(
    r"""^\s*(?:import|export)\s+(?:type\s+)?(?P<clause>[\w$*{},\s]+?)\s+from\s+["'](?P<spec>[^"']+)["']""",
    re.MULTILINE,
)
DYNAMIC = re.compile(r"""(?:import|require)\s*\(\s*["'](?P<spec>[^"']+)["']\s*\)""")
NAME = re.compile(r"[A-Za-z_$][\w$]*")

Binding = tuple[frozenset[str], frozenset[str], int]


def is_script(path: str) -> bool:
    return path.endswith(SCRIPT_SUFFIXES)


def _candidates(source_path: str, spec: str) -> frozenset[str]:
    if not spec.startswith("."):
        return frozenset()
    base = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), spec))
    if base.startswith(".."):
        return frozenset()
    stems = [base]
    if base.endswith((".js", ".jsx", ".mjs", ".cjs")):
        # TypeScript ESM imports name the compiled file.
        stems.append(base.rsplit(".", 1)[0])
    paths = {base}
    for stem in stems:
        for suffix in SCRIPT_SUFFIXES:
            paths.add(stem + suffix)
            paths.add(f"{stem}/index{suffix}")
    return frozenset(paths)


def _names(clause: str) -> frozenset[str]:
    names = set()
    for part in re.split(r"[{},]", clause):
        words = part.split()
        if not words or words == ["type"]:
            continue
        if "as" in words:
            names.add(words[words.index("as") + 1])
        elif words[-1] != "*":
            names.add(words[-1])
    return frozenset(name for name in names if NAME.fullmatch(name))


def _imports(source_path: str, text: str) -> list[Binding]:
    bindings = []
    for match in STATIC.finditer(text):
        line = text.count("\n", 0, match.start("spec")) + 1
        bindings.append(
            (
                _candidates(source_path, match["spec"]),
                _names(match["clause"]),
                line,
            )
        )
    for match in DYNAMIC.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        bindings.append((_candidates(source_path, match["spec"]), frozenset(), line))
    return bindings


def _used(text: str, names: frozenset[str], skip: set[int]) -> bool:
    for number, line in enumerate(text.splitlines(), start=1):
        if number not in skip and names & set(NAME.findall(line)):
            return True
    return False


def verifies_script_link(
    source_path: str,
    source: str,
    target: str,
    relationship: str,
    start: int,
    end: int,
    target_source: str | None = None,
) -> bool:
    """
    A TypeScript or JavaScript link from the changed lines to the target: a
    relative import of the target that the changed lines use, or, for callers
    and tests, a target that imports the changed file and uses what it imports.
    """
    if relationship == "configuration":
        return False
    if relationship in {"caller", "test"}:
        if target_source is None or not is_script(target):
            return False
        imports = _imports(target, target_source)
        lines = {line for _, _, line in imports}
        return any(
            source_path in paths and (not names or _used(target_source, names, lines))
            for paths, names, _ in imports
        )
    changed = "\n".join(source.splitlines()[start - 1 : end])
    for paths, names, line in _imports(source_path, source):
        if target not in paths:
            continue
        if start <= line <= end or _used(changed, names, set()):
            return True
    return False
