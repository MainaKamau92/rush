from typing import Any

from app.schemas.review import Finding, ReviewRecord

EXCERPT_LINES = 200
WINDOW = 20


def excerpts(record: ReviewRecord, finding: Finding) -> dict[str, Any]:
    sources = {
        source.id: source
        for source in (*record.inputs.sources, *record.progress.result.context_sources)
    }
    found: dict[str, Any] = {}
    for ref in (*finding.evidence, *finding.causal_path):
        source = sources.get(ref.source_id)
        if source is None or source.excerpt is None or ref.source_id in found:
            continue
        lines = source.excerpt.splitlines()
        first = max(1, ref.start - WINDOW)
        last = min(len(lines), ref.end + WINDOW, first + EXCERPT_LINES - 1)
        found[ref.source_id] = {
            "reference": source.reference,
            "cited": [ref.start, ref.end],
            "lines": {
                str(number): lines[number - 1] for number in range(first, last + 1)
            },
        }
    return found
