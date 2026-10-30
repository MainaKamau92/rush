import asyncio
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import httpx2
from fastapi import Request
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl

from app.core.errors import ChangeError, ModelError, SourceError
from app.core.settings import Settings
from app.db.migrate import migration_files
from app.db.repositories.reviews import SQLiteReviewRepository
from app.db.repositories.state import SQLiteStateRepository
from app.internal.adapters.mcp_auth import (
    REDIRECT_URI,
    McpCredentialFile,
    StaticBearerAuth,
    authorization_result,
    narrow_scope,
    refuse_authorization,
)
from app.models.source_access import CredentialStatus
from app.provider.model.base import ModelServiceProvider
from app.provider.repository.base import RepositoryServiceProvider
from app.provider.source.base import SourceServiceProvider
from app.services.code_change_reader import CodeChangeReaderService
from app.services.model_access import ModelAccessService
from app.services.review_records import ReviewRecordService
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


def build_system(settings: Settings) -> SystemService:
    return SystemService(
        SQLiteStateRepository(settings.database_path), len(migration_files())
    )


def build_model_access(settings: Settings) -> ModelAccessService:
    if settings.meta_api_key is None or not settings.meta_api_key.get_secret_value():
        raise ModelError("Set META_AI_KEY before checking model access")
    client = httpx.AsyncClient(
        base_url=settings.meta_base_url + "/",
        headers={"Authorization": f"Bearer {settings.meta_api_key.get_secret_value()}"},
        timeout=settings.model_timeout_seconds,
        follow_redirects=False,
        trust_env=False,
    )
    return ModelAccessService(
        ModelServiceProvider(client), settings.model_timeout_seconds
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
        raise SourceError("ClickUp authorization is required; run rush source-connect")
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


def get_system(request: Request) -> SystemService:
    service: SystemService = request.app.state.system
    return service
