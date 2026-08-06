"""
네이버 카페 게시글 자동 발행
- 형님 요구: 제목은 영문+숫자만
- 본문은 원본 최대한 살리되 안 잘리는 선에서 요약
"""
import re
import time
import urllib.parse
import requests

from config import (
    CAFE_ID, MENU_ID,
    MAX_TOTAL_BODY, MAX_PER_ITEM, MAX_SUBJECT_LEN,
    HTTP_TIMEOUT, RETRY_COUNT, RETRY_DELAY_SEC,
    get_env,
)
from utils import info, ok, fail, warn, remove_emojis, mask_forbidden


# ==========================================================
# 1. Access Token 발급
# ==========================================================
def get_access_token() -> str:
    res = requests.get(
        "https://nid.naver.com/oauth2.0/token",
        params={
            "grant_type":    "refresh_token",
            "client_id":     get_env("NAVER_CLIENT_ID"),
            "client_secret": get_env("NAVER_CLIENT_SECRET"),
            "refresh_token": get_env("NAVER_REFRESH_TOKEN"),
        },
        timeout=HTTP_TIMEOUT,
    )
    data = res.json()
    if "access_token" not in data:
        raise RuntimeError(f"토큰 재발급 실패: {data}")
    ok("Access Token 발급 완료")
    return data["access_token"]


# ==========================================================
# 2. 문자 정제
# ==========================================================
def _sanitize(text: str) -> str:
    """네이버 카페 API가 싫어할만한 문자 제거"""
    if not text:
        return ""
    text = re.sub(r'[\ud800-\udfff]', '', text)                         # 서로게이트
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)        # 제어문자
    text = re.sub(r'[\u200B-\u200D\uFE00-\uFE0F\uFFFD]', '', text)      # 제로폭
    return text.encode('utf-8', errors='ignore').decode('utf-8')


# ==========================================================
# 3. 요약 (원본 최대한 살림)
# ==========================================================
def _summarize_body(body: str, max_len: int) -> str:
    """
    - max_len 이하면 원본 그대로
    - 넘으면 문장 단위로 앞에서부터 채워넣고 뒤는 잘림 표시
    """
    body = body.strip()
    if len(body) <= max_len:
        return body

    # 문장 단위 분할
    sentences = re.split(r'(?<=[.!?。])\s+|\n+', body)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        cut = body[:max_len]
        last_space = cut.rfind(' ')
        if last_space > max_len * 0.8:
            cut = cut[:last_space]
        return cut + "..."

    result = []
    total = 0
    for sent in sentences:
        if total + len(sent) + 1 > max_len - 5:
            break
        result.append(sent)
        total += len(sent) + 1

    if not result:
        return sentences[0][:max_len - 3] + "..."

    summary = " ".join(result)
    if len(result) < len(sentences):
        summary += " ..."
    return summary


# ==========================================================
# 4. 제목 / 본문 빌더
# ==========================================================
def _build_subject(date_str: str) -> str:
    """
    형님 요구: 영문+숫자만
    예: '2026. 08. 06 World Economy News'
    """
    try:
        y, m, d = date_str.split("-")
        formatted_date = f"{y}. {m}. {d}"
    except Exception:
        formatted_date = date_str
    subject = f"{formatted_date} World Economy News"
    return subject[:MAX_SUBJECT_LEN]


def _build_unified_content(digest_list: list) -> str:
    """
    모든 채널 → 하나의 본문
    깔끔한 텍스트 스타일 (특수문자 최소화)
    """
    lines = []
    total_count = sum(d["count"] for d in digest_list)

    # 헤더
    lines.append(f"Date: {digest_list[0]['date']}")
    lines.append(f"Channels: {len(digest_list)} / Messages: {total_count}")
    lines.append("")
    lines.append("-" * 30)
    lines.append("")

    current_size = sum(len(l) + 1 for l in lines)

    for digest in digest_list:
        # 채널 헤더
        lines.append("")
        lines.append(f"[{digest['chat_name']}]")
        lines.append("")

        for i, item in enumerate(digest["items"], 1):
            time_str = item.get("date_kst", "")[11:16]
            raw_body = mask_forbidden(item.get("body", ""))

            summarized = _summarize_body(raw_body, MAX_PER_ITEM)

            block_lines = [
                f"{i}. {time_str}",
                summarized,
                "",
            ]
            block_size = sum(len(l) + 1 for l in block_lines)

            # 전체 크기 초과 방지
            if current_size + block_size > MAX_TOTAL_BODY - 500:
                lines.append("")
                lines.append("... (length limit)")
                current_size = MAX_TOTAL_BODY
                break

            lines.extend(block_lines)
            current_size += block_size

        if current_size >= MAX_TOTAL_BODY:
            break

    lines.append("")
    lines.append("-" * 30)
    lines.append("※ 참고용 정보입니다. 투자 판단은 본인 책임입니다.")

    return "\n".join(lines)


# ==========================================================
# 5. HTTP 요청
# ==========================================================
def _post_once(subject: str, content: str, token: str) -> tuple[bool, int, str]:
    url = f"https://openapi.naver.com/v1/cafe/{CAFE_ID}/menu/{MENU_ID}/articles"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/x-www-form-urlencoded; charset=utf-8",
    }
    # 개행 → <br> 로 변환 (카페에서 예쁘게 표시)
    content_html = content.replace("\n", "<br>")

    # 🔧 openyn=true 제거 (게시판이 전체공개 미허용 시 403 유발)
    body = "&".join([
        f"subject={urllib.parse.quote(subject, safe='')}",
        f"content={urllib.parse.quote(content_html, safe='')}",
    ])
    try:
        res = requests.post(
            url, headers=headers,
            data=body.encode("utf-8"),
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:
        return False, 0, f"네트워크: {e}"

    # 🔍 디버깅 강화: 응답 전문 로그
    info(f"  [DEBUG] HTTP Status: {res.status_code}")
    info(f"  [DEBUG] Response Body: {res.text[:500]}")

    try:
        result = res.json()
    except Exception:
        return False, res.status_code, f"파싱실패: {res.text[:200]}"

    status = result.get("message", {}).get("status")
    if status != "200":
        return False, res.status_code, f"status={status}, body={res.text[:250]}"

    return True, res.status_code, result["message"]["result"]["articleUrl"]


# ==========================================================
# 6. 통합 발행 (Rate Limit 회피)
# ==========================================================
def post_all_unified(digest_list: list, token: str) -> str | None:
    if not digest_list:
        warn("발행할 내용 없음")
        return None

    date_str = digest_list[0]["date"]
    subject = _sanitize(remove_emojis(_build_subject(date_str)))
    content = _sanitize(remove_emojis(_build_unified_content(digest_list)))

    info("=" * 60)
    info(f"📢 통합 발행 시작")
    info(f"  제목: {subject}")
    info(f"  본문: {len(content)}자")
    info(f"  채널: {len(digest_list)}개")
    info("=" * 60)

    delays = [0, 30, 90]  # 즉시 → 30초 → 90초
    for attempt, delay in enumerate(delays, 1):
        if delay > 0:
            info(f"  ⏳ {delay}초 대기 후 재시도...")
            time.sleep(delay)

        info(f"\n  [시도 {attempt}/{len(delays)}]")
        success, code, result = _post_once(subject, content, token)

        if success:
            ok(f"  ✅ 성공: {result}")
            return result

        warn(f"  실패 [HTTP {code}]: {result[:200]}")

    fail("\n  ❌ 3회 모두 실패")
    fail("  가능한 원인:")
    fail(f"  1. 일일 API 발행 한도 초과")
    fail(f"  2. 카페 도배 방지")
    fail(f"  3. Refresh Token 만료")
    fail(f"  4. CAFE_ID({CAFE_ID}) or MENU_ID({MENU_ID}) 오류")
    return None
