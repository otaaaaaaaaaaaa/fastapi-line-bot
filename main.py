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
from supabase import create_client

from prompts import TEXT_CHARACTER_PROMPT, IMAGE_CHARACTER_PROMPT

import csv
import json

PROFILE_CSV_PATH = "profile.csv"
HISTORY_CSV_PATH = "history.csv"

app = FastAPI()

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


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

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

LIMIT_MESSAGE = "いま無料枠の上限を超えたゾ。少し待ってからまた送ってくれ。"

def get_user_memories(user_id):
    try:

        result = (
            supabase
            .table("user_memories")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )

        memories = []

        for row in result.data:

            memories.append(
                f"{row['key']} : {row['value']}"
            )

        return "\n".join(memories)

    except Exception as e:

        print(
            f"memory load error: {e}"
        )

        return ""

def save_memory(
    user_id,
    key,
    value
):
    try:

        existing = (
            supabase
            .table("user_memories")
            .select("*")
            .eq("user_id", user_id)
            .eq("key", key)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("user_memories")
                .update(
                    {
                        "value": value
                    }
                )
                .eq("user_id", user_id)
                .eq("key", key)
                .execute()
            )

        else:

            (
                supabase
                .table("user_memories")
                .insert(
                    {
                        "user_id": user_id,
                        "key": key,
                        "value": value
                    }
                )
                .execute()
            )

    except Exception as e:

        print(
            f"memory save error: {e}"
        )

def extract_memory(user_text):

    try:

        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",

            messages=[
                {
                    "role": "system",
                    "content":
                    """
                    ユーザーの発言から
                    記憶すべきプロフィール情報を抽出せよ。

                    JSONのみ返すこと。

                    例

                    {"key":"部活","value":"陸上部"}

                    該当なしなら

                    {}
                    """
                },
                {
                    "role": "user",
                    "content": user_text
                }
            ]
        )

        content = (
            response
            .choices[0]
            .message
            .content
        )

        return json.loads(content)

    except Exception:

        return {}


def load_fixed_replies():
    fixed_replies = []

    try:
        with open(
            "fixed.csv",
            encoding="utf-8-sig"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:
                fixed_replies.append(
                    {
                        "keyword": row["keyword"],
                        "reply": row["reply"]
                    }
                )

    except Exception as e:
        print(
            f"fixed.csv load error: {e}"
        )

    return fixed_replies


def load_profile_csv():
    profile = []

    try:
        with open(
            PROFILE_CSV_PATH,
            encoding="utf-8-sig"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                profile.append(
                    f"{row['項目']} : {row['値']}"
                )

    except Exception as e:

        print(
            f"profile.csv load error: {e}"
        )

    return profile


def load_history_csv():
    history = []

    try:
        with open(
            HISTORY_CSV_PATH,
            encoding="utf-8-sig"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                history.append(
                    f"{row['年月']} : {row['出来事']}"
                )

    except Exception as e:

        print(
            f"history.csv load error: {e}"
        )

    return history


FIXED_REPLIES = load_fixed_replies()

PROFILE_DATA = load_profile_csv()
HISTORY_DATA = load_history_csv()


def get_fixed_reply(user_text):
    text = user_text.strip()

    for item in FIXED_REPLIES:

        keyword = item["keyword"]

        if keyword in text:
            return item["reply"]

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

def ask_groq_text(
    user_text,
    user_id
):
    if not groq_client:
        raise Exception("Groq APIキーが未設定だゾ")

    profile_text = "\n".join(
        PROFILE_DATA
    )

    history_text = "\n".join(
        HISTORY_DATA
    )

    memory_text = get_user_memories(
    user_id
    )


    print("=== PROFILE ===")
    print(profile_text)
    
    print("=== HISTORY ===")
    print(history_text)


    system_prompt = f"""
{TEXT_CHARACTER_PROMPT}

あなた自身の情報は以下である。

【プロフィール】
{profile_text}

【過去の出来事】
{history_text}

【ユーザーの記憶】
{memory_text}

プロフィールや過去の出来事に関する質問には、
上記情報を最優先で使用すること。

プロフィールに情報が存在する場合は
必ずその情報に従うこと。

プロフィールに情報が存在しない場合は、
キャラクターとして自然な範囲で創作してよい。

ただしプロフィールと矛盾する内容は
絶対に作らないこと。
"""


    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_text
            }
        ]
    )

    return (
        response
        .choices[0]
        .message
        .content
        .strip()
    )


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

def generate_text_reply(
    user_text,
    user_id
):
    try:

        memory = extract_memory(
            user_text
        )

        if (
            "key" in memory
            and
            "value" in memory
        ):

            save_memory(
                user_id,
                memory["key"],
                memory["value"]
            )

        return ask_groq_text(
            user_text,
            user_id
        )

    except Exception as groq_error:

        groq_error_text = str(
            groq_error
        )

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

                fixed_reply = get_fixed_reply(
                    user_text
                )

                if fixed_reply:
                    reply_text = fixed_reply

                else:
                    reply_text = generate_text_reply(
                        user_text
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

                user_id = (
                    event.source.user_id
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
