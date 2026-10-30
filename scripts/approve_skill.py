import argparse
import asyncio
import json
from pathlib import Path

from app.core.errors import SkillError
from app.dependencies import build_skill_catalog, build_skill_store
from app.services.review_skills import package_digest

ROOT = Path(__file__).resolve().parents[1]


async def approve(skill_ids: list[str]) -> None:
    approved_path = ROOT / "skills/approved.json"
    previous = approved_path.read_text()
    approved = json.loads(previous)
    store = build_skill_store(ROOT / "skills")
    entries = {entry["id"]: entry for entry in approved["skills"]}
    for skill_id in skill_ids:
        if skill_id not in entries:
            raise SkillError(f"Add {skill_id} to skills/approved.json first")
        entry = entries[skill_id]
        entry["digest"] = package_digest(await store.package(entry["package"]))
    approved_path.write_text(json.dumps(approved, indent=2) + "\n")
    try:
        await build_skill_catalog(ROOT / "skills").load()
    except SkillError:
        approved_path.write_text(previous)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pin the current contents of approved skill packages"
    )
    parser.add_argument("--skill", action="append", required=True, dest="skills")
    try:
        asyncio.run(approve(parser.parse_args().skills))
    except SkillError as error:
        print(f"Skill approval failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
