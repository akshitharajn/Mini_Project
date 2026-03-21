"""Seed achievements into the database."""

import asyncio
from backend.app.database import async_session_factory, init_db
from backend.app.services.gamification import seed_achievements


async def main():
    """Seed achievements."""
    await init_db()
    async with async_session_factory() as db:
        await seed_achievements(db)
        await db.commit()
    print("✅ Achievements seeded successfully!")


if __name__ == "__main__":
    asyncio.run(main())
