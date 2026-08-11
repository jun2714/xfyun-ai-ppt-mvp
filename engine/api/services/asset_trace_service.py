from models.sql.asset_generation_trace import AssetGenerationTrace


async def record_asset_generation_trace(trace: AssetGenerationTrace) -> None:
    # Trace rows use their own transaction so a later slide or export failure
    # cannot erase evidence of an already incurred provider call.
    # Import lazily so pure asset-planning and image-processing tests do not
    # initialize the application database as a side effect.
    from services.database import async_session_maker

    async with async_session_maker() as session:
        session.add(trace)
        await session.commit()
