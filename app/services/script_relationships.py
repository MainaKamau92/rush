import posixpath
import re

SCRIPT_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
# Every pattern is linear: no two adjacent parts can match the same text.
COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
FROM = re.compile(r"""\bfrom[ \t]*["']([^"'\n]{1,300})["']""")
KEYWORD = re.compile(r"\b(?:import|export)\b")
DYNAMIC = re.compile(
    r"""\b(?:import|require)[ \t]*\([ \t]*["']([^"'\n]{1,300})["'][ \t]*\)"""
)
NAME = re.compile(r"[A-Za-z_$][\w$]*")
CLAUSE_LIMIT = 1000

# Resolved paths, imported names, line, and whether it is a dynamic import.
Binding = tuple[frozenset[str], frozenset[str], int, bool]


def is_script(path: str) -> bool:
    return path.endswith(SCRIPT_SUFFIXES)


def _blank(match: re.Match[str]) -> str:
    # Keep line numbers when removing a comment.
    return "\n" * match.group().count("\n")


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
        if "as" in words and words.index("as") + 1 < len(words):
            names.add(words[words.index("as") + 1])
        elif words[-1] != "*":
            names.add(words[-1])
    return frozenset(name for name in names if NAME.fullmatch(name) and name != "type")


def _imports(source_path: str, text: str) -> list[Binding]:
    code = COMMENT.sub(_blank, text)
    bindings = []
    for match in FROM.finditer(code):
        window = code[max(0, match.start() - CLAUSE_LIMIT) : match.start()]
        keywords = list(KEYWORD.finditer(window))
        if not keywords:
            continue
        clause = window[keywords[-1].end() :]
        if ";" in clause or "=" in clause:
            continue
        line = code.count("\n", 0, match.start(1)) + 1
        bindings.append(
            (_candidates(source_path, match[1]), _names(clause), line, False)
        )
    for match in DYNAMIC.finditer(code):
        line = code.count("\n", 0, match.start()) + 1
        bindings.append((_candidates(source_path, match[1]), frozenset(), line, True))
    return bindings


def _used(text: str, names: frozenset[str], skip: set[int]) -> bool:
    code = COMMENT.sub(_blank, text)
    for number, line in enumerate(code.splitlines(), start=1):
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
    relative import of the target that the changed lines use; or, for callers
    and tests, a target that imports the changed file, uses an imported name,
    and that name appears in the changed lines.
    """
    if relationship == "configuration":
        return False
    changed = "\n".join(source.splitlines()[start - 1 : end])
    if relationship in {"caller", "test"}:
        if target_source is None or not is_script(target):
            return False
        imports = _imports(target, target_source)
        lines = {line for _, _, line, _ in imports}
        return any(
            source_path in paths
            and (
                dynamic
                or (
                    bool(names)
                    and _used(target_source, names, lines)
                    and _used(changed, names, set())
                )
            )
            for paths, names, _, dynamic in imports
        )
    for paths, names, line, _ in _imports(source_path, source):
        if target not in paths:
            continue
        if start <= line <= end or _used(changed, names, set()):
            return True
    return False
