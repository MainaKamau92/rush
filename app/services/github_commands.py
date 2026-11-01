import re


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


def command_text(text: str, mentions: tuple[str, ...] = ("rush",)) -> str | None:
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
