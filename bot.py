import os
import io
import base64
import json
import discord
import asyncio
import fitz  # PyMuPDF
from PIL import Image
from dotenv import load_dotenv
from chatgpt import send_to_chatGpt

# 환경 변수
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID", "1412689554909171722"))

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

MEMORY_FILE = "user_histories.json"

# -----------------------------
# 기록 로드/저장
# -----------------------------
def load_histories():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("⚠️ JSON 파싱 실패 → 새로 생성")
            return {}
    return {}

def save_histories(histories):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(histories, f, ensure_ascii=False, indent=2)

user_histories = load_histories()

# -----------------------------
# 이름 추출
# -----------------------------
def extract_name(display_name: str) -> str:
    prefixes = ["매니저_", "교육생_", "멘토_", "운영자_"]
    for p in prefixes:
        if display_name.startswith(p):
            return display_name.replace(p, "")
    return display_name

# -----------------------------
# 이미지 / PDF / TXT 처리
# -----------------------------
def compress_image(image_bytes, max_size=512):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
        img.thumbnail((max_size, max_size))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return image_bytes

def extract_pdf_text(pdf_bytes):
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            texts = [page.get_text("text") for page in doc if page.get_text("text")]
            return "\n".join(texts)
    except Exception as e:
        print("⚠️ PDF 추출 실패:", e)
        return ""

# 최근 대화만 전달
def get_recent_context(history, limit=15):
    system = [m for m in history if m["role"] == "system"]
    others = [m for m in history if m["role"] != "system"]
    return system + others[-limit:]

# -----------------------------
# 봇 이벤트
# -----------------------------
@client.event
async def on_ready():
    print(f"✅ 봇 로그인 완료: {client.user}")
    print(f"💾 {len(user_histories)}명의 대화 기록 로드 완료")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.channel.id != ALLOWED_CHANNEL_ID:
        return

    try:
        display_name = message.author.display_name
        user_name = extract_name(display_name)
        user_input = message.content.strip()
        image_base64, pdf_text, txt_text = None, None, None

        # 첨부파일 처리
        if message.attachments:
            attachment = message.attachments[0]
            file_name = attachment.filename.lower()
            file_bytes = await attachment.read()

            if any(file_name.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
                file_bytes = compress_image(file_bytes)
                image_base64 = base64.b64encode(file_bytes).decode("utf-8")
                user_input = user_input or "이 이미지를 분석해줘."

            elif file_name.endswith(".pdf"):
                pdf_text = await asyncio.to_thread(extract_pdf_text, file_bytes)
                user_input = user_input or "이 PDF 내용을 요약해줘."

            elif file_name.endswith(".txt"):
                try:
                    txt_text = file_bytes.decode("utf-8", errors="ignore")
                    user_input = user_input or "이 텍스트 파일을 분석해줘."
                except Exception as e:
                    print("⚠️ TXT 파일 읽기 실패:", e)

        if not (user_input or image_base64 or pdf_text or txt_text):
            return

        # 사용자 초기화
        if user_name not in user_histories:
            user_histories[user_name] = [{
                "role": "system",
                "content": f"너는 {user_name}의 개인 AI 비서야. "
                           f"이 사용자의 이름은 {user_name}이고, 이전 대화와 파일 내용을 기억해."
            }]
            await message.channel.send(f"안녕하세요 {user_name}님! 이제부터 대화를 기억하겠습니다 😊")

        # 유저 입력 저장
        content = {"role": "user", "content": user_input}
        if image_base64: content["image_base64"] = image_base64
        if pdf_text: content["pdf_text"] = pdf_text
        if txt_text: content["txt_text"] = txt_text
        user_histories[user_name].append(content)

        # GPT 호출 (비동기)
        await message.channel.send("🔎 GPT가 분석 중입니다... 잠시만 기다려주세요.")
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, send_to_chatGpt, get_recent_context(user_histories[user_name]))

        user_histories[user_name].append({"role": "assistant", "content": response})
        save_histories(user_histories)

        # Discord 메시지 분할 전송 (길이 초과 방지)
        if response and response.strip():
            chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
            for i, chunk in enumerate(chunks, 1):
                header = f"💬 {user_name} ({i}/{len(chunks)})" if len(chunks) > 1 else f"💬 {user_name}"
                await message.channel.send(f"{header}\n```{chunk}```")
        else:
            await message.channel.send("⚠️ GPT 응답이 비어있습니다.")

    except Exception as e:
        print("❌ on_message 에러:", e, flush=True)
        await message.channel.send(f"⚠️ 오류 발생: {e}")

# 실행
client.run(DISCORD_TOKEN)
