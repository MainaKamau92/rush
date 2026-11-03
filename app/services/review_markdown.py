import re
from collections.abc import Mapping

from app.schemas.code_change import Hunk
from app.schemas.review import EvidenceRef, Finding, FindingPresentation

MENTION = re.compile(r"(?<![A-Za-z0-9_])@(?=[A-Za-z0-9])", re.ASCII)
INLINE = re.compile(r"(`+)(?!`)([^\n]*?)(?<!`)\1(?!`)")
OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})([A-Za-z0-9_+-]*)[ \t]*$")
SYMBOL = re.compile(
    r"(?<![\w])(?:[A-Za-z_]\w*\([^()\n]{0,160}\)|"
    r"[A-Za-z_]\w*_[A-Za-z0-9_]+|"
    r"[A-Za-z_][\w/.-]*\.(?:py|js|ts|tsx|jsx|go|rs|java|json|ya?ml|sql|sh))"
    r"(?![\w])"
)


def safe_text(text: str) -> str:
    text = MENTION.sub("@\u200b", text.replace("<", "&lt;"))
    return text.replace("![", "!\\[")


def code(text: str) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    text = text.replace("<!-- rush:", "<\u200b!-- rush:")
    delimiter = "`" * (
        max((len(run) for run in re.findall(r"`+", text)), default=0) + 1
    )
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{delimiter}{padding}{text}{padding}{delimiter}"


def _prose(text: str) -> str:
    chunks: list[str] = []
    end = 0
    for match in SYMBOL.finditer(text):
        chunks.extend(
            (
                safe_text(text[end : match.start()].replace("\\", "\\\\"))
                .replace("`", "\\`")
                .replace("~", "\\~"),
                code(match[0]),
            )
        )
        end = match.end()
    return "".join(
        (
            *chunks,
            safe_text(text[end:].replace("\\", "\\\\"))
            .replace("`", "\\`")
            .replace("~", "\\~"),
        )
    )


def _inline(text: str) -> str:
    chunks: list[str] = []
    end = 0
    for match in INLINE.finditer(text):
        chunks.extend((_prose(text[end : match.start()]), code(match[2])))
        end = match.end()
    return "".join((*chunks, _prose(text[end:])))


def markdown(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    result: list[str] = []
    index = 0
    while index < len(lines):
        opening = OPEN.fullmatch(lines[index])
        closing = (
            next(
                (
                    position
                    for position in range(index + 1, len(lines))
                    if opening
                    and re.fullmatch(
                        r" {0,3}"
                        + re.escape(opening[1][0])
                        + "{"
                        + str(len(opening[1]))
                        + r",}[ \t]*",
                        lines[position],
                    )
                ),
                None,
            )
            if opening
            else None
        )
        if opening and closing is not None:
            content = "\n".join(lines[index + 1 : closing]).replace(
                "<!-- rush:", "<\u200b!-- rush:"
            )
            delimiter = "`" * max(
                3, max((len(run) + 1 for run in re.findall(r"`+", content)), default=3)
            )
            language = "text" if opening[2].lower() == "suggestion" else opening[2]
            result.extend((delimiter + language, content, delimiter))
            index = closing + 1
        else:
            result.append(_inline(lines[index]))
            index += 1
    return "\n".join(result)


DiffSources = Mapping[str, tuple[str, str, Hunk]]


def evidence_line(
    item: EvidenceRef, hunks: DiffSources | None = None, side: str = "RIGHT"
) -> str:
    """Show diff evidence as file lines; the model cites passage-relative lines."""
    old_path, new_path, hunk = (hunks or {}).get(item.source_id, ("", "", None))
    if hunk is not None:
        lines = hunk.lines[item.start - 1 : item.end]
        new = ("new", new_path, [line.new_line for line in lines if line.new_line])
        old = ("old", old_path, [line.old_line for line in lines if line.old_line])
        for version, path, numbers in (old, new) if side == "LEFT" else (new, old):
            if numbers:
                first, last = min(numbers), max(numbers)
                span = f"lines {first}–{last}" if first != last else f"line {first}"
                return f"{code(path)} {span} ({version} version)"
    return f"{code(item.source_id)} lines {item.start}–{item.end}"


def finding_comment(
    finding: Finding,
    presentation: FindingPresentation | None,
    hunks: DiffSources | None = None,
) -> str:
    wording = presentation.wording if presentation else None
    problem = wording.problem if wording else finding.problem
    consequence = wording.consequence if wording else finding.consequence
    remediation = wording.remediation if wording else finding.remediation
    example = wording.example if wording else finding.trigger_scenario
    connection = wording.connection if wording else ""
    short = presentation is None or presentation.settings.verbosity == "short"
    lines = [
        f"**{finding.severity.title()} · {safe_text(finding.category)}** — "
        + code(f"{finding.anchor.path}:{finding.anchor.line}"),
        "",
        "\n\n".join(
            dict.fromkeys(
                markdown(text) for text in (problem, connection, consequence) if text
            )
        ),
        "",
        "**Suggested fix:**",
        "",
        markdown(remediation),
        "",
    ]
    details = ["**Example:**", "", markdown(example), "", "**Evidence:**", ""]
    details += [
        f"- {evidence_line(item, hunks, finding.anchor.side)}"
        for item in finding.evidence
    ]
    rule = (
        f"{finding.rule_ref.id}@{finding.rule_ref.version}"
        if finding.rule_ref
        else "none"
    )
    details += [
        "",
        f"**Rule:** {code(rule)} · **Skill:** "
        + code(f"{finding.skill.id}@{finding.skill.version}"),
    ]
    if finding.assumptions:
        details += [
            "",
            "**Assumptions:**",
            "",
            "\n\n".join(markdown(item) for item in finding.assumptions),
        ]
    if short:
        lines += [
            "<details>",
            "<summary>Example and evidence</summary>",
            "",
            *details,
            "",
            "</details>",
        ]
    else:
        lines += details
    return "\n".join(lines)
