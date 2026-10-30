import asyncio
import os
import stat
from pathlib import Path

from app.core.errors import SkillError
from app.models.skill import PackageFile
from app.provider.skills.abstract import SkillStoreAbstract

MAX_FILE_BYTES = 262_144


def _component(name: str) -> str:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\0" in name:
        raise SkillError("Skill storage names must be single path components")
    return name


def _read(path: Path) -> bytes:
    with path.open("rb") as file:
        content = file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise SkillError(f"Skill file exceeds {MAX_FILE_BYTES} bytes: {path.name}")
    return content


class SkillFileAdapter(SkillStoreAbstract):
    def __init__(self, root: Path) -> None:
        self._root = root

    async def approved(self) -> bytes:
        return await asyncio.to_thread(self._approved)

    def _approved(self) -> bytes:
        path = self._root / "approved.json"
        if path.is_symlink() or not path.is_file():
            raise SkillError("Approved skill list is missing")
        return _read(path)

    async def package(self, name: str) -> tuple[PackageFile, ...]:
        return await asyncio.to_thread(self._package, _component(name))

    def _package(self, name: str) -> tuple[PackageFile, ...]:
        directory = self._root / name
        if directory.is_symlink() or not directory.is_dir():
            raise SkillError(f"Skill package is missing: {name}")
        files = []
        with os.scandir(directory) as entries:
            for entry in entries:
                mode = entry.stat(follow_symlinks=False).st_mode
                regular = stat.S_ISREG(mode)
                files.append(
                    PackageFile(
                        name=entry.name,
                        content=_read(Path(entry.path)) if regular else b"",
                        regular=regular,
                        executable=bool(mode & 0o111) and regular,
                    )
                )
        return tuple(sorted(files, key=lambda item: item.name))

    async def evaluation(self, name: str) -> bytes | None:
        return await asyncio.to_thread(self._evaluation, _component(name))

    def _evaluation(self, name: str) -> bytes | None:
        path = self._root / "evaluations" / name
        if path.is_symlink():
            raise SkillError("Skill evaluations must be regular files")
        return _read(path) if path.is_file() else None

    async def save_evaluation(self, name: str, content: bytes) -> None:
        await asyncio.to_thread(self._save, _component(name), content)

    def _save(self, name: str, content: bytes) -> None:
        directory = self._root / "evaluations"
        directory.mkdir(exist_ok=True)
        temporary = directory / f".{name}.tmp"
        temporary.write_bytes(content)
        temporary.replace(directory / name)
