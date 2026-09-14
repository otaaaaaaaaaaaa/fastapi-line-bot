import os

from fastapi import FastAPI, Request
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent,
    TextMessage,
    StickerMessage,
    ImageMessage,
    TextSendMessage,
)
from google import genai
from google.genai import types
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
返答は短文で、フランクで、省エネ気味にしてください。
長文にしないでください。
軽くツッコむ感じはOKです。
説明しすぎないでください。
"""

IMAGE_CHARACTER_PROMPT = """あなたは「山」という男子高校生の口調で返答するLINEボットです。
返答は自然な一言だけにしてください。
20文字以内にしてください。
説明や要約はしないでください。
まず画像内の文字を確認してください。
画像内に「くさい」「臭い」「くさっ」「臭っ」のどれかがあれば、
必ず「もうお前よくないって〜」だけを返してください。
それ以外は画像全体を見て自然な一言を返してください。
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

    if "401" in text or "authentication" in text or "invalid token" in text:
        return "認証エラーだゾ。設定を見直してくれ。"

    if "503" in text or "unavailable" in text:
        return "いま混んでるゾ。少し待ってくれ。"

    if "404" in text and "model" in text:
        return "モデル設定が変だゾ。見直してくれ。"

    if "400" in text or "bad request" in text:
        return "リクエスト形式でエラーだゾ。設定を見直してくれ。"

    return f"エラーが出たゾ。{error_text[:100]}"


def ask_gemini_text(user_text):
    if not gemini_client:
        raise Exception("Gemini APIキーが未設定だゾ")

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            TEXT_CHARACTER_PROMPT,
            f"ユーザーのメッセージ: {user_text}"
        ]
    )

    return (response.text or "").strip()


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


def ask_gemini_image(image_bytes, mime_type):
    if not gemini_client:
        raise Exception("Gemini APIキーが未設定だゾ")

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type
    )

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            IMAGE_CHARACTER_PROMPT,
            "この画像に対して自然な一言だけ返してくれ。",
            image_part
        ]
    )

    return (response.text or "").strip()


def ask_groq_image(image_bytes, mime_type):
    if not groq_client:
        raise Exception("Groq APIキーが未設定だゾ")

    import base64
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
                            "url": f"data:{mime_type};base64,{image_base64}"
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


def generate_image_reply(image_bytes, mime_type):
    try:
        reply_text = ask_gemini_image(image_bytes, mime_type)
        if reply_text:
            return reply_text
    except Exception as gemini_error:
        gemini_error_text = str(gemini_error)
        print(f"gemini image error: {gemini_error_text}")

        if is_gemini_quota_error(gemini_error_text):
            try:
                reply_text = ask_groq_image(image_bytes, mime_type)
                if reply_text:
                    return reply_text
            except Exception as groq_error:
                groq_error_text = str(groq_error)
                print(f"groq image error: {groq_error_text}")

                if is_groq_quota_error(groq_error_text):
                    return LIMIT_MESSAGE

        return "画像うまく見れなかったわ"

    return "なんか気になる画像だな"


@app.get("/")
def root():
    return {"message": "ok"}


@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return {"status": "invalid signature"}
    except Exception as e:
        print(f"parse error: {e}")
        return {"status": "parse error"}

    for event in events:
        try:
            if isinstance(event, MessageEvent) and isinstance(event.message, TextMessage):
                user_text = event.message.text.strip()

                if (
                    "くさい" in user_text
                    or "臭い" in user_text
                    or "くさっ" in user_text
                    or "臭っ" in user_text
                ):
                    reply_text = "もうお前よくないって〜"
                else:
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
                message_content = line_bot_api.get_message_content(event.message.id)
                image_bytes = b"".join(chunk for chunk in message_content.iter_content())

                mime_type = "image/jpeg"
                try:
                    if hasattr(message_content, "response") and message_content.response:
                        mime_type = message_content.response.headers.get("Content-Type", "image/jpeg")
                except Exception as mime_error:
                    print(f"mime detect error: {mime_error}")

                reply_text = generate_image_reply(image_bytes, mime_type)

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

        except LineBotApiError as e:
            print(f"line api error: {e}")
        except Exception as e:
            print(f"callback event error: {e}")
            try:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="なんかエラー出たわ")
                )
            except Exception as reply_error:
                print(f"reply fallback error: {reply_error}")

    return "OK"
