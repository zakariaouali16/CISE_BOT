from apiclient.discovery import build
from google.oauth2 import service_account

# Specify required scopes.
SCOPES = ['https://www.googleapis.com/auth/chat.bot']

# Specify service account details.
creds = service_account.Credentials.from_service_account_file(
    'credentials.json', scopes=SCOPES)

# Build the URI and authenticate with the service account.
chat = build('chat', 'v1', credentials=creds)

# Create a Chat message.
result = chat.spaces().messages().create(

    # The space to create the message in.
    #
    # Replace SPACE_NAME with a space name.
    # Obtain the space name from the spaces resource of Chat API,
    # or from a space's URL.
    parent='spaces/SPACE_NAME',

    # The message to create.
    body={'text': 'Hello, world!'}

).execute()

# Prints details about the created message.
print(result)