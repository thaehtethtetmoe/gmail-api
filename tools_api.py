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

def load_token():
    base64_token = os.environ.get("GMAIL_TOKEN_BASE64")
    if base64_token:
        with open("gmail_token.json", "wb") as f:
            f.write(base64.b64decode(base64_token))
    return "gmail_token.json"

GMAIL_TOKEN = load_token()

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

@app.route('/email_detail', methods=['GET'])
def email_detail():
    try:
        msg_id = request.args.get('id')
        if not msg_id:
            return jsonify({"success": False, "error": "Missing email id"})

        service = get_gmail_service()
        msg = service.users().messages().get(
            userId='me',
            id=msg_id,
            format='full'
        ).execute()

        payload = msg.get('payload', {})

        def extract_body(parts):
            for part in parts:
                if 'parts' in part:
                    body = extract_body(part['parts'])
                    if body:
                        return body
                elif part.get('mimeType') == 'text/plain':
                    data = part.get('body', {}).get('data')
                    if data:
                        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            return ""

        body = ""

        if 'parts' in payload:
            body = extract_body(payload['parts'])
        else:
            data = payload.get('body', {}).get('data')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

        return jsonify({
            "success": True,
            "id": msg_id,
            "body": body if body else "[No readable content]"
        })

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
        return jsonify({"success": True, "link": link, "title": title,"server_date": datetime.now(ZoneInfo('Asia/Singapore')).strftime("%Y-%m-%d"),
            "server_time": datetime.now(ZoneInfo('Asia/Singapore')).strftime("%H:%M") })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5050))
    app.run(host='0.0.0.0', port=port)
