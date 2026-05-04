import urllib.request
import urllib.parse
import json
import os
from groq import Groq


# Bot
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


# Groq
GROQ_KEY = os.environ["TELEGRAM_BOT_GROQ"]
client = Groq(api_key=GROQ_KEY)


offset = 0  # for tracking which messages we’ve seen



def get_updates():
    global offset
    url = f"{BASE_URL}/getUpdates?offset={offset}&timeout=30"
    try:
        with urllib.request.urlopen(url) as r:
            data = json.load(r)
        if data["ok"] and data["result"]:
            for msg in data["result"]:
                offset = msg["update_id"] + 1
                if "message" in msg:
                    yield msg["message"]
    except Exception as e:
        print("Error fetching updates:", e)


def reply_to_message(chat_id, text):
    if not text:
        print("Skipping reply: text is None or empty")
        return

    clean_text = text.strip()
    if not clean_text:
        print("Skipping reply: cleaned text is empty")
        return

    # TELEGRAM‑SAFE max length
    MAX_MSG = 3500
    if len(clean_text) > MAX_MSG:
        clean_text = clean_text[:MAX_MSG].rstrip() + "… (Answer truncated.)"

    print("Sending reply to chat_id:", chat_id)
    print("Reply text (length):", len(clean_text))
    print("Reply text (preview):", repr(clean_text[:200]))

    data = {"chat_id": chat_id, "text": clean_text}
    payload = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(
        url=f"{BASE_URL}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as r:
            response_data = json.load(r)
        if not response_data.get("ok"):
            print("Telegram API error (from response body):", response_data)
        else:
            print("Message sent successfully (ok = True)")
    except urllib.error.HTTPError as e:
        print("HTTPError:", e)
        print("Status code:", e.code)
        print("Reason:", e.reason)
        try:
            error_body = e.read().decode("utf-8")
            print("Telegram error body:", error_body)
        except Exception as inner:
            print("Could not read error body:", inner)
    except Exception as e:
        print("Other error sending reply:", e)



print("Listening for messages...")


while True:
    try:
        for message in iter(lambda: next(get_updates(), None), None):
            chat_id = message["chat"]["id"]
            user_name = message["from"].get("first_name", "User")
            text = message.get("text", "")

            if not text:
                continue

            print(f"From {user_name}: {text}")

            # Ask Groq ...
            try:
                completion = client.chat.completions.create(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a Telegram chatbot and you respond short and clear, "
                                "always in just a few sentences, like in a messaging app. "
                                "Avoid long lists or chapters; if the answer becomes too long, "
                                "summarize it."
                            ),
                        },
                        {
                            "role": "user",
                            "content": text,
                        }
                    ],
                    model="openai/gpt-oss-120b",
                    temperature=1.0,
                    max_completion_tokens=1024,
                    top_p=1.0,
                    stream=False,
                )
                reply_text = completion.choices[0].message.content

                if not reply_text or not reply_text.strip():
                    reply_text = "I could not generate an answer, sorry."
                if len(reply_text) > 3500:
                    reply_text = reply_text[:3500].rstrip() + "… (shortened)"
            except Exception as e:
                print("Groq error:", e)
                reply_text = "I had problems processing your message, sorry."

            reply_to_message(chat_id, reply_text)
    except Exception as e:
        print("Error in main loop:", e)
        # optional: add a small wait before retrying
        import time
        time.sleep(3)
