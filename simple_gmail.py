import os
import base64
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow 
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from calendar_utils import add_calendar_event, list_calendar_events
# ----------------------------
# CONFIG
# ----------------------------
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/gmail.send',
          'https://www.googleapis.com/auth/calendar',
          'https://www.googleapis.com/auth/calendar.events' ]

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GMAIL_TOKEN = 'gmail_token.json'

# ----------------------------
# GMAIL FUNCTIONS
# ----------------------------
def get_gmail_service():
    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)

def read_emails(max_results=5):
    service = get_gmail_service()
    results = service.users().messages().list(userId='me', maxResults=max_results).execute()
    messages = results.get('messages', [])
    email_list = []
    for msg in messages:
        txt = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = txt['payload']['headers']
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '[No Subject]')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), '[Unknown]')
        snippet = txt.get('snippet', '')
        email_list.append({
            "id": msg['id'],
            "text": f"{len(email_list)+1}. 📧 From: {sender}\n📌 Subject: {subject}\n{snippet}"
        })
    return email_list

def send_email(to, subject, body):
    service = get_gmail_service()
    message = MIMEText(body)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId='me', body={'raw': raw}).execute()

def get_email_detail(msg_id):
    service = get_gmail_service()
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
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

    if 'parts' in payload:
        body = extract_body(payload['parts'])
    else:
        data = payload.get('body', {}).get('data')
        if data:
            try:
                body = base64.urlsafe_b64decode(data.encode('ASCII')).decode('utf-8', errors='ignore')
            except:
                body = "[Error decoding body]"
        else:
            body = ""
    return body if body else "[No readable text content]"

# ----------------------------
# TELEGRAM COMMANDS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I'm your Assistant Bot!\n\n"
        "Commands:\n"
        "/read - Read latest 5 emails\n"
        "/detail 1 - View email content\n"
        "/send to@email.com | Subject | Body - Send email\n"
        "/events - read events\n"
        "/addevent Title | YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM "
    )

async def read(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📬 Fetching your emails...")
    try:
        emails = read_emails()
        if emails:
            reply = "📥 Your latest emails:\n\n" + "\n\n".join(e['text'] for e in emails)
            context.user_data['emails'] = emails
        else:
            reply = "📭 No emails found!"
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = ' '.join(context.args)
        parts = text.split('|')
        if len(parts) != 3:
            await update.message.reply_text("❌ Format: /send to@email.com | Subject | Body")
            return
        to = parts[0].strip()
        subject = parts[1].strip()
        body = parts[2].strip()
        send_email(to, subject, body)
        await update.message.reply_text(f"✅ Email sent to {to}!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        index = int(context.args[0]) - 1
        emails = context.user_data.get('emails') or read_emails()
        if index < 0 or index >= len(emails):
            await update.message.reply_text("❌ Invalid email number. Use /read first.")
            return
        msg_id = emails[index]['id']
        body = get_email_detail(msg_id)
        await update.message.reply_text(f"📄 Email content:\n\n{body}")
    except:
        await update.message.reply_text("❌ Usage: /detail 1")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if 'send' in text:
        await update.message.reply_text("📧 Use /send to@email.com | Subject | Body")
    elif any(word in text for word in ['read', 'check', 'inbox']):
        await read(update, context)
    else:
        await update.message.reply_text(
            "🤖 Commands:\n"
            "/read - Check latest emails\n"
            "/detail 1 - View email content\n"
            "/send - Send an email\n"
            "/events - Check events\n"
            "/addevent - Add event to calendar"
        )
async def addevent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = ' '.join(context.args)
        parts = text.split('|')
        if len(parts) != 3:
            await update.message.reply_text("❌ Format(event title| start date & time | end date & time): /addevent Title | YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM")
            return
        title = parts[0].strip()
        start_dt = parts[1].strip().replace(" ","T") + ":00"
        end_dt = parts[2].strip().replace(" ", "T") + ":00"
        link = add_calendar_event(title, start_dt, end_dt)
        await update.message.reply_text(f"✅ Event added: {title}\n🔗 {link}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        events = list_calendar_events()
        if not events:
            await update.message.reply_text("📭 No upcoming events found!")
            return
        reply = "📅 Upcoming events:\n\n"
        for idx, e in enumerate(events):
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            summary = e.get('summary', 'No Title')
            # Format datetime nicely
            if 'T' in start_raw:
               from datetime import datetime
               from zoneinfo import ZoneInfo
               import re
               # Remove timezone offset before parsing
               clean_dt = re.sub(r'Z$', '+00:00', start_raw)
               dt = datetime.fromisoformat(clean_dt)
               dt_sg = dt.astimezone(ZoneInfo('Asia/Singapore'))
               start_formatted = dt_sg.strftime("%d %b %Y, %I:%M %p")
            else:
               start_formatted = start_raw
            reply += f"{idx+1}. {summary}\n⏰ {start_formatted}\n\n"

        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('read', read))
    app.add_handler(CommandHandler('send', send))
    app.add_handler(CommandHandler('detail', detail))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler('addevent', addevent))
    app.add_handler(CommandHandler('events', events))
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
