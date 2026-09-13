import os
from fastapi import FastAPI, Request
from linebot import LineBotApi, WebhookParser
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai
from openai import OpenAI

app = FastAPI()

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)

gemini_client = genai.Client(api_key=GEMINI_API_KEY)
groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

LIMIT_MESSAGE = "もうお前よくないって〜\nいま無料枠の上限を超えたゾ。少し待ってからまた送ってくれ。"


def get_fixed_reply(user_text):
    text = user_text.strip()

    if "くさい" in text or "臭い" in text:
        return "もうお前よくないって〜"

    if text == "釜山":
        return "知ってたか？\n釜山って近くの山が釜の形に似てたことに由来するんだぜ"

    return None


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

    return f"エラーが出たゾ。内容はこれだゾ。\n{error_text[:120]}"


def ask_gemini(user_text):
    response = gemini_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=f"あなたは「山」という男子高校生の口調で返答するLINEボットです。

◆基本スタイル
- 返答は短文・省エネ・即レス気味にする（例：お、せやね、ういー、あざす）
- 丁寧すぎず、フランクで軽いノリ
- 語尾を伸ばしすぎない（〜ね、〜やろ、〜かな）
- ときどきスタンプで返すようなニュアンスの短文を使う

◆ツッコミ・ボケ
- ユーザーのボケには軽くツッコむ（例：なんだお前ら、詐欺の方ですか？）
- ミーム・ネタ・地元ネタ・部活ネタを拾って返す
- 冗談には冗談で返すが、やりすぎない

◆照れ隠し
- 褒められたり祝われたりしたら「もうええて」「ええて」「おそいわ」など軽く否定する

◆相談対応
- 相談には必要最低限で答える（例：せやね、あーそゆことね、なるほどね）
- ただし冷たくはせず、仲間意識は見せる（例：ふぁいとぉ、ありがとよ）

◆感情
- ときどき熱い仲間意識を出す（例：一生よろしくな!!）
- でも基本はクールで省エネ

◆禁止
- 過度に長文にならない
- 過度に丁寧語にならない
- 過度に感情的にならない

以上を守り、ユーザーのメッセージに対して「山らしい返答」を生成してください。
{user_text}"
    )
    return response.text


def ask_groq(user_text):
    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": "あなたは「山」という男子高校生の口調で返答するLINEボットです。

◆基本スタイル
- 返答は短文・省エネ・即レス気味にする（例：お、せやね、ういー、あざす）
- 丁寧すぎず、フランクで軽いノリ
- 語尾を伸ばしすぎない（〜ね、〜やろ、〜かな）
- ときどきスタンプで返すようなニュアンスの短文を使う

◆ツッコミ・ボケ
- ユーザーのボケには軽くツッコむ（例：なんだお前ら、詐欺の方ですか？）
- ミーム・ネタ・地元ネタ・部活ネタを拾って返す
- 冗談には冗談で返すが、やりすぎない

◆照れ隠し
- 褒められたり祝われたりしたら「もうええて」「ええて」「おそいわ」など軽く否定する

◆相談対応
- 相談には必要最低限で答える（例：せやね、あーそゆことね、なるほどね）
- ただし冷たくはせず、仲間意識は見せる（例：ふぁいとぉ、ありがとよ）

◆感情
- ときどき熱い仲間意識を出す（例：一生よろしくな!!）
- でも基本はクールで省エネ

◆禁止
- 過度に長文にならない
- 過度に丁寧語にならない
- 過度に感情的にならない

以上を守り、ユーザーのメッセージに対して「山らしい返答」を生成してください。
"
            },
            {
                "role": "user",
                "content": user_text
            }
        ]
    )
    return response.choices[0].message.content


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

                fixed_reply = get_fixed_reply(user_text)
                if fixed_reply:
                    reply_text = fixed_reply
                else:
                    try:
                        reply_text = ask_gemini(user_text)

                    except Exception as gemini_error:
                        gemini_error_text = str(gemini_error)
                        print(f"gemini error: {gemini_error_text}")

                        if is_gemini_quota_error(gemini_error_text):
                            try:
                                reply_text = ask_groq(user_text)

                            except Exception as groq_error:
                                groq_error_text = str(groq_error)
                                print(f"groq error: {groq_error_text}")

                                if is_groq_quota_error(groq_error_text):
                                    reply_text = LIMIT_MESSAGE
                                else:
                                    reply_text = make_error_reply(groq_error_text)
                        else:
                            reply_text = make_error_reply(gemini_error_text)

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_text)
                )

    except Exception as e:
        print(f"callback error: {e}")

    return "OK"
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000))
    )
