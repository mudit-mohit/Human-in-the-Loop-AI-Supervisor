import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LiveKit Configuration
    LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://test.livekit.cloud")
    LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "secret")
    
    # Groq API for STT, LLM, and TTS
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    
    # OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Application Settings
    REQUEST_TIMEOUT_MINUTES = 30

config = Config()