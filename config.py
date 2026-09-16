import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = "qwen/qwen3.8-27b"
APP_API_KEY = os.getenv("APP_API_KEY")  # shared key your frontend sends
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")  # from the webhook endpoint setup step
STRIPE_PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY")  # price_... ID
STRIPE_PRICE_ANNUAL = os.getenv("STRIPE_PRICE_ANNUAL")  # price_... ID
DESKTOP_TOKEN_SECRET = os.getenv("DESKTOP_TOKEN_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://synora-frontend-swart.vercel.app")

B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY")
B2_INSTALLERS_BUCKET_NAME = os.getenv("B2_INSTALLERS_BUCKET_NAME", "Synora-installers")
DOWNLOAD_URL_VALID_SECONDS = 300  # authorized download links expire after 5 minutes
