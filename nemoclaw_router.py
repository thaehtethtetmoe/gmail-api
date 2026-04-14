import requests
import json
import re
import datetime
API_BASE = "https://gmail-api-2ar5.onrender.com"

def ask_llm(prompt):
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        }
    )
    return response.json()['response']

def extract_json(text):
    # Strip markdown code fences
    text = re.sub(r'```(?:json)?', '', text)
    # Find all {...} blocks
    matches = re.findall(r'\{[^{}]*\}', text, re.DOTALL)
    # Walk in reverse — last block is usually the real answer, not an echoed example
    for candidate in reversed(matches):
        try:
            parsed = json.loads(candidate.strip())
            if "action" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue
    return None

# ----------------------------
# Convert "YYYY-MM-DD HH:MM" → "YYYY-MM-DDTHH:MM:00"
# ----------------------------
def to_iso(dt_str):
    if not dt_str:
        return ""
    dt_str = dt_str.strip()
    # Already ISO format
    if "T" in dt_str:
        return dt_str if dt_str.endswith(":00") or len(dt_str) > 16 else dt_str + ":00"
    # "YYYY-MM-DD HH:MM" → "YYYY-MM-DDTHH:MM:00"
    try:
        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        return dt_str

def route_command(text):
    today = datetime.date.today().strftime("%Y-%m-%d")
    text_lower = text.lower()

    # Fast keyword shortcuts — bypass LLM for obvious intents
    if any(w in text_lower for w in ["read email", "check email", "inbox", "my email", "my emails", "read my email"]):
        return requests.get(f"{API_BASE}/read_emails").json()

    if any(w in text_lower for w in ["calendar", "schedule", "events", "my schedule"]):
        return requests.get(f"{API_BASE}/list_events").json()

    # LLM for everything else (send email, add event, ambiguous phrasing)
    prompt = f"""
You are a JSON-only intent extractor. Output ONE JSON object and NOTHING else.
No explanation. No markdown. No code fences. No extra text. No examples.

Today's date: {today}

Valid actions:
- {{"action":"read_emails"}}
- {{"action":"list_events"}}
- {{"action":"send_email","to":"...","subject":"...","body":"..."}}
- {{"action":"add_event","title":"...","start":"YYYY-MM-DD HH:MM","end":"YYYY-MM-DD HH:MM"}}

### EXAMPLES
User: read my emails
{{"action":"read_emails"}}

User: check my schedules
{{"action":"list_events"}}

User: send email to john@gmail.com subject Meeting body See you at 3pm
{{"action":"send_email","to":"john@gmail.com","subject":"Meeting","body":"See you at 3pm"}}

User: add dentist appointment tomorrow 2pm to 3pm
{{"action":"add_event","title":"Dentist","start":"YYYY-MM-DD 14:00","end":"YYYY-MM-DD HH:MM"}}
### TASK
User: {text}
"""    
    raw = ask_llm(prompt)
    print("AI raw:", raw)

    decision = extract_json(raw)
    if not decision:
        return {"error": f"Could not parse AI response: {raw[:200]}"}

    action = decision.get("action")

    if action == "read_emails":
        return requests.get(f"{API_BASE}/read_emails").json()

    if action == "list_events":
        return requests.get(f"{API_BASE}/list_events").json()

    if action == "send_email":
        return requests.post(
            f"{API_BASE}/send_email",
            json={
                "to": decision.get("to", ""),
                "subject": decision.get("subject", ""),
                "body": decision.get("body", "")
            }
        ).json()

    if action == "add_event":
        start = to_iso(decision.get("start", ""))
        end   = to_iso(decision.get("end", ""))
        print(f"Adding event: {decision.get('title')} | {start} → {end}")
        return requests.post(
            f"{API_BASE}/add_event",
            json={
                "title": decision.get("title", ""),
                "start": decision.get("start", ""),
                "end": decision.get("end", "")
            }
        ).json()

    return {"error": f"Unknown action: {action}"}

    

if __name__ == "__main__":
    while True:
        user_input = input("You: ")
        result = route_command(user_input)
        print("Bot:", result)
