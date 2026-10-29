import argparse
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

START = ("index.md", "current-state.md", "maintenance.md")
LINK = re.compile(r"\[[^\]\n]*\]\(([^\s)]+)\)")
FENCE = re.compile(r"^```[^\n]*\n.*?^```[^\n]*$", re.MULTILINE | re.DOTALL)


class KnowledgeError(ValueError):
    pass


def read_page(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    header, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise KnowledgeError("Unclosed frontmatter")
    metadata = yaml.safe_load(header)
    if not isinstance(metadata, dict):
        raise KnowledgeError("Frontmatter must be a mapping")
    return metadata, body


def linked_paths(path: Path, body: str, bundle: Path) -> set[Path]:
    targets = set()
    for match in LINK.findall(FENCE.sub("", body)):
        uri = urlsplit(match)
        if uri.scheme or uri.netloc or not uri.path:
            continue
        name = unquote(uri.path)
        target = (
            bundle / name.lstrip("/") if name.startswith("/") else path.parent / name
        )
        target = target.resolve()
        if not target.is_relative_to(bundle):
            raise KnowledgeError("Local links must stay inside the knowledge bundle")
        targets.add(target / "index.md" if target.is_dir() else target)
    return targets


def check_repo_source(source: dict[str, Any], root: Path) -> None:
    if "x_repo_path" not in source:
        return
    local = root / source["x_repo_path"]
    if not local.resolve().is_relative_to(root) or not local.is_file():
        raise KnowledgeError("Repository source missing or outside checkout")
    digest = hashlib.sha256(local.read_bytes()).hexdigest()
    if source.get("x_sha256") != digest:
        raise KnowledgeError(
            f"Source changed: {source['x_repo_path']}; refresh the summary and digest"
        )


def check_sources(
    metadata: dict[str, Any], root: Path, page: Path, bundle: Path
) -> None:
    sources = metadata.get("sources")
    if not isinstance(sources, list) or not sources:
        raise KnowledgeError("Concept needs sources")
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("resource"), str):
            raise KnowledgeError("Each source needs a resource")
        if not source["resource"].strip():
            raise KnowledgeError("Source resource must not be empty")
        resource = source["resource"]
        if resource.endswith(".md") and not urlsplit(resource).scheme:
            targets = linked_paths(page, f"[source]({resource})", bundle)
            if not targets or any(not target.is_file() for target in targets):
                raise KnowledgeError("Local source reference missing")
        check_repo_source(source, root)


def check_concept(
    metadata: dict[str, Any], root: Path, page: Path, bundle: Path
) -> None:
    for key in ("type", "title", "description"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise KnowledgeError(f"Concept needs a nonempty {key}")
    generated = metadata.get("generated", {})
    if not isinstance(generated, dict) or not generated.get("by"):
        raise KnowledgeError("Concept needs generated.by")
    at = datetime.fromisoformat(str(generated.get("at", "")))
    if at.tzinfo is None:
        raise KnowledgeError("generated.at needs a timezone")
    if metadata.get("status", "stable") not in ("draft", "stable", "deprecated"):
        raise KnowledgeError("Invalid concept status")
    check_sources(metadata, root, page, bundle)


def page_links(path: Path, root: Path, bundle: Path) -> set[Path]:
    metadata, body = read_page(path)
    if path.name == "index.md":
        expected = {"okf_version": "0.2"} if path == bundle / "index.md" else {}
        if metadata != expected:
            raise KnowledgeError("Index frontmatter must follow the OKF convention")
    elif path.name == "log.md":
        dates = re.findall(r"^## (.+)$", body, re.MULTILINE)
        if metadata or not dates or dates != sorted(dates, reverse=True):
            raise KnowledgeError("Log needs newest-first date headings and no metadata")
        for date in dates:
            datetime.strptime(date, "%Y-%m-%d")
    else:
        check_concept(metadata, root, path, bundle)
    return linked_paths(path, body, bundle)


def check_navigation(links: dict[Path, set[Path]], bundle: Path) -> list[str]:
    errors = []
    for path, targets in links.items():
        for target in targets:
            if not target.is_file():
                errors.append(
                    f"{path.relative_to(bundle)}: missing link target "
                    f"{target.relative_to(bundle)}"
                )
        if path != bundle / "index.md":
            directory = path.parent.parent if path.name == "index.md" else path.parent
            parent = directory / "index.md"
            if path not in links.get(parent, set()):
                errors.append(
                    f"{path.relative_to(bundle)}: missing from directory index"
                )
    return errors


def check(root: Path) -> list[str]:
    root = root.resolve()
    bundle = root / "knowledge"
    if bundle.is_symlink():
        return ["knowledge must be a directory inside the checkout, not a symlink"]
    errors = []
    for name in (*START, "log.md"):
        if not (bundle / name).is_file():
            errors.append(f"Missing knowledge/{name}")
    links: dict[Path, set[Path]] = {}
    for path in sorted(bundle.rglob("*")):
        label = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"{label}: symlinks are not allowed")
            continue
        if path.suffix != ".md":
            continue
        try:
            links[path] = page_links(path, root, bundle)
        except KnowledgeError as error:
            errors.append(f"{label}: invalid page: {error}")
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            errors.append(
                f"{label}: invalid page; check metadata, dates, sources and links"
            )
    return errors + check_navigation(links, bundle)


def main() -> int:
    parser = argparse.ArgumentParser(prog="knowledge")
    parser.add_argument("command", choices=("check", "context"))
    args = parser.parse_args()
    root = Path.cwd()
    errors = check(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    if args.command == "check":
        print("Knowledge checks passed")
        return 0
    print(
        "Read AGENTS.md first. "
        "Recorded state must be checked against live Git/PR state."
    )
    for name in START:
        print(f"\n--- knowledge/{name} ---\n")
        print((root / "knowledge" / name).read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
