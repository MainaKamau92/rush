import asyncio
import contextlib
import os
import re
from pathlib import Path

from app.core.errors import ChangeError, MissingObjectError
from app.models.code_change import RepositoryFile, TreeChange
from app.models.repository_path import safe_repository_path
from app.provider.repository.abstract import CodeRepositoryAbstract

ZERO_OBJECT = re.compile(r"0+")
# Repository-local config is still read by Git, so every setting that could run
# a helper, fetch objects or reshape diff output is overridden on each call.
SAFE_OPTIONS = (
    "--no-pager",
    "--literal-pathspecs",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.quotePath=false",
    "-c",
    "protocol.allow=never",
    "-c",
    "diff.suppressBlankEmpty=false",
)
COMPARE_OPTIONS = (
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--text",
    "--unified=3",
    "--inter-hunk-context=0",
    "--diff-algorithm=myers",
    "--indent-heuristic",
)


def safe_environment() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }


class GitRepositoryAdapter(CodeRepositoryAbstract):
    def __init__(
        self, repository: Path, executable: str, timeout_seconds: float = 30
    ) -> None:
        self._repository = repository
        self._executable = executable
        self._timeout = timeout_seconds
        self._git_dir: str | None = None
        self._environment = safe_environment()

    async def commit(self, revision: str) -> str:
        code, output = await self._git(
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{revision}^{{commit}}",
        )
        if code != 0:
            raise ChangeError(
                f"Version {revision!r} is not available in the repository"
            )
        return output.decode().strip()

    async def merge_base(self, target: str, head: str) -> str:
        code, output = await self._git("merge-base", target, head)
        if code != 0:
            raise ChangeError("The target and head have no shared starting point")
        return output.decode().strip()

    async def changes(self, base: str, head: str) -> list[TreeChange]:
        code, output = await self._git(
            "diff-tree", "-r", "-z", "--no-abbrev", "--find-renames", base, head
        )
        if code != 0:
            raise ChangeError("Git could not list the changed files")
        return _tree_changes(output)

    async def blob(self, object_id: str, limit: int) -> bytes | None:
        code, size = await self._git("cat-file", "-s", object_id)
        if code != 0:
            raise MissingObjectError(object_id)
        if int(size) > limit:
            return None
        code, content = await self._git("cat-file", "blob", object_id)
        if code != 0:
            raise MissingObjectError(object_id)
        return content

    async def compare(self, old_object: str, new_object: str) -> str:
        code, output = await self._git("diff", *COMPARE_OPTIONS, old_object, new_object)
        if code != 0:
            raise ChangeError("Git could not compare a changed file")
        return output.decode(errors="surrogateescape")

    async def file(self, commit: str, path: str, limit: int) -> RepositoryFile:
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
            raise ChangeError("Related reads require a frozen commit ID")
        if not safe_repository_path(path):
            raise ChangeError("Related path must stay inside this repository")
        code, output = await self._git("ls-tree", "-z", commit, "--", path)
        if code != 0 or not output:
            raise MissingObjectError("Related file is unavailable at the frozen head")
        header, name = output.rstrip(b"\0").split(b"\t", 1)
        mode, _, object_id = header.decode().split(" ")
        if name.decode(errors="surrogateescape") != path:
            raise ChangeError("Git returned a different related path")
        content = None
        if mode in {"100644", "100755"}:
            content = await self.blob(object_id, limit)
        return RepositoryFile(path, object_id, mode, content)

    async def _git(self, *arguments: str) -> tuple[int, bytes]:
        if self._git_dir is None:
            self._git_dir = await self._locate()
        return await self._run(
            self._git_dir, *SAFE_OPTIONS, f"--git-dir={self._git_dir}", *arguments
        )

    async def _locate(self) -> str:
        environment = self._environment | {
            "GIT_CEILING_DIRECTORIES": str(self._repository.parent)
        }
        code, output = await self._run(
            str(self._repository),
            *SAFE_OPTIONS,
            "rev-parse",
            "--path-format=absolute",
            "--git-dir",
            environment=environment,
        )
        if code != 0:
            raise ChangeError(
                "The path is not a Git repository Rush can read; check its location "
                "and ownership"
            )
        return output.decode(errors="surrogateescape").strip()

    async def _run(
        self,
        directory: str,
        *arguments: str,
        environment: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        return await run_git(
            self._executable,
            directory,
            arguments,
            environment or self._environment,
            self._timeout,
        )


async def run_git(
    executable: str,
    directory: str,
    arguments: tuple[str, ...],
    environment: dict[str, str],
    timeout: float,
) -> tuple[int, bytes]:
    process = await asyncio.create_subprocess_exec(
        executable,
        *arguments,
        cwd=directory,
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(timeout):
            output, _ = await process.communicate()
    except BaseException as error:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        if isinstance(error, TimeoutError):
            raise ChangeError(
                "Git did not respond in time; nothing was read"
            ) from error
        raise
    return int(process.returncode or 0), output


def _object(value: bytes) -> str | None:
    text = value.decode()
    return None if ZERO_OBJECT.fullmatch(text) else text


def _tree_changes(output: bytes) -> list[TreeChange]:
    fields = output.split(b"\0")
    changes: list[TreeChange] = []
    index = 0
    while index < len(fields) and fields[index]:
        old_mode, new_mode, old_object, new_object, status = (
            fields[index].lstrip(b":").split(b" ")
        )
        kind = status[:1].decode()
        paths = [
            field.decode(errors="surrogateescape")
            for field in fields[index + 1 : index + 3]
        ]
        if kind in {"R", "C"}:
            old_path, new_path = paths
            index += 3
        else:
            old_path = new_path = paths[0]
            index += 2
        changes.append(
            TreeChange(
                status=kind,
                old_mode=old_mode.decode(),
                new_mode=new_mode.decode(),
                old_object=_object(old_object),
                new_object=_object(new_object),
                old_path=None if kind == "A" else old_path,
                new_path=None if kind == "D" else new_path,
                similarity=int(status[1:]) if kind in {"R", "C"} else None,
            )
        )
    return changes
