"""
공통 유틸 함수
"""
import re
from datetime import datetime
from config import KST


# ==========================================================
# 로그 출력
# ==========================================================
def _now() -> str:
    return datetime.now(KST).strftime("%H:%M:%S")

def info(msg: str):
    print(f"[{_now()}] ℹ️  {msg}")

def ok(msg: str):
    print(f"[{_now()}] ✅ {msg}")

def warn(msg: str):
    print(f"[{_now()}] ⚠️  {msg}")

def fail(msg: str):
    print(f"[{_now()}] ❌ {msg}")


# ==========================================================
# 이모지 제거 (카페 API가 싫어할 수 있는 문자)
# ==========================================================
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # 이모티콘
    "\U0001F300-\U0001F5FF"  # 심볼&그림
    "\U0001F680-\U0001F6FF"  # 교통&지도
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)

def remove_emojis(text: str) -> str:
    if not text:
        return ""
    return _EMOJI_PATTERN.sub("", text)


# ==========================================================
# 금칙어/문제문자 마스킹
# ==========================================================
def mask_forbidden(text: str) -> str:
    """
    네이버 카페 스팸 필터에 걸릴만한 것들 살짝 처리
    - 텔레그램 링크(t.me/...)는 그대로 두면 카페에서 튕길 수 있음 → 마스킹
    - 노골적 광고 문구도 필요시 추가
    """
    if not text:
        return ""
    # 텔레그램 링크 마스킹
    text = re.sub(r'(https?://)?t\.me/[\w+/-]+', '[텔레그램링크]', text)
    # @유저명 태그도 살짝 (선택)
    # text = re.sub(r'@[\w_]+', '', text)
    return text


# ==========================================================
# 문자열 자르기
# ==========================================================
def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix
