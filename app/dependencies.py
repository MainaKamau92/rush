import asyncio
import json
import shutil
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import httpx
import httpx2
from fastapi import Request
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl

from app.core.errors import (
    ChangeError,
    CodeHostError,
    ModelError,
    ReviewError,
    SkillError,
    SourceAccessError,
    SourceError,
)
from app.core.settings import Settings
from app.db.migrate import migration_files
from app.db.repositories.finding_events import SQLiteFindingEventRepository
from app.db.repositories.jobs import SQLiteJobRepository
from app.db.repositories.learning import SQLiteLearningRepository
from app.db.repositories.publications import SQLitePublicationRepository
from app.db.repositories.reviews import SQLiteReviewRepository
from app.db.repositories.state import SQLiteStateRepository
from app.internal.adapters.examples import ExampleContextAdapter
from app.internal.adapters.mcp_auth import (
    REDIRECT_URI,
    McpCredentialFile,
    StaticBearerAuth,
    authorization_result,
    narrow_scope,
    refuse_authorization,
)
from app.models.source_access import CredentialStatus
from app.provider.github.base import CodeHostServiceProvider
from app.provider.model.abstract import ModelProviderAbstract
from app.provider.model.base import ModelServiceProvider
from app.provider.repository.base import RepositoryServiceProvider
from app.provider.skills.abstract import SkillStoreAbstract
from app.provider.skills.base import SkillServiceProvider
from app.provider.source.base import SourceServiceProvider
from app.schemas.github import PullRequest, ReviewJob
from app.schemas.learning import CaseResult, LearningDraft
from app.schemas.local_review import LocalReviewRequest, ReviewOutcome
from app.schemas.policy import Rule
from app.schemas.review import ModelConfiguration, ReviewLimits, VersionPin
from app.schemas.skill import InstalledSkill
from app.services.code_change_reader import CodeChangeReaderService
from app.services.context_retrieval import ContextRetrievalService
from app.services.disclosure import DisclosureService
from app.services.finding_conversation import FindingConversationService
from app.services.finding_validation import FindingValidationService
from app.services.github_events import GitHubEventService
from app.services.investigation import InvestigationService
from app.services.learning import LearningService
from app.services.learning_evaluation import LearningEvaluationService
from app.services.local_review import LocalReviewService
from app.services.model_access import ModelAccessService
from app.services.model_context import ModelContext
from app.services.model_review import ModelReviewService
from app.services.pull_request_publication import PullRequestPublisher
from app.services.review_budget import ReviewBudget
from app.services.review_jobs import ReviewJobService
from app.services.review_records import ReviewRecordService
from app.services.review_skills import SkillCatalog, SkillCatalogService
from app.services.source_access import SourceAccessService
from app.services.system import SystemService

SIGN_IN_TIMEOUT_SECONDS = 600


def build_review_records(settings: Settings) -> ReviewRecordService:
    return ReviewRecordService(
        SQLiteReviewRepository(settings.database_path), lambda: datetime.now(UTC)
    )


def build_code_change_reader(repository: Path) -> CodeChangeReaderService:
    executable = shutil.which("git")
    if executable is None:
        raise ChangeError("Git is not installed; run change-read in the dev image")
    if not repository.is_dir():
        raise ChangeError("Repository path is not a directory")
    return CodeChangeReaderService(
        RepositoryServiceProvider(repository.resolve(), executable)
    )


def build_investigation(
    repository: Path,
    limits: ReviewLimits | None = None,
    *,
    search_paths: frozenset[str] = frozenset(),
    approved_test_paths: frozenset[str] = frozenset(),
) -> InvestigationService:
    executable = shutil.which("git")
    if executable is None or not repository.is_dir():
        raise ChangeError("Investigation needs Git and a readable repository directory")
    provider = RepositoryServiceProvider(repository.resolve(), executable)
    return InvestigationService(
        provider,
        CodeChangeReaderService(provider),
        ReviewBudget(limits or ReviewLimits(), time.monotonic),
        search_paths=search_paths,
        approved_test_paths=approved_test_paths,
    )


def build_system(settings: Settings) -> SystemService:
    return SystemService(
        SQLiteStateRepository(settings.database_path), len(migration_files())
    )


def _build_model_provider(settings: Settings) -> ModelProviderAbstract:
    if settings.meta_api_key is None or not settings.meta_api_key.get_secret_value():
        raise ModelError("Set META_AI_KEY before checking model access")
    client = httpx.AsyncClient(
        base_url=settings.meta_base_url + "/",
        headers={"Authorization": f"Bearer {settings.meta_api_key.get_secret_value()}"},
        timeout=settings.model_timeout_seconds,
        follow_redirects=False,
        trust_env=False,
    )
    return ModelServiceProvider(client)


def build_model_access(settings: Settings) -> ModelAccessService:
    return ModelAccessService(
        _build_model_provider(settings), settings.model_timeout_seconds
    )


def build_model_review(
    settings: Settings, investigation: InvestigationService
) -> ModelReviewService:
    return ModelReviewService(
        _build_model_provider(settings),
        investigation,
        build_review_records(settings),
        lambda inputs, disclosure: ModelContext(
            inputs, investigation, disclosure, lambda: datetime.now(UTC)
        ),
        settings.model_timeout_seconds,
    )


def build_skill_store(root: Path) -> SkillStoreAbstract:
    if not root.is_dir():
        raise SkillError("Skills directory is missing")
    return SkillServiceProvider(root.resolve())


def build_skill_catalog(root: Path) -> SkillCatalogService:
    return SkillCatalogService(build_skill_store(root))


def build_context_retrieval(settings: Settings) -> ContextRetrievalService:
    return ContextRetrievalService(
        build_source_access(settings),
        settings.source_disclosure,
        lambda: datetime.now(UTC),
    )


def build_local_review(settings: Settings, catalog: SkillCatalog) -> LocalReviewService:
    records = build_review_records(settings)
    return LocalReviewService(
        catalog,
        lambda investigation: build_model_review(settings, investigation),
        FindingValidationService(records),
        records,
        lambda: datetime.now(UTC),
        lambda: build_context_retrieval(settings),
    )


def _credential_file(settings: Settings) -> McpCredentialFile:
    if settings.mcp_credentials_dir is None:
        raise SourceError("Set RUSH_MCP_CREDENTIALS_DIR before connecting a source")
    return McpCredentialFile(settings.mcp_credentials_dir / "clickup.json")


def _api_token(settings: Settings) -> str | None:
    token = settings.clickup_api_token
    if token is None or not token.get_secret_value():
        return None
    return token.get_secret_value()


def source_credential_status(settings: Settings) -> CredentialStatus:
    if _api_token(settings) is not None:
        return CredentialStatus("api_token", True, False, None, False, None)
    return _credential_file(settings).status()


def _clickup_oauth(
    settings: Settings,
    show_authorization: Callable[[str], None] | None,
    read_redirect: Callable[[], str] | None,
) -> tuple[httpx2.Auth, float]:
    storage = _credential_file(settings)
    redirect_handler: Callable[[str], Awaitable[None]] = refuse_authorization
    callback_handler: Callable[[], Awaitable[AuthorizationCodeResult]]
    callback_handler = refuse_authorization
    timeout_seconds = settings.source_timeout_seconds
    if show_authorization is not None and read_redirect is not None:
        show, read = show_authorization, read_redirect

        async def show_read_only(url: str) -> None:
            show(narrow_scope(url, "read"))

        async def receive_redirect() -> AuthorizationCodeResult:
            return authorization_result(await asyncio.to_thread(read))

        redirect_handler, callback_handler = show_read_only, receive_redirect
        timeout_seconds = SIGN_IN_TIMEOUT_SECONDS
    elif not storage.status().credential_available:
        raise SourceAccessError(
            "ClickUp authorization is required; run rush source-connect"
        )
    oauth = OAuthClientProvider(
        server_url=settings.clickup_mcp_url,
        client_metadata=OAuthClientMetadata(
            client_name="rush", redirect_uris=[AnyUrl(REDIRECT_URI)], scope="read"
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    return oauth, timeout_seconds


def build_source_access(
    settings: Settings,
    show_authorization: Callable[[str], None] | None = None,
    read_redirect: Callable[[], str] | None = None,
) -> SourceAccessService:
    if not settings.clickup_workspace_id:
        raise SourceError("Set RUSH_CLICKUP_WORKSPACE_ID to the approved workspace")
    token = _api_token(settings)
    auth: httpx2.Auth
    if token is not None:
        auth, timeout_seconds = StaticBearerAuth(token), settings.source_timeout_seconds
    else:
        auth, timeout_seconds = _clickup_oauth(
            settings, show_authorization, read_redirect
        )
    http_client = httpx2.AsyncClient(
        auth=auth,
        timeout=settings.source_timeout_seconds,
        follow_redirects=False,
        trust_env=False,
    )
    client = Client(
        streamable_http_client(settings.clickup_mcp_url, http_client=http_client),
        read_timeout_seconds=settings.source_timeout_seconds,
    )
    return SourceAccessService(
        SourceServiceProvider(client, settings.clickup_workspace_id, http_client),
        {
            "ticket": settings.approved_tickets,
            "guideline": settings.approved_guidelines,
        },
        timeout_seconds,
    )


@dataclass(frozen=True)
class GitHubReviews:
    events: GitHubEventService
    worker: ReviewJobService


def _trusted_text(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        raise ReviewError(f"Cannot read the approved policy file {path.name}") from None


async def review_pull_request(
    settings: Settings, job: ReviewJob, pull: PullRequest, mirror: Path
) -> ReviewOutcome:
    if settings.review_skills_dir is None or job.run_id is None:
        raise ReviewError("Set RUSH_REVIEW_SKILLS_DIR to the approved skills")
    catalog = await build_skill_catalog(settings.review_skills_dir).load()
    service = build_local_review(settings, catalog)
    live = bool(settings.clickup_workspace_id and pull.body and pull.body.strip())
    rules, approvers = await _rules_with_learning(settings)
    request = LocalReviewRequest(
        run_id=job.run_id,
        repository=job.repository,
        pull_request=job.pull_request,
        head=pull.head_sha,
        target=pull.base_sha,
        disclosure=settings.review_disclosure,
        rules=rules,
        exceptions=_trusted_text(settings.review_exceptions_file),
        approvers=approvers,
        pull_request_text=pull.body if live else None,
        live_guidelines=bool(
            settings.clickup_workspace_id and settings.approved_guidelines
        ),
    )
    outcome = await service.review(build_investigation(mirror), request)
    return await disclose_for_github(settings, await service.finish(outcome))


async def _rules_with_learning(
    settings: Settings,
) -> tuple[str | None, tuple[str, ...]]:
    """
    Add approved learning to the trusted rules as ordinary entries, so scope,
    conflict and exception handling treat it like any other standard. A learned
    rule counts only while its approver is still a designated learning approver,
    and learning approvers never validate the operator's own rules.
    """
    text = _trusted_text(settings.review_rules_file)
    approvers = set(settings.review_approvers)
    rules = json.loads(text) if text else []
    if not isinstance(rules, list):
        raise ReviewError("Rules and exceptions must match the approved policy format")
    taken = {item.get("id") for item in rules if isinstance(item, dict)}
    learned = [
        rule
        for rule in await build_learning(settings).active_rules()
        if rule.approved_by in settings.learning_approvers and rule.id not in taken
    ]
    for rule in learned:
        label = f"team learning approval by {rule.approved_by}"
        approvers.add(label)
        rules.append(
            rule.model_copy(update={"approved_by": label}).model_dump(mode="json")
        )
    return (json.dumps(rules) if learned else text), tuple(sorted(approvers))


def build_learning(settings: Settings) -> LearningService:
    return LearningService(
        SQLiteLearningRepository(settings.database_path),
        settings.learning_approvers,
        lambda: datetime.now(UTC),
        lambda: f"L{uuid.uuid4().hex[:8]}",
    )


def build_example_context(root: Path | None = None) -> ExampleContextAdapter:
    return ExampleContextAdapter(
        root or Path(__file__).resolve().parents[1] / "tests/fixtures/customer_lookup"
    )


async def _example(case: str) -> Path:
    process = await asyncio.create_subprocess_exec(
        "sh",
        str(Path(__file__).resolve().parents[1] / "scripts/reset-example.sh"),
        case,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    output, _ = await process.communicate()
    if process.returncode != 0:
        raise ReviewError(f"Example {case} is not a known fixture case")
    return Path(output.decode().strip())


async def evaluate_learning(
    settings: Settings, draft: LearningDraft, rule: Rule
) -> tuple[VersionPin, ModelConfiguration, tuple[CaseResult, ...]]:
    catalog = await build_skill_catalog(
        settings.review_skills_dir or Path("skills")
    ).load()
    skill = next(
        (
            item
            for item in catalog.active
            if "*" in item.manifest.rule_ids or rule.id in item.manifest.rule_ids
        ),
        None,
    )
    if skill is None:
        raise SkillError("No active skill applies team rules; evaluate one first")
    service = build_local_review(settings, catalog)

    async def review(
        case: str, request: LocalReviewRequest, selected: InstalledSkill
    ) -> ReviewOutcome:
        example = await _example(case)
        try:
            return await service.finish(
                await service.review(build_investigation(example), request, (selected,))
            )
        finally:
            shutil.rmtree(example)

    context = build_example_context()

    cases = await LearningEvaluationService(
        review,
        context.request,
        lambda: datetime.now(UTC),
        lambda: f"learning-{uuid.uuid4().hex}",
    ).evaluate(draft, rule, skill)
    model = ModelConfiguration(
        task="review",
        model_id=skill.model.model_id,
        adapter_version=skill.model.adapter_version,
        max_output_tokens=skill.model.max_output_tokens,
    )
    return skill.pin, model, tuple(cases)


async def disclose_for_github(
    settings: Settings, outcome: ReviewOutcome
) -> ReviewOutcome:
    if settings.review_skills_dir is None:
        raise ReviewError("Set RUSH_REVIEW_SKILLS_DIR to the approved skills")
    catalog = await build_skill_catalog(settings.review_skills_dir).load()
    return DisclosureService(catalog.approved.publishable_disclosures).for_audience(
        outcome, settings.github_audience, settings.review_disclosure
    )


def build_github_reviews(settings: Settings) -> GitHubReviews:
    secret, key_file = settings.github_webhook_secret, settings.github_private_key_file
    if not settings.github_enabled or secret is None or key_file is None:
        raise CodeHostError(
            "Set the GitHub App ID, private key file, webhook secret and repositories"
        )
    executable = shutil.which("git")
    if executable is None:
        raise ChangeError("Git is not installed; GitHub reviews need it")
    try:
        private_key = key_file.read_text()
    except (OSError, UnicodeDecodeError):
        raise CodeHostError("Cannot read the GitHub App private key file") from None
    client = httpx.AsyncClient(
        base_url=settings.github_api_url + "/",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "rush",
        },
        timeout=30,
        follow_redirects=False,
        trust_env=False,
    )
    jobs = SQLiteJobRepository(settings.database_path)
    host = CodeHostServiceProvider(
        client,
        str(settings.github_app_id),
        private_key,
        settings.github_git_url,
        executable,
    )
    records = build_review_records(settings)
    publications = SQLitePublicationRepository(settings.database_path)
    worker = ReviewJobService(
        jobs,
        host,
        partial(review_pull_request, settings),
        records,
        settings.mirrors_dir,
        lambda: datetime.now(UTC),
        publisher=PullRequestPublisher(host, publications, lambda: datetime.now(UTC)),
        conversation=FindingConversationService(
            host,
            publications,
            records,
            SQLiteFindingEventRepository(settings.database_path),
            lambda: _build_model_provider(settings),
            partial(disclose_for_github, settings),
            lambda: datetime.now(UTC),
            (settings.explain_complexity, settings.explain_verbosity),
            build_learning(settings),
        ),
    )
    events = GitHubEventService(
        jobs,
        secret.get_secret_value().encode(),
        settings.github_repositories,
        lambda: datetime.now(UTC),
        lambda: f"job-{uuid.uuid4().hex[:12]}",
        worker.wake,
    )
    return GitHubReviews(events, worker)


def build_job_list(
    settings: Settings,
) -> Callable[[int], Awaitable[tuple[ReviewJob, ...]]]:
    return SQLiteJobRepository(settings.database_path).recent


def get_system(request: Request) -> SystemService:
    service: SystemService = request.app.state.system
    return service


def get_github(request: Request) -> GitHubReviews | None:
    reviews: GitHubReviews | None = request.app.state.github
    return reviews
