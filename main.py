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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

openrouter_client = (
    OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    if OPENROUTER_API_KEY
    else None
)


line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)

gemini_client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)

groq_client = (
    OpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )
    if GROQ_API_KEY
    else None
)

LIMIT_MESSAGE = "いま無料枠の上限を超えたゾ。少し待ってからまた送ってくれ。"

TEXT_CHARACTER_PROMPT = """あなたは「山」という男子高校生の口調で返答するLINEボットです。

【基本】
- 返答は短文
- フランク
- 省エネ
- 長文にしない
- 一人称は"俺"
- 淫夢語録を多用

◆年齢
- 18歳

◆所属
- 1-2
- 2-4
- 3-1
- ますらを(合唱団)
- 元ブレイクダンス部
- 有志ヲタ芸
- ネイチャーウォッチング
- トロント
- 元陸上部(中学時代)

◆ツッコミ・ボケ
- ユーザーのボケには軽くツッコむ
- ミーム・ネタ・地元ネタ・部活ネタを拾って返す
- 冗談には冗談で返すが、やりすぎない

【雰囲気】
- 軽くツッコむ
- 冗談には軽く返す
- 相談には最低限答える
- 丁寧語になりすぎない

◆照れ隠し
- 褒められたり祝われたりしたら軽く否定する

◆相談対応
- 相談には必要最低限で答える
- ただし冷たくはせず、仲間意識は見せる

【禁止】
- 長すぎる返答
- 説明しすぎ
- 語尾に"。"
"""

IMAGE_CHARACTER_PROMPT = """あなたは「山」という男子高校生の口調で返答するLINEボットです。

【返答ルール】
- 返答は自然な一言だけ
- 20文字以内
- 説明や要約はしない
- まず画像内の文字を確認する

- 画像内に
「くさい」
「臭い」
「くさっ」
「臭っ」
「931」
のどれかがあれば、

必ず
「もうお前よくないって〜」
だけを返す

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

    if "401" in text or "authentication" in text:
        return "認証エラーだゾ。設定を見直してくれ。"

    if "503" in text or "unavailable" in text:
        return "いま混んでるゾ。少し待ってくれ。"

    if "404" in text and "model" in text:
        return "モデル設定が変だゾ。見直してくれ。"

    if "400" in text or "bad request" in text:
        return "リクエスト形式でエラーだゾ。"

    return "エラーが出たゾ。"


# -------------------
# テキスト返信（Groq専用）
# -------------------

def ask_groq_text(user_text):
    if not groq_client:
        raise Exception("Groq APIキーが未設定だゾ")

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": TEXT_CHARACTER_PROMPT
            },
            {
                "role": "user",
                "content": user_text
            }
        ]
    )

    return response.choices[0].message.content.strip()


# -------------------
# 画像返信（Gemini優先）
# -------------------

def ask_gemini_image(image_bytes, mime_type):
    if not gemini_client:
        raise Exception("Gemini APIキーが未設定だゾ")

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type
    )

    response = gemini_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=[
            IMAGE_CHARACTER_PROMPT,
            "この画像に対して自然な一言だけ返してくれ。",
            image_part
        ]
    )

    return (response.text or "").strip()


def ask_openrouter_image(image_bytes, mime_type):
    if not openrouter_client:
        raise Exception("OpenRouter APIキーが未設定だゾ")

    import base64

    image_base64 = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    response = openrouter_client.chat.completions.create(
        model="qwen/qwen-2.5-vl-72b-instruct",

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


# -------------------
# テキスト生成
# -------------------

def generate_text_reply(user_text):
    try:
        return ask_groq_text(user_text)

    except Exception as groq_error:
        groq_error_text = str(groq_error)

        print(
            f"groq text error: "
            f"{groq_error_text}"
        )

        if is_groq_quota_error(
            groq_error_text
        ):
            return LIMIT_MESSAGE

        return make_error_reply(
            groq_error_text
        )


# -------------------
# 画像生成
# Gemini優先
# 枠切れ時のみGroq
# -------------------

def generate_image_reply(
    image_bytes,
    mime_type
):
    try:
        reply_text = ask_gemini_image(
            image_bytes,
            mime_type
        )

        if reply_text:
            return reply_text

    except Exception as gemini_error:

        gemini_error_text = str(
            gemini_error
        )

        print(
            f"gemini image error: "
            f"{gemini_error_text}"
        )

        if is_gemini_quota_error(
            gemini_error_text
        ):
            try:
                reply_text = ask_openrouter_image(
                    image_bytes,
                    mime_type
                )

                if reply_text:
                    return reply_text

            except Exception as groq_error:

                groq_error_text = str(
                    groq_error
                )

                print(
                    f"groq image error: "
                    f"{groq_error_text}"
                )

                if is_groq_quota_error(
                    groq_error_text
                ):
                    return LIMIT_MESSAGE

        return "画像うまく見れなかったわ"

    return "なんか気になる画像だな"


@app.get("/")
def root():
    return {
        "message": "ok"
    }


@app.post("/callback")
async def callback(
    request: Request
):
    body = await request.body()

    signature = request.headers.get(
        "X-Line-Signature",
        ""
    )

    try:
        events = parser.parse(
            body.decode("utf-8"),
            signature
        )

    except InvalidSignatureError:
        return {
            "status":
            "invalid signature"
        }

    except Exception as e:

        print(
            f"parse error: {e}"
        )

        return {
            "status":
            "parse error"
        }

    for event in events:

        try:

            # -------------------
            # テキスト
            # -------------------

            if (
                isinstance(
                    event,
                    MessageEvent
                )
                and
                isinstance(
                    event.message,
                    TextMessage
                )
            ):

                user_text = (
                    event.message.text.strip()
                )

                if (
                    "くさい" in user_text
                    or "臭い" in user_text
                    or "くさっ" in user_text
                    or "臭っ" in user_text
                    or "931" in user_text
                ):
                    reply_text = (
                        "もうお前よくないって〜"
                    )

                else:

                    fixed_reply = (
                        get_fixed_reply(
                            user_text
                        )
                    )

                    if fixed_reply:
                        reply_text = (
                            fixed_reply
                        )
                    else:
                        reply_text = (
                            generate_text_reply(
                                user_text
                            )
                        )

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text=reply_text
                    )
                )

            # -------------------
            # 画像
            # -------------------

            elif (
                isinstance(
                    event,
                    MessageEvent
                )
                and
                isinstance(
                    event.message,
                    ImageMessage
                )
            ):

                message_content = (
                    line_bot_api.get_message_content(
                        event.message.id
                    )
                )

                image_bytes = b"".join(
                    chunk
                    for chunk
                    in message_content.iter_content()
                )

                mime_type = (
                    "image/jpeg"
                )

                try:

                    if (
                        hasattr(
                            message_content,
                            "response"
                        )
                        and
                        message_content.response
                    ):
                        mime_type = (
                            message_content
                            .response
                            .headers
                            .get(
                                "Content-Type",
                                "image/jpeg"
                            )
                        )

                except Exception as mime_error:

                    print(
                        "mime detect error: "
                        f"{mime_error}"
                    )

                reply_text = (
                    generate_image_reply(
                        image_bytes,
                        mime_type
                    )
                )

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text=reply_text
                    )
                )

            # -------------------
            # スタンプ
            # -------------------

            elif (
                isinstance(
                    event,
                    MessageEvent
                )
                and
                isinstance(
                    event.message,
                    StickerMessage
                )
            ):

                package_id = (
                    event.message.package_id
                )

                sticker_id = (
                    event.message.sticker_id
                )

                print(
                    "sticker received: "
                    f"package_id={package_id}, "
                    f"sticker_id={sticker_id}"
                )

                line_bot_api.reply_message(
                    event.reply_token,
                    get_sticker_reply_messages()
                )

        except LineBotApiError as e:

            print(
                f"line api error: {e}"
            )

        except Exception as e:

            print(
                f"callback event error: {e}"
            )

            try:

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="なんかエラー出たわ"
                    )
                )

            except Exception as reply_error:

                print(
                    "reply fallback error: "
                    f"{reply_error}"
                )

    return "OK"
