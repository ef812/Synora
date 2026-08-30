import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = "qwen/qwen3.6-27b"
APP_API_KEY = os.getenv("APP_API_KEY")  # shared key your frontend sendss
