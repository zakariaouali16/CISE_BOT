import base64
import json
import logging
import os
from flask import Flask, request
from google.apps import chat_v1 as google_chat
import google.auth

app = Flask(__name__)

# Configure Cloud Logging
logging.basicConfig(level=logging.INFO)

@app.route('/', methods=['POST'])
def receive_message():
    envelope = request.get_json()
    if not envelope:
        logging.error("No JSON envelope received.")
        return 'Bad Request', 400

    pubsub_message = envelope.get('message')
    if pubsub_message and 'data' in pubsub_message:
        # Decode the Chat event from the Pub/Sub wrapper
        data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        event = json.loads(data)
        logging.info(f"Processing event: {event.get('type')}")

        try:
            # Authenticate using the Cloud Run Service Account identity
            scopes = ['https://www.googleapis.com/auth/chat.bot']
            credentials, _ = google.auth.default(scopes=scopes)
            chat_client = google_chat.ChatServiceClient(credentials=credentials)
            
            chat_request = format_request(event)
            if chat_request:
                chat_client.create_message(chat_request)
                
        except Exception as e:
            logging.error(f"Error processing Chat response: {e}")
            return 'Internal Error', 500

    return ('', 204)

def format_request(event):
    """Business logic for bot responses."""
    chat_event = event.get('chat', {})
    
    if 'removedFromSpacePayload' in chat_event:
        return None
        
    payload = chat_event.get('messagePayload') or chat_event.get('addedToSpacePayload')
    space_name = payload.get('space', {}).get('name') if payload else None
    
    if not space_name:
        return None

    if 'addedToSpacePayload' in chat_event:
        return google_chat.CreateMessageRequest(
            parent=space_name,
            message={'text': '✅ FabBot is now active in this space!'}
        )
        
    elif 'messagePayload' in chat_event:
        message = chat_event['messagePayload']['message']
        return google_chat.CreateMessageRequest(
            parent=space_name,
            message_reply_option=google_chat.CreateMessageRequest.MessageReplyOption.REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD,
            message={
                'text': f"You said: `{message['text']}`",
                'thread': {'name': message['thread']['name']}
            }
        )
    return None