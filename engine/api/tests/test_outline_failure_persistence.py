import asyncio

from sqlalchemy import JSON, Integer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from api.v1.ppt.endpoints.kindergarten import _persist_outline_failure


def test_outline_timeout_survives_real_async_rollback_and_preserves_saved_request():
    class Base(DeclarativeBase):
        pass

    class Presentation(Base):
        __tablename__ = "failure_checkpoint"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        theme: Mapped[dict] = mapped_column(JSON)

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                saved = {"palette": "mint", "kindergarten_generation": {
                    "outline_status": "pending", "request": {"topic": "小种子", "n_slides": 8},
                }}
                presentation = Presentation(id=1, theme=saved)
                session.add(presentation)
                await session.commit()
                # Rollback must discard unfinished changes and restore saved metadata.
                presentation.theme = {"unfinished": True}
                await _persist_outline_failure(presentation, "Text model timed out after 180 seconds", session)
            async with sessions() as session:
                stored = await session.get(Presentation, 1)
                assert stored.theme["palette"] == "mint"
                generation = stored.theme["kindergarten_generation"]
                assert generation["outline_status"] == "failed"
                assert generation["outline_error"] == "Text model timed out after 180 seconds"
                assert generation["request"] == {"topic": "小种子", "n_slides": 8}
                assert "unfinished" not in stored.theme
        finally:
            await engine.dispose()

    asyncio.run(run())
