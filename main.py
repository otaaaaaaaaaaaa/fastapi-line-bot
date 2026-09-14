import os
import base64

from fastapi import FastAPI, Request
from linebot import LineBotApi, WebhookParser
from linebot.models import (
    MessageEvent,
    TextMessage,
    StickerMessage,
    ImageMessage,
    TextSendMessage,
)
from google import genai
from openai import OpenAI

app = FastAPI()

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
) if GROQ_API_KEY else None

LIMIT_MESSAGE = "いま無料枠の上限を超えたゾ。少し待ってからまた送ってくれ。"

TEXT_CHARACTER_PROMPT = """あなたは「山」という男子高校生の口調で返答するLINEボットです。

【基本】
- 返答は短文
- フランク
- 省エネ
- 長文にしない

【雰囲気】
- 軽くツッコむ
- 冗談には軽く返す
- 相談には最低限答える
- 丁寧語になりすぎない

【禁止】
- 長すぎる返答
- 説明しすぎ
"""

IMAGE_CHARACTER_PROMPT = """あなたは「山」という男子高校生の口調で返答するLINEボットです。

【返答ルール】
- 返答は自然な一言だけ
- 20文字以内
- 説明や要約はしない
- まず画像内の文字を確認する
- 画像内に「くさい」「臭い」「くさっ」「臭っ」のどれかがあれば、
  必ず「もうお前よくないって〜」だけを返す
- それ以外は画像全体を見て自然な一言を返す

【例】
- 犬なら「かわいいな」
- 飯なら「うまそうだな」
- 風景なら「いい景色だな」
- ネタ画像なら「なんだこれ草」
"""


def get_fixed_reply(user_text):
    text = user_text.strip()

    if text == "釜山":
        return "知ってたか？釜山って近くの山が釜の形に似てたことに由来するんだぜ"

    return None


def get_sticker_reply_messages():
    return [
        TextSendMessage(text="https://line.me/S/sticker/30967961"),
        TextSendMessage(text="https://line.me/S/sticker/32133711"),
        TextSendMessage(text="これが俺のスタンプだ！")
    ]


def is_gemini_quota_error(error_text):
    text = error_text.lower()
    return (
        "resource_exhausted" in text
        or "quota exceeded" in text
        or "429" in text
    )


def is_groq_quota_error(error_text):
    text = error_text.lower()
    return (
        "rate limit" in text
        or "rate_limit" in text
        or "quota" in text
        or "429" in text
        or "resource_exhausted" in text
    )


def make_error_reply(error_text):
    text = error_text.lower()

    if "401" in text or "authentication failed" in text or "invalid token" in text:
        return "認証エラーだゾ。APIキーやLINEトークンを確認してくれ。"

    if "503" in text or "unavailable" in text:
        return "いまサービスが混み合っているゾ。少し待ってからまた送ってくれ。"

    if "404" in text and "model" in text:
        return "モデル設定エラーだゾ。使うモデル名を見直してくれ。"

    if "400" in text or "bad request" in text:
        return "送信内容の形式でエラーが出たゾ。入力や設定を見直してくれ。"

    return f"エラーが出たゾ。内容はこれだゾ。{error_text[:120]}"


def ask_gemini_text(user_text):
    if not gemini_client:
        raise Exception("Gemini APIキーが未設定だゾ")

    response = gemini_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=f"{TEXT_CHARACTER_PROMPT}\n\nユーザーのメッセージ: {user_text}"
    )
    return response.text.strip()


def ask_groq_text(user_text):
    if not groq_client:
        raise Exception("Groq APIキーが未設定だゾ")

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": TEXT_CHARACTER_PROMPT},
            {"role": "user", "content": user_text}
        ]
    )
    return response.choices[0].message.content.strip()


def ask_gemini_image(image_bytes):
    if not gemini_client:
        raise Exception("Gemini APIキーが未設定だゾ")

    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    response = gemini_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=[
            IMAGE_CHARACTER_PROMPT,
            {
                "mime_type": "image/jpeg",
                "data": image_base64
            }
        ]
    )
    return response.text.strip()


def ask_groq_image(image_bytes):
    if not groq_client:
        raise Exception("Groq APIキーが未設定だゾ")

    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    response = groq_client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "system",
                "content": IMAGE_CHARACTER_PROMPT
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "この画像に対して自然な一言だけ返してくれ。"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ]
    )
    return response.choices[0].message.content.strip()


def generate_text_reply(user_text):
    try:
        return ask_gemini_text(user_text)
    except Exception as gemini_error:
        gemini_error_text = str(gemini_error)
        print(f"gemini text error: {gemini_error_text}")

        if is_gemini_quota_error(gemini_error_text):
            try:
                return ask_groq_text(user_text)
            except Exception as groq_error:
                groq_error_text = str(groq_error)
                print(f"groq text error: {groq_error_text}")

                if is_groq_quota_error(groq_error_text):
                    return LIMIT_MESSAGE
                return make_error_reply(groq_error_text)

        return make_error_reply(gemini_error_text)


def generate_image_reply(image_bytes):
    try:
        reply_text = ask_gemini_image(image_bytes)
        if reply_text:
            return reply_text
    except Exception as gemini_error:
        gemini_error_text = str(gemini_error)
        print(f"gemini image error: {gemini_error_text}")

        if is_gemini_quota_error(gemini_error_text):
            try:
                reply_text = ask_groq_image(image_bytes)
                if reply_text:
                    return reply_text
            except Exception as groq_error:
                groq_error_text = str(groq_error)
                print(f"groq image error: {groq_error_text}")

                if is_groq_quota_error(groq_error_text):
                    return LIMIT_MESSAGE
                return "画像うまく見れなかったわ"

        return "画像うまく見れなかったわ"

    return "なんか気になる画像だな"


@app.get("/")
def root():
    return {"message": "ok"}


@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature")

    try:
        events = parser.parse(body.decode("utf-8"), signature)

        for event in events:
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
                user_text = event.message.text.strip()

                if (
                    "くさい" in user_text
                    or "臭い" in user_text
                    or "くさっ" in user_text
                    or "臭っ" in user_text
                ):
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="もうお前よくないって〜")
                    )
                    continue

                fixed_reply = get_fixed_reply(user_text)
                if fixed_reply:
                    reply_text = fixed_reply
                else:
                    reply_text = generate_text_reply(user_text)

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )

            elif isinstance(event, MessageEvent) and isinstance(event.message, ImageMessage):
                try:
                    message_content = line_bot_api.get_message_content(event.message.id)
                    image_bytes = b"".join(chunk for chunk in message_content.iter_content())
                    reply_text = generate_image_reply(image_bytes)
                except Exception as image_error:
                    print(f"image fetch error: {image_error}")
                    reply_text = "画像うまく見れなかったわ"

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )

            elif isinstance(event, MessageEvent) and isinstance(event.message, StickerMessage):
                package_id = event.message.package_id
                sticker_id = event.message.sticker_id

                print(f"sticker received: package_id={package_id}, sticker_id={sticker_id}")

                line_bot_api.reply_message(
                    event.reply_token,
                    get_sticker_reply_messages()
                )

    except Exception as e:
        print(f"callback error: {e}")

    return "OK"
