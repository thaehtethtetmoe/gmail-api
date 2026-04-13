from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import datetime

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# 1️⃣ Create Calendar service
def get_calendar_service():
    creds = Credentials.from_authorized_user_file('gmail_token.json', SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('calendar', 'v3', credentials=creds)

# 2️⃣ Add event to calendar
def add_calendar_event(summary, start_time, end_time):
    service = get_calendar_service()
    event = {
        'summary': summary,
        'start': {'dateTime': start_time, 'timeZone': 'Asia/Singapore'},
        'end': {'dateTime': end_time, 'timeZone': 'Asia/Singapore'},
    }
    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return created_event.get('htmlLink')

# 3️⃣ Optional: list next 5 events
def list_calendar_events(max_results=5):
    service = get_calendar_service()
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    events_result = service.events().list(
        calendarId='primary', timeMin=now, maxResults=max_results, singleEvents=True, orderBy='startTime'
    ).execute()
    return events_result.get('items', [])
