import os
import io
import base64
import json
import discord
import asyncio
import fitz  # PyMuPDF (PDF 텍스트 추출)
from PIL import Image
from dotenv import load_dotenv
from chatgpt import send_to_chatGpt

# -----------------------------
# 환경 변수 로드
# -----------------------------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# -----------------------------
# 디스코드 설정
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 채널 및 메모리 파일 설정
ALLOWED_CHANNEL_ID = 1412689554909171722
MEMORY_FILE = "user_histories.json"

# -----------------------------
# 유저 기록 로드 / 저장
# -----------------------------
def load_histories():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("⚠️ user_histories.json 파싱 실패 → 새로 초기화합니다.")
            return {}
    return {}

def save_histories(histories):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(histories, f, ensure_ascii=False, indent=2)

user_histories = load_histories()

# -----------------------------
# 별명에서 실제 이름 추출
# -----------------------------
def extract_name(display_name: str) -> str:
    prefixes = ["매니저_", "교육생_", "멘토_", "운영자_"]
    for p in prefixes:
        if display_name.startswith(p):
            return display_name.replace(p, "")
    return display_name

# -----------------------------
# 이미지 압축
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

# -----------------------------
# PDF 텍스트 추출
# -----------------------------
def extract_pdf_text(pdf_bytes):
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            texts = []
            for page in doc:
                text = page.get_text("text")
                if text:
                    texts.append(text)
            return "\n".join(texts)
    except Exception as e:
        print("⚠️ PDF 추출 실패:", e)
        return ""

# -----------------------------
# GPT에 전달할 최근 대화만 선택
# -----------------------------
def get_recent_context(history, limit=15):
    """
    GPT에 보낼 최근 대화만 선택 (system + 최근 n개)
    """
    system_message = [msg for msg in history if msg["role"] == "system"]
    other_messages = [msg for msg in history if msg["role"] != "system"]
    return system_message + other_messages[-limit:]

# -----------------------------
# 봇 시작 시
# -----------------------------
@client.event
async def on_ready():
    print(f"✅ 봇 로그인 완료: {client.user}")
    print(f"💾 {len(user_histories)}명의 대화 기록 로드 완료")

# -----------------------------
# 메시지 처리
# -----------------------------
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
        image_base64, pdf_text = None, None

        # -------------------------
        # 첨부파일 처리
        # -------------------------
        if message.attachments:
            attachment = message.attachments[0]
            file_name = attachment.filename.lower()
            file_bytes = await attachment.read()

            # 이미지 처리
            if any(file_name.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
                file_bytes = compress_image(file_bytes)
                image_base64 = base64.b64encode(file_bytes).decode("utf-8")
                user_input = user_input or "이 이미지를 분석해줘."

            # PDF 처리
            elif file_name.endswith(".pdf"):
                pdf_text = await asyncio.to_thread(extract_pdf_text, file_bytes)
                user_input = user_input or "이 PDF 파일의 내용을 요약해줘."

        if not (user_input or image_base64 or pdf_text):
            return

        # -------------------------
        # 유저 기록이 없으면 초기화
        # -------------------------
        if user_name not in user_histories:
            user_histories[user_name] = [{
                "role": "system",
                "content": f"너는 {user_name}의 개인 AI 비서야. "
                           f"이 사용자의 이름은 {user_name}이고, 질문·이미지·PDF 내용을 기억해. "
                           f"이 사람은 Discord에서 활동하는 실제 사용자야."
            }]
            await message.channel.send(f"안녕하세요 {user_name}님! 이제부터 당신의 이름과 대화를 기억하겠습니다 😊")

        # -------------------------
        # “내가 누군지 알아?” 감지
        # -------------------------
        if "누군지 알아" in user_input or "내 이름" in user_input:
            await message.channel.send(f"당연하죠 😊 {user_name}님이에요. 이전에 주신 메시지와 파일들도 기억하고 있어요!")
            return

        # -------------------------
        # 유저 입력 저장
        # -------------------------
        content_block = {"role": "user", "content": user_input}
        if image_base64:
            content_block["image_base64"] = image_base64
        if pdf_text:
            content_block["pdf_text"] = pdf_text

        user_histories[user_name].append(content_block)

        # -------------------------
        # GPT 응답 생성 (최근 15개만 전달)
        # -------------------------
        context = get_recent_context(user_histories[user_name], limit=15)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, send_to_chatGpt, context)

        # -------------------------
        # 응답 저장 및 출력
        # -------------------------
        user_histories[user_name].append({"role": "assistant", "content": response})
        save_histories(user_histories)

        if response and response.strip():
            chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
            for idx, chunk in enumerate(chunks, start=1):
                header = f"💬 {user_name} ({idx}/{len(chunks)})" if len(chunks) > 1 else f"💬 {user_name}"
                await message.channel.send(f"{header}\n```{chunk}```")
        else:
            await message.channel.send("⚠️ GPT 응답이 비어있습니다.")

    except Exception as e:
        print("❌ on_message 에러:", e, flush=True)
        await message.channel.send("⚠️ 오류가 발생했습니다.")

# -----------------------------
# 봇 실행
# -----------------------------
client.run(DISCORD_TOKEN)
