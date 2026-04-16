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

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration for Cloud Tasks (Update these with your info)
PROJECT_ID = "fabbot-493206"
LOCATION = "us-central1"
QUEUE_ID = "reminder-queue"
SERVICE_URL = "https://fastapi-chat-bot-457040200265.us-central1.run.app/send-reminder" # Endpoint for the callback

@app.route('/', methods=['POST'])
def receive_message():
    envelope = request.get_json()
    if not envelope: return 'Bad Request', 400

    pubsub_message = envelope.get('message')
    if pubsub_message and 'data' in pubsub_message:
        data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        event = json.loads(data)
        
        try:
            scopes = ['https://www.googleapis.com/auth/chat.bot']
            credentials, _ = google.auth.default(scopes=scopes)
            chat_client = google_chat.ChatServiceClient(credentials=credentials)
            
            chat_request, needs_timer = format_request(event)
            
            if chat_request:
                chat_client.create_message(chat_request)
                
                # If a reminder was requested, schedule the Cloud Task
                if needs_timer:
                    schedule_reminder_task(event)
                    
        except Exception as e:
            logging.error(f"Error: {e}")
            return 'Internal Error', 500

    return ('', 204)

def format_request(event):
    chat_event = event.get('chat', {})
    payload = chat_event.get('messagePayload') or chat_event.get('addedToSpacePayload')
    space_name = payload.get('space', {}).get('name') if payload else None
    
    if not space_name: return None, False

    if 'messagePayload' in chat_event:
        message_text = chat_event['messagePayload']['message']['text'].lower().strip()
        thread_name = chat_event['messagePayload']['message']['thread']['name']
        
        # Detection logic: Matches "10" or "taking 10"
        if re.search(r'\b(10|taking 10)\b', message_text):
            return google_chat.CreateMessageRequest(
                parent=space_name,
                message={
                    'text': '⏳ Got it! I’ll remind you in 10 minutes.',
                    'thread': {'name': thread_name}
                }
            ), True # True signals that we need to start a timer
            
        # Default echo response
        return google_chat.CreateMessageRequest(
            parent=space_name,
            message_reply_option=google_chat.CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD,
            message={
                'text': f"You said: `{message_text}`",
                'thread': {'name': thread_name}
            }
        ), False
        
    return None, False

def schedule_reminder_task(event):
    """Creates a task to be sent to the /send-reminder endpoint in 10 minutes."""
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(PROJECT_ID, LOCATION, QUEUE_ID)
    
    # Data to pass to the reminder endpoint
    payload = {
        'space_name': event['chat']['messagePayload']['space']['name'],
        'thread_name': event['chat']['messagePayload']['message']['thread']['name']
    }
    
    # Schedule for 10 minutes from now
    d = datetime.utcnow() + timedelta(minutes=2)
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
    logging.info("Reminder task scheduled.")

@app.route('/send-reminder', methods=['POST'])
def send_reminder():
    """This endpoint is called by Cloud Tasks after 10 minutes."""
    data = request.get_json()
    
    scopes = ['https://www.googleapis.com/auth/chat.bot']
    credentials, _ = google.auth.default(scopes=scopes)
    chat_client = google_chat.ChatServiceClient(credentials=credentials)
    
    chat_client.create_message(google_chat.CreateMessageRequest(
        parent=data['space_name'],
        message={
            'text': '⏰ **Time is up!** 10 minutes have passed.',
            'thread': {'name': data['thread_name']}
        }
    ))
    return ('', 204)