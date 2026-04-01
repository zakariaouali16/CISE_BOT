from fastapi import FastAPI, Request, BackgroundTasks
import uvicorn
import logging
import asyncio
import re
import json, os
# For sending asynchronous messages later
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# --- GOOGLE CHAT API SETUP FOR DELAYED MESSAGES ---
scopes = ['https://www.googleapis.com/auth/chat.bot']

# Try to load from an environment variable first (for Cloud Run)
creds_env = os.environ.get("GOOGLE_CREDENTIALS_JSON")

if creds_env:
    # Parse the JSON string from the environment variable
    creds_info = json.loads(creds_env)
    credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
else:
    # Fallback to the file if running locally
    CREDENTIALS_FILE = "credentials.json"
    credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)

chat_service = build('chat', 'v1', credentials=credentials)

# --- FIX 1: Add space_name to the function parameters ---
async def send_delayed_dm(space_name: str, sender_name: str, delay_seconds: int):
    """Waits for the specified time, then sends a DM via Google Chat API."""
    logger.info(f"Starting {delay_seconds} second timer for {sender_name} in {space_name}...")
    
    # Wait for the break to finish (this is async and perfectly safe)
    await asyncio.sleep(delay_seconds)
    
    logger.info(f"Timer up! Sending message to {space_name}")
    
    message_body = {
        "text": f"🔔 Hey <{sender_name}>! Your 10-minute break is up. Time to get back to it!"
    }
    
    # --- FIX: Wrap the blocking synchronous code in a helper function ---
    def make_api_call():
        return chat_service.spaces().messages().create(
            parent=space_name, 
            body=message_body
        ).execute()

    try:
        # --- FIX: Run the blocking call in a separate thread ---
        # This prevents the .execute() method from freezing the Uvicorn worker
        await asyncio.to_thread(make_api_call)
        logger.info(f"Successfully sent delayed DM to {sender_name}")
    except Exception as e:
        logger.error(f"Failed to send delayed DM: {e}")

        
@app.post("/")
async def chat_endpoint(request: Request, background_tasks: BackgroundTasks):
    logger.info("--- New POST request received ---")
    
    try:
        try:
            event = await request.json()
        except Exception:
            return {"text": "Received empty request."}
            
        logger.info(f"Raw payload received: {event}")

        # Extract variables safely
        user_message = ""
        sender_name = "" 
        space_name = ""  # --- FIX 3: Initialize space_name ---
        
        # 1. Handle Google Workspace Add-on Format
        if "chat" in event:
            chat_data = event.get("chat", {})
            if "messagePayload" in chat_data:
                msg_payload = chat_data["messagePayload"].get("message", {})
                user_message = msg_payload.get("text", "")
                sender_name = msg_payload.get("sender", {}).get("name", "")
                
                # --- FIX 4: Safely extract space_name from Add-on payload ---
                space_name = msg_payload.get("space", {}).get("name", "")
                if not space_name:
                    space_name = chat_data.get("space", {}).get("name", "")
                
        # 2. Handle Standard Google Chat Format
        elif event.get("type") == "MESSAGE":
            msg_payload = event.get("message", {})
            user_message = msg_payload.get("text", "")
            sender_name = msg_payload.get("sender", {}).get("name", "")
            
            # --- FIX 5: Extract space_name from Standard payload ---
            space_name = event.get("space", {}).get("name", "")

        # --- TIMER LOGIC ---
        if user_message:
            text_lower = user_message.lower().strip()
            
            # Check if the user said the magic words
            if re.search(r'\b(i 10|taking 10|taking 10 minute break)\b', text_lower):
                
                # --- FIX 6: Pass space_name to the background task ---
                background_tasks.add_task(send_delayed_dm, space_name, sender_name, 10)
                
                text = "Got it! Have a good 10-minute break. I'll send you a DM when time is up."
            else:
                text = f"You said: {user_message}. I am ready to track your tasks and breaks!"
                
            # Build the response (Workspace Add-on format)
            if "chat" in event:
                return {
                    "hostAppDataAction": {
                        "chatDataAction": {
                            "createMessageAction": {
                                "message": {
                                    "text": text
                                }
                            }
                        }
                    }
                }
            # Standard Chat Format
            else:
                return {"text": text}

        # Fallback for bot added to space
        if event.get("type") == "ADDED_TO_SPACE" or ("chat" in event and "messagePayload" not in event["chat"]):
            text = "Thanks for adding me! I am ready to help you track your work hours."
            if "chat" in event:
                return {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": text}}}}}
            return {"text": text}

        return {"text": "Hello! I am online but received an unknown payload."}

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)
        return {"text": "Sorry, I encountered an internal error."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)