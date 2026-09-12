from fastapi import FastAPI, Request
from linebot import LineBotApi, WebhookParser
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = FastAPI()

CHANNEL_ACCESS_TOKEN = "bzILIsli1d9N2ZbBeJdJFIJYJDuoXBEfa0bQyeB9B9aImRuY1n8Yh1trt6zFv2rtD6GnF1//cxzDE8onp8OfSwawcYGG9pmBmUAhBgp7tRTJ8CpguJ9zdFUIYxAvDSwON+P8WRm0NoKJiGPtsx65NgdB04t89/1O/w1cDnyilFU="
CHANNEL_SECRET = "ef1635f70c6c5541b4cec5e2e2320913"

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)

from config import OPENAI_API_KEY
from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature")
    events = parser.parse(body.decode(), signature)

    for event in events:
        if isinstance(event, MessageEvent):

            ai_response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "あなたは山崎聡太のように、短く要点を押さえつつ、丁寧でカジュアルな口調で返事するLINEボットです。"},
                    {"role": "user", "content": event.message.text}
                ]
            )

            reply_text = ai_response.choices[0].message["content"]

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )

    return "OK"
