from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.post("/")
async def chat_endpoint(request: Request):
    # Parse the incoming JSON payload from Google Chat
    event = await request.json()
    
    # Determine the type of event
    event_type = event.get("type")
    
    if event_type == "ADDED_TO_SPACE":
        space_type = event.get("space", {}).get("type")
        if space_type == "ROOM":
            text = "Thanks for adding me to this space!"
        else:
            text = "Thanks for sending me a direct message!"
            
    elif event_type == "MESSAGE":
        user_message = event.get("message", {}).get("text", "")
        # Echo the message back to the user
        text = f"You said: {user_message}. How can I help?"
        
    else:
        text = "Hello! I am a FastAPI bot."

    # Return the response format expected by Google Chat
    return {"text": text}

if __name__ == "__main__":
    # Cloud Run expects apps to listen on port 8080 (or the PORT env var)
    uvicorn.run(app, host="0.0.0.0", port=8080)