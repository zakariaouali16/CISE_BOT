import base64
import json
import logging
import re
from datetime import datetime, timedelta
from flask import Flask, request

from google.apps import chat_v1 as google_chat
import google.auth
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from googleapiclient.discovery import build

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration for Cloud Tasks & Sheets
PROJECT_ID = "fabbot-493206"
LOCATION = "us-central1"
QUEUE_ID = "reminder-queue"
SERVICE_URL = "https://fastapi-chat-bot-457040200265.us-central1.run.app/send-reminder"

# --- GOOGLE SHEETS CONFIGURATION ---
SPREADSHEET_ID = "1xCsTyYgWuGUUNS9Ek-VUrfHR1O0Eud2mb_InwIVhAWU" # Replace with the ID from your Google Sheets URL
SHEET_RANGE = "'April ''26 Fab Lab Tasks'!A404:I470" # Replace YOUR_SHEET_NAME (e.g., 'Fab Lab Tasks')

@app.route('/', methods=['POST'])
def receive_message():
    envelope = request.get_json()
    if not envelope: return 'Bad Request', 400

    pubsub_message = envelope.get('message')
    if pubsub_message and 'data' in pubsub_message:
        data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        event = json.loads(data)
        
        try:
            # Added sheets.readonly scope
            scopes = ['https://www.googleapis.com/auth/chat.bot', 'https://www.googleapis.com/auth/spreadsheets.readonly']
            credentials, _ = google.auth.default(scopes=scopes)
            chat_client = google_chat.ChatServiceClient(credentials=credentials)
            
            chat_request, needs_timer, minutes = format_request(event, credentials)
            
            if chat_request:
                chat_client.create_message(chat_request)
                
                if needs_timer:
                    # Pass the specific minutes to the scheduler
                    schedule_reminder_task(event, minutes)
                    
        except Exception as e:
            logging.error(f"Error: {e}")
            return ('', 204)

    return ('', 204)

def is_upcoming_or_no_deadline(deadline_str):
    """Checks if a deadline string is empty, today, or in the future."""
    # If there is no deadline, or it says "TBD", include it
    if not deadline_str or not str(deadline_str).strip() or str(deadline_str).strip().upper() == "TBD":
        return True
    
    # Common date formats used in Google Sheets
    date_formats = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%b %d, %Y", "%m-%d-%Y", "%m/%d"]
    today = datetime.now().date()
    
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(str(deadline_str).strip(), fmt).date()
            
            # Handle MM/DD format where the year defaults to 1900
            if fmt == "%m/%d":
                parsed_date = parsed_date.replace(year=today.year)
                
            return parsed_date >= today
        except ValueError:
            continue
            
    # If the date can't be parsed (e.g., text like "End of Month" or "Pending"), 
    # we treat it as having "no strict deadline" and keep it in the list.
    return True


def fetch_user_tasks(user_display_name, credentials):
    """Fetches tasks assigned to the user from the entire Google Sheet."""
    try:
        service = build('sheets', 'v4', credentials=credentials)
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=SHEET_RANGE).execute()
        values = result.get('values', [])
        
        if not values:
            return "⚠️ No data found in the specified range."
        
        user_tasks = []
        today = datetime.now().date()
        
        for row in values:
            # TODO: Update these indices based on your actual Google Sheet columns
            assignee = row[1] if len(row) > 1 else ""
            deadline_str = row[2] if len(row) > 2 else "" 
            
            # First, check if the task is actually assigned to the user
            if user_display_name.lower() not in assignee.lower():
                continue

            # Clean up the string just in case there are accidental spaces
            clean_date_str = deadline_str.strip()
            parsed_date = None
            
            # Tuple of date formats: 'Apr 14, 2026' and '4/30/2026'
            date_formats = ('%b %d, %Y', '%m/%d/%Y')
            
            for fmt in date_formats:
                try:
                    parsed_date = datetime.strptime(clean_date_str, fmt).date()
                    break # Success! It matched this format, so break out of the loop
                except ValueError:
                    continue # It didn't match this format, try the next one
            
            # If we successfully extracted a date and it's before today, skip the row
            if parsed_date and parsed_date < today:
                continue 
            
            # (If parsed_date is still None, it was something like "TBD", so we keep it)

            # If it passed the filters, add it to the list
            user_tasks.append(row)
            
        # --- FORMATTING LOGIC GOES HERE (Inside the try block) ---
        if not user_tasks:
            return "✅ You have no upcoming tasks!"

        # Recreate the exact formatting from your testing space!
        response_lines = ["📋 *Here are your assigned upcoming tasks:*"]
        
        for task in user_tasks:
            # Provide safe defaults if the row is missing columns
            task_name = task[0] if len(task) > 0 else "Unknown Task"
            # task[1] is the assignee
            deadline = task[2] if len(task) > 2 else "TBD"
            event_name = task[3] if len(task) > 3 else "" 

            response_lines.append(f"• *{task_name}*")
            response_lines.append(f"  ↳ *Event:* {event_name} | *Deadline:* {deadline}")

        # Join the list into a single string with line breaks
        return "\n".join(response_lines)
        
    except Exception as e:
        logging.error(f"Error fetching tasks: {e}")
        return "⚠️ An error occurred while fetching your tasks."
    
def format_request(event, credentials):
    chat_event = event.get('chat', {})
    payload = chat_event.get('messagePayload') or chat_event.get('addedToSpacePayload')
    space_name = payload.get('space', {}).get('name') if payload else None
    
    # FIX 1: Added 0
    if not space_name: return None, False, 0

    if 'messagePayload' in chat_event:
        message_data = chat_event['messagePayload'].get('message', {})
        
        # If the message sender is a BOT, ignore the message to prevent infinite loops.
        # FIX 2: Added 0
        if message_data.get('sender', {}).get('type') == 'BOT':
            return None, False, 0
        
        # 'text' contains the full message (e.g. "@BotName here")
        message_text = message_data.get('text', '').lower().strip()
        
        # 'argumentText' strips out the @BotName mention (e.g. "here")
        argument_text = message_data.get('argumentText', message_text).lower().strip()
        
        thread_name = message_data.get('thread', {}).get('name')
        sender_name = message_data.get('sender', {}).get('displayName', '')

        # --- TASK FETCHING LOGIC ---
        if argument_text == 'here':
            task_response_text = fetch_user_tasks(sender_name, credentials)
            return google_chat.CreateMessageRequest(
                parent=space_name,
                message_reply_option=google_chat.CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD,
                message={
                    'text': task_response_text,
                    'thread': {'name': thread_name}
                }
            ), False, 0  # <--- FIX 3: Added , 0 here!

        # --- TIMER LOGIC ---
        # Check for Lunch (30 mins)
        if 'lunch' in argument_text:
            return google_chat.CreateMessageRequest(
                parent=space_name,
                message_reply_option=google_chat.CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD,
                message={
                    'text': '⏳ Enjoy your lunch! I’ll remind you in 30 minutes.',
                    'thread': {'name': thread_name}
                }
            ), True, 30  
            
        if re.search(r'\b(10|taking 10)\b', argument_text):
            return google_chat.CreateMessageRequest(
                parent=space_name,
                message_reply_option=google_chat.CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD,
                message={
                    'text': '⏳ Got it! I’ll remind you in ten minutes.',
                    'thread': {'name': thread_name}
                }
            ), True, 10  
            
        # Fallback response
        return google_chat.CreateMessageRequest(
            parent=space_name,
            message_reply_option=google_chat.CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD,
            message={
                'text': f"You said: `{argument_text}`",
                'thread': {'name': thread_name}
            }
        ), False, 0  # <--- FIX 4: Added , 0 here!
        
    return None, False, 0

def schedule_reminder_task(event, minutes):
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(PROJECT_ID, LOCATION, QUEUE_ID)
    
    message_data = event['chat']['messagePayload']['message']
    payload = {
        'space_name': event['chat']['messagePayload']['space']['name'],
        'thread_name': message_data['thread']['name'],
        'minutes': minutes # Optional: send to payload if you want the reminder message to be dynamic
    }
    
    # Use the dynamic 'minutes' variable here
    d = datetime.utcnow() + timedelta(minutes=minutes) 
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(d)

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': SERVICE_URL,
            'headers': {'Content-type': 'application/json'},
            'body': json.dumps(payload).encode()
        },
        'schedule_time': timestamp
    }
    client.create_task(parent=parent, task=task)
    logging.info(f"Reminder task scheduled for {minutes} minutes.")

@app.route('/send-reminder', methods=['POST'])
def send_reminder():
    data = request.get_json()
    minutes = data.get('minutes', 10) # Fallback to 10 if not provided
    
    scopes = ['https://www.googleapis.com/auth/chat.bot']
    credentials, _ = google.auth.default(scopes=scopes)
    chat_client = google_chat.ChatServiceClient(credentials=credentials)
    
    chat_client.create_message(google_chat.CreateMessageRequest(
        parent=data['space_name'],
        message_reply_option=google_chat.CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD,
        message={
            'text': f'⏰ **Time is up!** {minutes} minutes have passed.',
            'thread': {'name': data['thread_name']}
        }
    ))
    return ('', 204)