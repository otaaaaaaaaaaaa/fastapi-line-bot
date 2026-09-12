import os
from fastapi import FastAPI, Request
from linebot import LineBotApi, WebhookParser
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = FastAPI()

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash-latest")


@app.get("/")
def root():
    return {"message": "ok"}


@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature")

    try:
        events = parser.parse(body.decode(), signature)

        for event in events:
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
                user_text = event.message.text

                prompt = f"あなたは親切で短く答えるアシスタントです。次のメッセージに日本語で返信してください。{user_text}"
                response = model.generate_content(prompt)
                reply_text = response.text

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )

    except Exception as e:
        print(f"error: {e}")

    return "OK"
