import os
import re
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_KEY")
MODEL = os.getenv("GPT_MODEL", "gpt-5")

client = OpenAI(api_key=OPENAI_KEY)


def clean_text(text):
    """PDF 등에서 불필요한 제어문자 제거"""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text).strip()


def send_to_chatGpt(messages, model=MODEL):
    try:
        last_message = messages[-1]
        content_blocks = []

        # --- 텍스트 ---
        text = last_message.get("content", "").strip()
        if text:
            content_blocks.append({"type": "input_text", "text": text})

        # --- 이미지 ---
        if "image_base64" in last_message:
            b64 = last_message["image_base64"]
            content_blocks.append({
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{b64}"
            })

        # --- PDF ---
        if "pdf_text" in last_message:
            pdf_text = clean_text(last_message["pdf_text"])
            if not pdf_text:
                pdf_text = "(이 PDF는 텍스트가 포함되지 않았습니다. 아마도 이미지 기반 스캔일 수 있습니다.)"
            else:
                pdf_text = pdf_text[:4000]
            content_blocks.append({
                "type": "input_text",
                "text": f"[PDF 내용]\n{pdf_text}"
            })

        if not content_blocks:
            content_blocks.append({"type": "input_text", "text": "내용 없음"})

        # --- GPT 호출 ---
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": content_blocks}],
            max_output_tokens=2000,
        )

        # --- 응답 파싱 (최신 SDK 대응) ---
        message_content = None
        if hasattr(response, "output_text") and response.output_text:
            message_content = response.output_text
        elif hasattr(response, "output") and response.output:
            try:
                for out in response.output:
                    if hasattr(out, "content"):
                        for c in out.content:
                            if hasattr(c, "text"):
                                message_content = c.text
                                break
            except Exception:
                pass

        if not message_content:
            return "⚠️ GPT로부터 응답이 오지 않았습니다."

        print(f"🧠 사용 모델: {getattr(response, 'model', '알 수 없음')}", flush=True)
        return message_content

    except Exception as e:
        print("OpenAI API 호출 에러:", e, flush=True)
        return "⚠️ API 호출 중 오류가 발생했습니다."
