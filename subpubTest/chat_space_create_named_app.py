from google.oauth2 import service_account
from apiclient.discovery import build

# Define your app's authorization scopes.
# When modifying these scopes, delete the file token.json, if it exists.
SCOPES = ["https://www.googleapis.com/auth/chat.app.spaces.create"]

def main():
    '''
    Authenticates with Chat API using app authentication,
    then creates a Chat space.
    '''

    # Specify service account details.
    creds = (
        service_account.Credentials.from_service_account_file('credentials.json')
        .with_scopes(SCOPES)
    )

    # Build a service endpoint for Chat API.
    chat = build('chat', 'v1', credentials=creds)

    # Use the service endpoint to call Chat API.
    result = chat.spaces().create(

      # Details about the space to create.
      body = {

        # To create a named space, set spaceType to SPACE.
        'spaceType': 'SPACE',

        # The user-visible name of the space.
        'displayName': 'API-made',

        # The customer ID of the Workspace domain.
        'customer': 'CUSTOMER'
      }

      ).execute()

    # Prints details about the created space.
    print(result)

if __name__ == '__main__':
    main()