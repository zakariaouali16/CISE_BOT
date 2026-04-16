from fastapi import FastAPI, Request, BackgroundTasks
from contextlib import asynccontextmanager
import uvicorn
import logging
import asyncio
import re
import json, os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.cloud import pubsub_v1

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- GCP Configuration ---
# You need to set these environment variables in Cloud Run
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
SUBSCRIPTION_ID = os.environ.get("PUBSUB_SUBSCRIPTION_ID")

# --- Credentials & Chat Service Setup ---
scopes = ['https://www.googleapis.com/auth/chat.bot', 'https://www.googleapis.com/auth/pubsub']
creds_env = os.environ.get("GOOGLE_CREDENTIALS")

if creds_env:
    creds_info = json.loads(creds_env)
    credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
else:
    CREDENTIALS_FILE = "credentials.json"
    credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)

chat_service = build('chat', 'v1', credentials=credentials)

# --- Your Existing Delayed DM Logic ---
async def send_delayed_dm(space_name: str, sender_name: str, delay_seconds: int):
    logger.info(f"Starting {delay_seconds} second timer for {sender_name}...")
    await asyncio.sleep(delay_seconds)
    logger.info(f"Timer up! Sending message to {space_name}")
    
    message_body = {
        "text": f"🔔 Hey <{sender_name}>! Your break is up. Time to get back to it!"
    }
    
    def make_api_call():
        return chat_service.spaces().messages().create(parent=space_name, body=message_body).execute()

    try:
        await asyncio.to_thread(make_api_call)
        logger.info(f"Successfully sent delayed DM to {sender_name}")
    except Exception as e:
        logger.error(f"Failed to send delayed DM: {e}")

# --- NEW: Pub/Sub Listener Logic ---
def process_pubsub_message(message: pubsub_v1.subscriber.message.Message):
    """Callback function triggered every time a message hits the Pub/Sub queue."""
    try:
        # Decode the byte payload into a JSON dictionary
        payload = json.loads(message.data.decode("utf-8"))
        
        # Workspace Events API wraps the chat message in a specific format
        # Check if this is a message creation event
        if payload.get("type") == "google.workspace.chat.message.v1.created":
            event_data = payload.get("data", {})
            user_message = event_data.get("text", "")
            sender_name = event_data.get("sender", {}).get("name", "")
            space_name = event_data.get("space", {}).get("name", "")
            
            logger.info(f"Pub/Sub received: {user_message} from {sender_name}")
            
            if user_message:
                text_lower = user_message.lower().strip()
                if re.search(r'\b(i 10|taking 10|taking 10 minute break)\b', text_lower):
                    logger.info("Trigger phrase detected via Pub/Sub! Starting timer.")
                    # Create a new event loop task since we are in a synchronous callback
                    loop = asyncio.get_running_loop()
                    loop.create_task(send_delayed_dm(space_name, sender_name, 10))

    except Exception as e:
        logger.error(f"Error processing Pub/Sub message: {e}")
    finally:
        # ALWAYS acknowledge the message so Pub/Sub doesn't send it again
        message.ack()

def start_pubsub_listener():
    """Starts the synchronous Pub/Sub streaming pull."""
    subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
    
    logger.info(f"Listening for messages on {subscription_path}..\n")
    
    # This future blocks the thread while listening
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=process_pubsub_message)
    try:
        streaming_pull_future.result()
    except Exception as e:
        logger.error(f"Pub/Sub listener stopped: {e}")
        streaming_pull_future.cancel()

# --- FastAPI Lifespan (Starts background tasks) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Kick off the Pub/Sub listener in a separate thread so it doesn't block FastAPI
    logger.info("Starting Pub/Sub background worker...")
    listener_task = asyncio.create_task(asyncio.to_thread(start_pubsub_listener))
    yield
    # Shutdown logic can go here
    listener_task.cancel()

app = FastAPI(lifespan=lifespan)

# --- Keep the HTTP Endpoint for DMs or @Mentions ---
@app.post("/")
async def chat_endpoint(request: Request, background_tasks: BackgroundTasks):
    # ... [Keep your exact same @app.post("/") code from before here] ...
    # This ensures your bot still responds to standard @mentions and DMs!
    return {"text": "Webhook endpoint active."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)