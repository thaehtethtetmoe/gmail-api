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
from nemoclaw_router import route_command

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import re
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
        "/daily - Get your daily briefing"
        "/reply 1 - Generate reply"
        "/sendreply - Send generated reply"     
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
    user_text = update.message.text

    try:
        result = route_command(user_text)

        # If emails
        if result.get("emails"):
            reply = "📥 Emails:\n\n"
            for e in result["emails"]:
                reply += f"📧 {e['subject']}\nFrom: {e['from']}\n\n"
            await update.message.reply_text(reply)

        # If events
        elif result.get("events"):
            reply = "📅 Events:\n\n"
            for e in result["events"]:
                reply += f"{e['title']} - {e['start']}\n"
            await update.message.reply_text(reply)

        else:
            # await update.message.reply_text(str(result)
            if "plan" in result:
                final_output = None

                for step in result["plan"]:
                action = step.get("action")
                params = step.get("params", {})

            if action == "add_event":
                link = add_calendar_event(**params)
                final_output = f"✅ Event added: {params.get('title')}"

            elif action == "list_events":
                events = list_calendar_events()
                reply = "📅 Upcoming events:\n\n"

                from datetime import datetime
                from zoneinfo import ZoneInfo
                import re

                now = datetime.now(ZoneInfo('Asia/Singapore'))

                for e in events:
                   start_raw = e['start'].get('dateTime', e['start'].get('date'))
                   summary = e.get('summary', 'No Title')

                   if 'T' not in start_raw:
                     continue

                   clean_dt = re.sub(r'Z$', '+00:00', start_raw)
                   dt = datetime.fromisoformat(clean_dt).astimezone(ZoneInfo('Asia/Singapore')) 
                   # ✅ FILTER OUT PAST EVENTS
                   if dt < now:
                     continue

                   reply += f"{summary} - {dt.strftime('%d %b %Y, %I:%M %p')}\n"

                 final_output = reply

    await update.message.reply_text(final_output)
                      

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")



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
 
        now = datetime.now(ZoneInfo('Asia/Singapore'))  
       
        for idx, e in enumerate(events):
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            summary = e.get('summary', 'No Title')

            if 'T' not in start_raw:
               continue
                       
            clean_dt = re.sub(r'Z$', '+00:00', start_raw)
            dt = datetime.fromisoformat(clean_dt).astimezone(ZoneInfo('Asia/Singapore'))

            # ✅ FILTER PAST EVENTS
            if dt < now:
                continue

            start_formatted = dt.strftime("%d %b %Y, %I:%M %p")
            reply += f"{summary}\n⏰ {start_formatted}\n\n"

        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ----------------------------
# NOTIFICATION FUNCTIONS
# ----------------------------
notified_events = set()  # track already notified events

async def check_and_notify(bot):
    try:
        events = list_calendar_events(20)
        now = datetime.now(ZoneInfo('Asia/Singapore'))

        for e in events:
            event_id = e.get('id', '')
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            summary = e.get('summary', 'No Title')

            if 'T' not in start_raw:
                continue

            clean_dt = re.sub(r'Z$', '+00:00', start_raw)
            event_time = datetime.fromisoformat(clean_dt).astimezone(ZoneInfo('Asia/Singapore'))
            diff = event_time - now
            minutes_left = diff.total_seconds() / 60

            # 12 hour reminder (between 719 and 721 minutes)
            key_12h = f"{event_id}_12h"
            if 719 <= minutes_left <= 721 and key_12h not in notified_events:
                notified_events.add(key_12h)
                msg = (f"⏰ 12-Hour Reminder!\n\n"
                       f"📅 {summary}\n"
                       f"🕐 {event_time.strftime('%d %b %Y, %I:%M %p')}\n\n"
                       f"You have 12 hours until this event!")
                await bot.send_message(chat_id=os.environ.get('TELEGRAM_CHAT_ID'), text=msg)

            # 1 hour reminder (between 59 and 61 minutes)
            key_1h = f"{event_id}_1h"
            if 55 <= minutes_left <= 65 and key_1h not in notified_events:
                notified_events.add(key_1h)
                msg = (f"🔔 1-Hour Reminder!\n\n"
                       f"📅 {summary}\n"
                       f"🕐 {event_time.strftime('%d %b %Y, %I:%M %p')}\n\n"
                       f"Your event starts in 1 hour!")
                await bot.send_message(chat_id=os.environ.get('TELEGRAM_CHAT_ID'), text=msg)

            # 30 minute reminder (between 29 and 31 minutes)
            key_30 = f"{event_id}_30"
            if 25 <= minutes_left <= 35 and key_30 not in notified_events:
                notified_events.add(key_30)
                msg = (f"🔔 30-Minute Reminder!\n\n"
                       f"📅 {summary}\n"
                       f"🕐 {event_time.strftime('%d %b %Y, %I:%M %p')}\n\n"
                       f"Your event starts in 30 minutes!")
                await bot.send_message(chat_id=os.environ.get('TELEGRAM_CHAT_ID'), text=msg)  
    except Exception as e:
        print(f"Notification error: {e}")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        reply = "🌅 *Your Daily Briefing*\n\n"

        # 📧 Emails
        emails = read_emails(3)
        if emails:
            reply += "📧 *Latest Emails:*\n"
            for e in emails:
                reply += f"- {e['text'].splitlines()[1]}\n"
        else:
            reply += "📧 No new emails\n"

        reply += "\n"

        # 📅 Events
        events = list_calendar_events(5)
        today_events = []
        now = datetime.now(ZoneInfo('Asia/Singapore'))

        for e in events:
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            if 'T' in start_raw:
                clean_dt = re.sub(r'Z$', '+00:00', start_raw)
                dt = datetime.fromisoformat(clean_dt).astimezone(ZoneInfo('Asia/Singapore'))

                if dt.date() == now.date():
                    today_events.append((e.get('summary', 'No Title'), dt))

        if today_events:
            reply += "📅 *Today's Events:*\n"
            for title, dt in today_events:
                reply += f"- {title} at {dt.strftime('%I:%M %p')}\n"
        else:
            reply += "📅 No events today\n"

        reply += "\n"

        # ⏰ Next event
        upcoming = []
        for e in events:
            start_raw = e['start'].get('dateTime', e['start'].get('date'))
            if 'T' in start_raw:
                clean_dt = re.sub(r'Z$', '+00:00', start_raw)
                dt = datetime.fromisoformat(clean_dt).astimezone(ZoneInfo('Asia/Singapore'))
                if dt > now:
                    upcoming.append((e.get('summary', 'No Title'), dt))

        if upcoming:
            next_event = sorted(upcoming, key=lambda x: x[1])[0]
            reply += f"⏰ *Next Event:*\n{next_event[0]} at {next_event[1].strftime('%d %b %I:%M %p')}\n\n"

        # 🧠 Smart summary
        reply += f"🧠 You have {len(today_events)} events today and {len(emails)} recent emails."

        await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

#reply email 
async def reply_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        index = int(context.args[0]) - 1
        emails = context.user_data.get('emails')

        if not emails or index >= len(emails):
            await update.message.reply_text("❌ Use /read first.")
            return

        selected = emails[index]

        # extract info
        sender = selected['text'].split("From: ")[1].split("\n")[0]
        subject = selected['text'].split("Subject: ")[1].split("\n")[0]

        # ✨ simple AI-style reply (you can upgrade later)
        suggested_reply = f"""Hi,

Thanks for your message regarding "{subject}". 
I will get back to you shortly.

Best regards."""

        # save draft in memory
        context.user_data['draft_reply'] = {
            "to": sender,
            "subject": f"Re: {subject}",
            "body": suggested_reply
        }

        await update.message.reply_text(
            f"📧 From: {sender}\n"
            f"Subject: {subject}\n\n"
            f"✍️ Suggested Reply:\n{suggested_reply}\n\n"
            f"Type /sendreply to send."
        )

    except:
        await update.message.reply_text("❌ Usage: /reply 1") 

async def sendreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        draft = context.user_data.get('draft_reply')

        if not draft:
            await update.message.reply_text("❌ No draft found.")
            return

        send_email(draft['to'], draft['subject'], draft['body'])

        await update.message.reply_text("✅ Reply sent!")

        context.user_data['draft_reply'] = None

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
    app.add_handler(CommandHandler('daily', daily))
    app.add_handler(CommandHandler('reply', reply_email))
    app.add_handler(CommandHandler('sendreply', sendreply))
    # Start notification scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Singapore")
   
    async def start_scheduler(app): 
        scheduler.add_job(
           check_and_notify,
           'interval',
           minutes=1,
           args=[app.bot]
         )
        scheduler.start()
        print("scheduler started")
    app.post_init = start_scheduler

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
