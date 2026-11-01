import re

from app.schemas.review import PresentationSettings


def review_settings(
    text: str, defaults: PresentationSettings | None = None
) -> PresentationSettings | None:
    words = text.splitlines()[0].lower().split() if text.splitlines() else []
    if words[:2] != ["/rush", "review"]:
        return None
    chosen = (defaults or PresentationSettings()).model_dump()
    seen = set()
    for word in words[2:]:
        key, separator, value = word.partition("=")
        allowed = {
            "complexity": {"plain", "technical"},
            "verbosity": {"short", "detailed"},
        }
        if not separator or key in seen or value not in allowed.get(key, set()):
            return None
        chosen[key] = value
        seen.add(key)
    return PresentationSettings(**chosen)


def _plain(text: str) -> str:
    lines = []
    fence = ""
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        expanded = line.expandtabs(4)
        indented = len(expanded) - len(expanded.lstrip(" ")) >= 4
        marker = re.match(r"(`{3,}|~{3,})", stripped) if not indented else None
        hidden = bool(fence or indented or stripped.startswith(">") or marker)
        if marker and not stripped.startswith(">"):
            token = marker[0]
            if not fence:
                fence = token
            elif (
                token[0] == fence[0]
                and len(token) >= len(fence)
                and not stripped[marker.end() :].strip()
            ):
                fence = ""
        lines.append(re.sub(r"[^\n]", " ", line) if hidden else line)
    plain = "".join(lines)
    return re.sub(
        r"(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)",
        lambda match: re.sub(r"[^\n]", " ", match[0]),
        plain,
    )


def command_text(
    text: str, mentions: tuple[str, ...] = ("rush-reviewer",)
) -> str | None:
    aliases = "|".join(re.escape(name) for name in mentions if name)
    prefix = rf"(?<![\w@])@(?:{aliases})(?:\[bot\])?(?![\w-])"
    pattern = rf"(?m:^[ \t]*/rush(?![\w-]))|{prefix}"
    plain = _plain(text)
    for match in re.finditer(pattern, plain, re.IGNORECASE):
        rest = text[match.end() :]
        if "@" in match[0] and re.match(r"[ \t]*(?:\n|$)", rest):
            return "/rush review" + rest
        if re.match(r"[ \t]+[a-z]", plain[match.end() :], re.IGNORECASE):
            return "/rush" + rest
    return None
