import asyncio
import logging
from livekit.agents import WorkerOptions, Worker
from agent.voice_agent import entrypoint
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("🚀 Starting LiveKit Voice Agent...")
    logger.info(f"✅ Configured for: {Config.LIVEKIT_URL}")
    logger.info("🔄 Starting worker...")
    
    # Create worker with FULL options including credentials
    worker = Worker(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=Config.LIVEKIT_API_KEY,
            api_secret=Config.LIVEKIT_API_SECRET,
            ws_url=Config.LIVEKIT_URL,
        )
    )
    
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("👋 Worker stopped by user")
    except Exception as e:
        logger.error(f"💥 Worker error: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())