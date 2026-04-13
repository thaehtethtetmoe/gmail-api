from flask import Flask, request, jsonify
import os
import base64
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from calendar_utils import add_calendar_event, list_calendar_events
from datetime import datetime
from zoneinfo import ZoneInfo
import re

app = Flask(__name__)
@app.route('/')
def home():
    return "API is running"

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events'
]
GMAIL_TOKEN = 'gmail_token.json'

def get_gmail_service():
    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)

# --- EMAIL ROUTES ---
@app.route('/read_emails', methods=['GET'])
def read_emails():
    try:
        service = get_gmail_service()
        results = service.users().messages().list(userId='me', maxResults=5).execute()
        messages = results.get('messages', [])
        email_list = []
        for msg in messages:
            txt = service.users().messages().get(userId='me', id=msg['id']).execute()
            headers = txt['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            snippet = txt.get('snippet', '')
            email_list.append({
                "from": sender,
                "subject": subject,
                "snippet": snippet
            })
        return jsonify({"success": True, "emails": email_list})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/send_email', methods=['POST'])
def send_email():
    try:
        data = request.json
        to = data['to']
        subject = data['subject']
        body = data['body']
        service = get_gmail_service()
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        return jsonify({"success": True, "message": f"Email sent to {to}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# --- CALENDAR ROUTES ---
@app.route('/list_events', methods=['GET'])
def list_events():
    try:
        events = list_calendar_events()
        formatted = []
        for e in events:
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            summary = e.get('summary', 'No Title')
            if 'T' in start_raw:
                clean_dt = re.sub(r'Z$', '+00:00', start_raw)
                dt = datetime.fromisoformat(clean_dt)
                dt_sg = dt.astimezone(ZoneInfo('Asia/Singapore'))
                start_formatted = dt_sg.strftime("%d %b %Y, %I:%M %p")
            else:
                start_formatted = start_raw
            formatted.append({
                "title": summary,
                "start": start_formatted
            })
        return jsonify({"success": True, "events": formatted})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/add_event', methods=['POST'])
def add_event():
    try:
        data = request.json
        title = data['title']
        start_dt = data['start'].replace(" ", "T") + ":00"
        end_dt = data['end'].replace(" ", "T") + ":00"
        link = add_calendar_event(title, start_dt, end_dt)
        return jsonify({"success": True, "link": link, "title": title})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5050))
    app.run(host='0.0.0.0', port=port)
