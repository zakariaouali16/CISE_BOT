from fastapi import FastAPI, Request, BackgroundTasks
import uvicorn
import logging
import asyncio
import re
import json
import os
from datetime import datetime

# Google API imports
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# ==========================================
# CONFIGURATION
# ==========================================
# Replace with your actual Google Sheet ID
SPREADSHEET_ID = 'Task Updates' 

# IMPORTANT: Change 'Task Updates .xlsx - Fab Lab Tasks' to the EXACT name of your tab
# A:J ensures we grab enough columns to include Task, Tech Assigned, and Deadline
RANGE_NAME = 'Task Updates - Fab Lab Tasks!A:J' 

# ==========================================
# GOOGLE API SETUP
# ==========================================
scopes = [
    'https://www.googleapis.com/auth/chat.bot',
    'https://www.googleapis.com/auth/spreadsheets.readonly' 
]

creds_env = os.environ.get("GOOGLE_CREDENTIALS_JSON")

if creds_env:
    # Use environment variable (great for Cloud Run / Heroku)
    creds_info = json.loads(creds_env)
    credentials = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
else:
    # Fallback to local file
    CREDENTIALS_FILE = "credentials.json"
    credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)

# Build the services
chat_service = build('chat', 'v1', credentials=credentials)
sheets_service = build('sheets', 'v4', credentials=credentials)


# ==========================================
# HELPER FUNCTIONS
# ==========================================
def fetch_sheet_data(spreadsheet_id: str, range_name: str):
    """Synchronous function to fetch data from Google Sheets API."""
    sheet = sheets_service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
    return result.get('values', [])

async def send_delayed_dm(space_name: str, sender_name: str, delay_seconds: int):
    """Waits for the specified time, then sends a DM via Google Chat API."""
    logger.info(f"Starting {delay_seconds} second timer for {sender_name} in {space_name}...")
    
    await asyncio.sleep(delay_seconds)
    
    logger.info(f"Timer up! Sending message to {space_name}")
    
    message_body = {
        "text": f"🔔 Hey <{sender_name}>! Your break is up. Time to get back to it!"
    }
    
    def make_api_call():
        return chat_service.spaces().messages().create(
            parent=space_name, 
            body=message_body
        ).execute()

    try:
        await asyncio.to_thread(make_api_call)
        logger.info(f"Successfully sent delayed DM to {sender_name}")
    except Exception as e:
        logger.error(f"Failed to send delayed DM: {e}")


# ==========================================
# MAIN BOT ENDPOINT
# ==========================================
@app.post("/")
async def chat_endpoint(request: Request, background_tasks: BackgroundTasks):
    logger.info("--- New POST request received ---")
    
    try:
        try:
            event = await request.json()
        except Exception:
            return {"text": "Received empty request."}

        # Initialize variables safely
        user_message = ""
        sender_name = "" 
        space_name = ""  
        
        # 1. Handle Google Workspace Add-on Format
        if "chat" in event:
            chat_data = event.get("chat", {})
            if "messagePayload" in chat_data:
                msg_payload = chat_data["messagePayload"].get("message", {})
                user_message = msg_payload.get("text", "")
                
                # Try to get displayName, fallback to name
                sender_info = msg_payload.get("sender", {})
                sender_name = sender_info.get("displayName", sender_info.get("name", ""))
                
                space_name = msg_payload.get("space", {}).get("name", "")
                if not space_name:
                    space_name = chat_data.get("space", {}).get("name", "")
                
        # 2. Handle Standard Google Chat Format
        elif event.get("type") == "MESSAGE":
            msg_payload = event.get("message", {})
            user_message = msg_payload.get("text", "")
            
            # Try to get displayName, fallback to name
            sender_info = msg_payload.get("sender", {})
            sender_name = sender_info.get("displayName", sender_info.get("name", ""))
            
            space_name = event.get("space", {}).get("name", "")

        # --- BOT LOGIC ---
        if user_message:
            text_lower = user_message.lower().strip()
            
            # TRIGGER 1: Read daily tasks ("@fablab here")
            if "here" in text_lower:
                try:
                    # Get today's date in YYYY-MM-DD format (matches your CSV format)
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    
                    # Extract the user's first name (e.g., "Fanny" from "Fanny Villa")
                    first_name = sender_name.split()[0] if sender_name else "Tech"
                    
                    # Fetch data asynchronously so we don't block the server
                    values = await asyncio.to_thread(fetch_sheet_data, SPREADSHEET_ID, RANGE_NAME)
                    
                    if not values:
                        text = "I couldn't read the spreadsheet. Please check my permissions or the tab name."
                    else:
                        my_tasks = []
                        
                        # Loop through rows to find today's tasks for this specific user
                        for row in values:
                            # We need at least 3 columns to check Task, Tech Assigned, and Deadline
                            if len(row) >= 3:
                                task_name = row[0].strip()
                                tech_assigned = row[1].strip()
                                deadline = row[2].strip()
                                
                                # Skip header row
                                if task_name.lower() == "task":
                                    continue
                                    
                                # Check if user is assigned AND deadline is today
                                if first_name.lower() in tech_assigned.lower() and deadline == today_str:
                                    my_tasks.append(task_name)
                        
                        # Build the response message
                        if my_tasks:
                            text = f"👋 Welcome in, {first_name}! Here are your tasks for today ({today_str}):\n\n"
                            for t in my_tasks:
                                text += f"✅ {t}\n"
                        else:
                            text = f"👋 Welcome in, {first_name}! I checked the schedule for {today_str}, and you don't have any specific tasks assigned to you today."
                            
                except Exception as e:
                    logger.error(f"Sheets API Error: {e}")
                    text = f"❌ Sorry, I couldn't read the tasks. Error: `{str(e)}`"
            
            # TRIGGER 2: Timer
            elif re.search(r'\b(2|taking 2|taking 2 minute break| 10|taking 10)\b', text_lower):
                # Set delay to 120 seconds (2 minutes)
                delay_duration = 2 * 60 
                background_tasks.add_task(send_delayed_dm, space_name, sender_name, delay_duration)
                text = "Got it! Have a good break. I'll send you a DM when time is up."
            
            # DEFAULT RESPONSE
            else:
                text = f"You said: {user_message}. Type 'here' to get today's tasks!"
                
            # Build the response payload based on the format Google sent
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
            else:
                return {"text": text}

        # Fallback for when the bot is first added to a space (no message text)
        if event.get("type") == "ADDED_TO_SPACE" or ("chat" in event and "messagePayload" not in event["chat"]):
            text = "Thanks for adding me! I am ready to help. Type 'here' to get your daily tasks."
            if "chat" in event:
                return {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": text}}}}}
            return {"text": text}

        return {"text": "Hello! I am online but received an unknown payload."}

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)
        return {"text": "Sorry, I encountered an internal error."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)