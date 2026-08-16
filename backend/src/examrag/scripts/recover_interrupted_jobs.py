"""Fail any ingestion job left mid-run by the previous process.

Run once per container start, after migrations and before the API starts
serving traffic — see the `backend` service command in docker-compose.yml.
Deliberately not wired into FastAPI's lifespan: liveness must stay reachable
even while the database is still starting, so nothing that requires a
database belongs in application startup. Sequencing this after
`alembic upgrade head`, which already requires the database to be up, keeps
that invariant intact while still running the sweep before any request could
observe a stuck job.

    uv run python -m examrag.scripts.recover_interrupted_jobs
"""

import asyncio
import logging

from examrag.database.connection import dispose_engine, get_session_factory
from examrag.ingestion.ingestion_pipeline import recover_interrupted_jobs

logger = logging.getLogger(__name__)


async def main() -> None:
    async with get_session_factory()() as session:
        recovered = await recover_interrupted_jobs(session)
        await session.commit()
    await dispose_engine()
    logger.info("Interrupted-job recovery: %d job(s) recovered", recovered)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(main())
