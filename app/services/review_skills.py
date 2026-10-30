import hashlib
import re
from collections.abc import Iterable

from pydantic import ValidationError

from app.core.errors import SkillError
from app.models.skill import PackageFile
from app.provider.skills.abstract import SkillStoreAbstract
from app.schemas.review import VersionPin
from app.schemas.skill import (
    ApprovedSkill,
    ApprovedSkills,
    EvaluatedModel,
    InstalledSkill,
    ModelProfile,
    SkillEvaluation,
    SkillExamples,
    SkillManifest,
)
from app.services.model_review import protocol_sha256


def package_digest(files: Iterable[PackageFile]) -> str:
    digest = hashlib.sha256()
    for file in sorted(files, key=lambda item: item.name):
        digest.update(file.name.encode() + b"\0")
        digest.update(hashlib.sha256(file.content).hexdigest().encode() + b"\n")
    return digest.hexdigest()


def evaluation_name(pin: VersionPin) -> str:
    return f"{pin.id}@{pin.version}.json"


def _pattern(glob: str) -> re.Pattern[str]:
    expression = ""
    for token in re.split(r"(\*\*/|\*\*|\*|\?)", glob):
        expression += {
            "**/": "(?:.*/)?",
            "**": ".*",
            "*": "[^/]*",
            "?": "[^/]",
        }.get(token, re.escape(token))
    return re.compile(expression)


def path_matches(glob: str, path: str) -> bool:
    return _pattern(glob).fullmatch(path) is not None


class SkillCatalog:
    def __init__(self, approved: ApprovedSkills, skills: tuple[InstalledSkill, ...]):
        self.approved, self.skills = approved, skills

    @property
    def active(self) -> tuple[InstalledSkill, ...]:
        return tuple(skill for skill in self.skills if skill.active)

    def get(self, skill_id: str) -> InstalledSkill:
        for skill in self.skills:
            if skill.pin.id == skill_id:
                return skill
        raise SkillError(f"Skill is not approved: {skill_id}")

    def select(
        self,
        paths: Iterable[str],
        skills: tuple[InstalledSkill, ...] | None = None,
    ) -> tuple[InstalledSkill, ...]:
        changed = tuple(paths)
        return tuple(
            skill
            for skill in (self.active if skills is None else skills)
            if any(
                path_matches(pattern, path)
                for pattern in skill.manifest.scope.paths
                for path in changed
            )
        )


class SkillCatalogService:
    def __init__(self, store: SkillStoreAbstract) -> None:
        self._store = store

    async def load(self) -> SkillCatalog:
        try:
            approved = ApprovedSkills.model_validate_json(await self._store.approved())
        except ValidationError:
            raise SkillError("Approved skill list has an unknown format") from None
        skills = []
        for entry in approved.skills:
            skills.append(await self._install(approved, entry))
        return SkillCatalog(approved, tuple(skills))

    async def _install(
        self, approved: ApprovedSkills, entry: ApprovedSkill
    ) -> InstalledSkill:
        label = f"{entry.id}@{entry.version}"
        contents = self._contents(
            label, entry, await self._store.package(entry.package)
        )
        manifest = self._manifest(label, entry, approved, contents)
        model = approved.model_profiles.get(manifest.model_profile)
        if model is None:
            raise SkillError(f"{label}: unknown model profile")
        try:
            instructions = contents[manifest.instructions].decode()
            examples = SkillExamples.model_validate_json(contents[manifest.examples])
        except UnicodeDecodeError:
            raise SkillError(f"{label}: instructions must be UTF-8 text") from None
        except ValidationError:
            raise SkillError(f"{label}: examples have an unknown format") from None
        if not instructions.strip():
            raise SkillError(f"{label}: instructions are empty")
        pin = VersionPin(id=entry.id, version=entry.version, digest=entry.digest)
        active, status = await self._activation(pin, model, examples)
        return InstalledSkill(
            pin=pin,
            manifest=manifest,
            instructions=instructions,
            examples=examples,
            model=model,
            active=active,
            status=status,
        )

    @staticmethod
    def _contents(
        label: str, entry: ApprovedSkill, files: tuple[PackageFile, ...]
    ) -> dict[str, bytes]:
        for file in files:
            if not file.regular:
                raise SkillError(f"{label}: links and folders are not allowed")
            if file.executable:
                raise SkillError(f"{label}: executable files are not allowed")
        if package_digest(files) != entry.digest:
            raise SkillError(f"{label}: package contents changed since approval")
        return {file.name: file.content for file in files}

    @staticmethod
    def _manifest(
        label: str,
        entry: ApprovedSkill,
        approved: ApprovedSkills,
        contents: dict[str, bytes],
    ) -> SkillManifest:
        if "manifest.json" not in contents:
            raise SkillError(f"{label}: manifest.json is missing")
        try:
            manifest = SkillManifest.model_validate_json(contents["manifest.json"])
        except ValidationError:
            raise SkillError(f"{label}: manifest has an unknown format") from None
        if (manifest.id, manifest.version) != (entry.id, entry.version):
            raise SkillError(f"{label}: manifest does not match its approval")
        expected = {"manifest.json", manifest.instructions, manifest.examples}
        if missing := sorted(expected - contents.keys()):
            raise SkillError(f"{label}: missing files {', '.join(missing)}")
        if unexpected := sorted(contents.keys() - expected):
            raise SkillError(f"{label}: unexpected files {', '.join(unexpected)}")
        if extra := sorted(
            set(manifest.permissions.capabilities) - set(approved.permissions)
        ):
            raise SkillError(f"{label}: requests unapproved {', '.join(extra)}")
        return manifest

    async def _activation(
        self, pin: VersionPin, model: ModelProfile, examples: SkillExamples
    ) -> tuple[bool, str]:
        content = await self._store.evaluation(evaluation_name(pin))
        if content is None:
            return False, "Inactive: no recorded example evaluation"
        try:
            evaluation = SkillEvaluation.model_validate_json(content)
        except ValidationError:
            return False, "Inactive: example evaluation has an unknown format"
        evaluated = sorted(case.case for case in evaluation.cases)
        if evaluation.skill != pin:
            return False, "Inactive: evaluation is for different package contents"
        if evaluation.model != EvaluatedModel(**model.model_dump()):
            return False, "Inactive: evaluation used a different model configuration"
        if evaluation.protocol_sha256 != protocol_sha256():
            return False, "Inactive: evaluation used a different review protocol"
        if evaluated != sorted(item.case for item in examples.examples):
            return False, "Inactive: evaluation does not cover every example"
        if not evaluation.passed:
            return False, "Inactive: the recorded example evaluation failed"
        return True, f"Active: examples passed with {model.model_id}"

    async def record(self, evaluation: SkillEvaluation) -> None:
        await self._store.save_evaluation(
            evaluation_name(evaluation.skill),
            evaluation.model_dump_json(indent=2).encode() + b"\n",
        )
