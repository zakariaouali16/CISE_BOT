from fastapi import FastAPI, Request
import uvicorn
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

@app.post("/")
async def chat_endpoint(request: Request):
    logger.info("--- New POST request received ---")
    
    try:
        # Safely attempt to parse the incoming JSON
        try:
            event = await request.json()
        except Exception:
            return {"text": "Received empty request."}
            
        logger.info(f"Raw payload received: {event}")

        # 1. Handle Google Workspace Add-on Format (Your Current Setup)
        if "chat" in event:
            logger.info("Detected Google Workspace Add-on payload structure.")
            chat_data = event.get("chat", {})
            
            # Detect if it is a new message
            if "messagePayload" in chat_data:
                user_message = chat_data["messagePayload"].get("message", {}).get("text", "")
                logger.info(f"Extracted user message: '{user_message}'")
                
                # --- This is where your time tracking logic will go! ---
                text = f"You said: {user_message}. I am ready to track your tasks and breaks!"
                
            # Detect if the bot was just added to a space/DM
            else:
                text = "Thanks for adding me! I am ready to help you track your work hours."
                
            # WRONG (Standard Chat API format):
            # response_data = {"text": text} 
            
            # RIGHT (Workspace Add-on format):
            response_data = {
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
            
            logger.info(f"Sending response: {response_data}")
            return response_data

        # 2. Handle Standard Google Chat Format (Fallback just in case)
        event_type = event.get("type")
        if event_type:
            logger.info("Detected Standard Google Chat App payload structure.")
            if event_type == "MESSAGE":
                user_message = event.get("message", {}).get("text", "")
                return {"text": f"You said: {user_message}. How can I help?"}
            elif event_type == "ADDED_TO_SPACE":
                return {"text": "Thanks for adding me to this space!"}

        # 3. Catch-all for unknown payloads
        logger.warning("Payload did not match expected Add-on or Chat App formats.")
        return {"text": "Hello! I am online but received an unknown payload."}

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)
        return {"text": "Sorry, I encountered an internal error."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)