import os
from fastapi import FastAPI, Request
from linebot import LineBotApi, WebhookParser
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai

app = FastAPI()

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)
client = genai.Client(api_key=GEMINI_API_KEY)


def make_error_reply(error_text):
    text = error_text.lower()

    if "resource_exhausted" in text or "quota exceeded" in text or "429" in text:
        return "いま無料枠の上限を超えたゾ。少し待ってからまた送ってくれ。"

    if "401" in text or "authentication failed" in text or "invalid token" in text:
        return "認証エラーだゾ。LINEかAPIのトークン設定を確認してくれ。"

    if "503" in text or "unavailable" in text:
        return "いまサービスが混み合っているゾ。少し待ってからまた送ってくれ。"

    if "404" in text and "model" in text:
        return "モデル設定エラーだゾ。使うモデル名を見直してくれ。"

    if "400" in text or "bad request" in text:
        return "送信内容の形式でエラーが出たゾ。入力や設定を見直してくれ。"

    return f"エラーが出たゾ。内容はこれだゾ。{error_text[:120]}"


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

                try:
                    response = client.models.generate_content(
                        model="gemini-3.6-flash",
                        contents=f"あなたは親切で短く答えるアシスタントです。次のメッセージに日本語で返信してください。{user_text}"
                    )
                    reply_text = response.text

                except Exception as e:
                    error_text = str(e)
                    print(f"gemini error: {error_text}")
                    reply_text = make_error_reply(error_text)

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )

    except Exception as e:
        print(f"callback error: {e}")

    return "OK"
