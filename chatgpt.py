import os
import re
import time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_KEY")
MODEL = os.getenv("GPT_MODEL", "gpt-5")

client = OpenAI(api_key=OPENAI_KEY)

def clean_text(text):
    """PDF, TXT 등에서 제어문자 제거"""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text).strip()

def chunk_text(text, size=6000):
    """긴 텍스트를 일정 길이로 나눔"""
    text = clean_text(text)
    return [text[i:i+size] for i in range(0, len(text), size)]

def send_to_chatGpt(messages, model=MODEL):
    """
    GPT에게 메시지 전송 (긴 TXT 파일도 자동 분할 처리)
    """
    try:
        last = messages[-1]
        blocks = []

        # 기본 입력 텍스트
        text = last.get("content", "").strip()
        if text:
            blocks.append({"type": "input_text", "text": text})

        # 이미지
        if "image_base64" in last:
            b64 = last["image_base64"]
            blocks.append({
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{b64}"
            })

        # PDF
        if "pdf_text" in last:
            pdf_text = clean_text(last["pdf_text"])
            blocks.append({"type": "input_text", "text": f"[PDF 내용]\n{pdf_text}"})

        # TXT (길면 자동 분할)
        if "txt_text" in last:
            txt_text = clean_text(last["txt_text"])
            chunks = chunk_text(txt_text)
            if len(chunks) > 1:
                summary_results = []
                for idx, chunk in enumerate(chunks, 1):
                    print(f"📄 TXT 조각 {idx}/{len(chunks)} 분석 중...")

                    # ✅ 조각 분석 요청 문구 수정
                    part_prompt = (
                        "아래는 문서 일부입니다. 이 조각은 전체 문서의 일부분이며, 누락된 부분은 없습니다.\n"
                        "지금은 조각별 핵심 요약만 해주세요. 과도한 가이드, '1/2 2/2' 같은 표현 금지.\n\n"
                        f"{chunk}"
                    )

                    response = client.responses.create(
                        model=model,
                        input=[{"role": "user", "content": [
                            {"type": "input_text", "text": part_prompt}
                        ]}],
                        max_output_tokens=4000,
                    )
                    part_text = getattr(response, "output_text", None)
                    if not part_text and hasattr(response, "output"):
                        for out in response.output:
                            for c in getattr(out, "content", []):
                                if hasattr(c, "text"):
                                    part_text = c.text
                    summary_results.append(part_text or "")
                    time.sleep(1)  # API 과부하 방지

                # ✅ 최종 통합 지시 수정 (불필요 안내 금지)
                final_prompt = (
                    "지금까지 조각별 요약 결과입니다. 이 내용은 전체 문서를 모두 포함합니다.\n"
                    "이제 아래 내용을 바탕으로 전체 문서를 종합 분석해주세요.\n"
                    "※ '문맥상 1/2, 2/2' 안내 문구 금지\n"
                    "※ 추론, 통찰 중심으로 답변\n\n"
                    + "\n\n".join(summary_results)
                )
                blocks.append({"type": "input_text", "text": final_prompt})
            else:
                blocks.append({"type": "input_text", "text": f"[TXT 파일 내용]\n{txt_text}"})

        if not blocks:
            blocks.append({"type": "input_text", "text": "내용 없음"})

        # 최종 GPT 호출
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": blocks}],
            max_output_tokens=4000,
        )

        # 응답 파싱
        if hasattr(response, "output_text") and response.output_text:
            return response.output_text
        if hasattr(response, "output"):
            for out in response.output:
                for c in getattr(out, "content", []):
                    if hasattr(c, "text"):
                        return c.text

        return "⚠️ GPT로부터 응답이 오지 않았습니다."

    except Exception as e:
        print("OpenAI API 호출 에러:", e, flush=True)
        return f"⚠️ API 호출 중 오류 발생: {e}"
