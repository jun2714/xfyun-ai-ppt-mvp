from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria
from sqlmodel import SQLModel

from models.sql.async_task import AsyncTaskModel
from models.sql.async_presentation_generation_status import (
    AsyncPresentationGenerationTaskModel,
)
from models.sql.chat_history_message import ChatHistoryMessageModel
from models.sql.font_upload import FontUpload
from models.sql.image_asset import ImageAsset
from models.sql.asset_generation_trace import AssetGenerationTrace
from models.sql.key_value import KeyValueSqlModel
from models.sql.ollama_pull_status import OllamaPullStatus
from models.sql.presentation_layout_code import PresentationLayoutCodeModel
from models.sql.presentation import PresentationModel
from models.sql.template import TemplateModel
from models.sql.template_create_info import TemplateCreateInfoModel
from models.sql.template_v2 import TemplateV2
from models.sql.slide import SlideModel
from models.sql.webhook_subscription import WebhookSubscription
from models.sql.user import User
from models.sql.access_token import AccessToken
from models.sql.provider_settings import ProviderSettings
from models.sql.ppt_library_item import PptLibraryItem
from starlette.requests import Request

from api.v1.auth.context import (
    bind_owner_from_principal,
    unbind_owner,
)
from services.owner_scope import attach_owner_to_session, owner_id_from_session
from utils.get_env import get_migrate_database_on_startup_env
from utils.db_utils import get_database_url_and_connect_args, get_pool_kwargs


database_url, connect_args = get_database_url_and_connect_args()

# Apply connection-pool settings for server-class databases (PostgreSQL, MySQL).
# SQLite uses a file-lock model and ignores pool configuration, so we skip it.
_pool_kwargs = get_pool_kwargs() if "sqlite" not in database_url else {}

sql_engine: AsyncEngine = create_async_engine(
    database_url, connect_args=connect_args, **_pool_kwargs
)


if "sqlite" in database_url:
    @event.listens_for(sql_engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
async_session_maker = async_sessionmaker(sql_engine, expire_on_commit=False)


_STRICT_OWNER_MODELS = (
    PresentationModel,
    SlideModel,
    PresentationLayoutCodeModel,
    TemplateModel,
    ChatHistoryMessageModel,
    ImageAsset,
    AssetGenerationTrace,
    TemplateCreateInfoModel,
    AsyncTaskModel,
    AsyncPresentationGenerationTaskModel,
    WebhookSubscription,
)


def _selected_model_classes(statement) -> list[type] | None:
    """Return mapped classes actually present in this SELECT, if detectable."""
    try:
        descriptions = statement.column_descriptions
    except Exception:
        return None
    selected: list[type] = []
    for desc in descriptions or []:
        entity = desc.get("entity") if isinstance(desc, dict) else None
        model = getattr(entity, "class_", None) or entity
        if isinstance(model, type) and model not in selected:
            selected.append(model)
    return selected


@event.listens_for(Session, "do_orm_execute")
def _scope_owned_selects(execute_state) -> None:
    """Apply tenant criteria only to mapped classes in the current SELECT.

    Applying with_loader_criteria to unused models (and stacking it on an
    explicit owner_id WHERE) can compile to an always-false predicate on
    MySQL CHAR(32) UUID columns, which emptied the dashboard for tn_1.
    """
    owner_id = owner_id_from_session(execute_state.session)
    if (
        owner_id is None
        or not execute_state.is_select
        or execute_state.execution_options.get("skip_owner_scope")
    ):
        return

    statement = execute_state.statement
    selected = _selected_model_classes(statement)
    if selected is not None and not selected:
        return

    for model in _STRICT_OWNER_MODELS:
        if selected is not None and model not in selected:
            continue
        statement = statement.options(
            with_loader_criteria(
                model,
                lambda row, owned_id=owner_id: row.owner_id == owned_id,
                include_aliases=True,
            )
        )
    if selected is None or TemplateV2 in selected:
        statement = statement.options(
            with_loader_criteria(
                TemplateV2,
                lambda row, owned_id=owner_id: or_(
                    row.owner_id == owned_id,
                    (row.owner_id.is_(None) & row.is_default.is_(True)),
                ),
                include_aliases=True,
            )
        )
    execute_state.statement = statement


@event.listens_for(Session, "before_flush")
def _stamp_new_owned_rows(session, _flush_context, _instances) -> None:
    owner_id = owner_id_from_session(session)
    if owner_id is None:
        return
    owner_models = _STRICT_OWNER_MODELS + (TemplateV2,)
    for instance in session.new:
        if isinstance(instance, owner_models):
            instance.owner_id = owner_id


async def get_async_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session with owner scope bound from the current request principal.

    Binding here (not only in BaseHTTPMiddleware) keeps ContextVars visible to
    the endpoint. Owner id is also stored on session.info so SQLAlchemy's
    sync greenlet listeners can still see it.
    """
    principal = getattr(request.state, "auth_principal", None)
    owner_token, admin_token = None, None
    try:
        async with async_session_maker() as session:
            if principal is None:
                from api.v1.auth.principal import resolve_request_principal

                principal, user = await resolve_request_principal(request, session)
                if principal is not None:
                    request.state.auth_principal = principal
                    request.state.current_user = user
            owner_token, admin_token = bind_owner_from_principal(principal)
            attach_owner_to_session(session, principal)
            yield session
    finally:
        unbind_owner(owner_token, admin_token)


# Create Database and Tables
async def create_db_and_tables():
    should_run_alembic = get_migrate_database_on_startup_env() in ["true", "True"]
    if not should_run_alembic:
        async with sql_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: SQLModel.metadata.create_all(
                    sync_conn,
                    tables=[
                        PresentationModel.__table__,
                        SlideModel.__table__,
                        KeyValueSqlModel.__table__,
                        TemplateV2.__table__,
                        ChatHistoryMessageModel.__table__,
                        ImageAsset.__table__,
                        AssetGenerationTrace.__table__,
                        FontUpload.__table__,
                        PresentationLayoutCodeModel.__table__,
                        TemplateCreateInfoModel.__table__,
                        TemplateModel.__table__,
                        WebhookSubscription.__table__,
                        AsyncTaskModel.__table__,
                        AsyncPresentationGenerationTaskModel.__table__,
                        OllamaPullStatus.__table__,
                        User.__table__,
                        AccessToken.__table__,
                        ProviderSettings.__table__,
                        PptLibraryItem.__table__,
                    ],
                )
            )


async def dispose_engines():
    """Dispose all engine connection pools.

    Call this during application shutdown (e.g. in a FastAPI ``shutdown``
    event or lifespan context) to release every connection back to the
    database and prevent stale / leaked connections.
    """
    await sql_engine.dispose()
