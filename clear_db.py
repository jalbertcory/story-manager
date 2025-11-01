import asyncio
from backend.app.database import engine
from backend.app import models

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)

if __name__ == "__main__":
    asyncio.run(main())
