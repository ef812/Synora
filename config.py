import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = "qwen/qwen3.6-27b"  # check console.groq.com/docs/models for exact current model string