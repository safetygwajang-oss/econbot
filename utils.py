"""
공통 유틸리티
- 로깅
- 텍스트 정제
- 해시
- 스팸 필터
- 상태 관리 (중복 방지)
"""
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
from config import KST, FORBIDDEN_WORDS, SPAM_PATTERNS, STATE_FILE, MAX_HASH_HISTORY


# ==========================================================
# 로깅
# ==========================================================
def log(tag: str, msg: str):
    """일관된 로그 포맷"""
    ts = datetime.now(KST).strftime("%H:%M:%S")
    print(f"[{ts}] {tag} {msg}")


def info(msg: str):  log("[INFO]", msg)
def ok(msg: str):    log("[ OK ]", msg)
def warn(msg: str):  log("[WARN]", msg)
def fail(msg: str):  log("[FAIL]", msg)


# ==========================================================
# 텍스트 정제
# ==========================================================
def remove_emojis(text: str) -> str:
    """
    4바이트(BMP 밖) 이모지 제거.
    네이버 API가 종종 이모지에서 500 에러를 반환하기 때문.
    """
    if not text:
        return ""
    return "".join(c for c in text if ord(c) <= 0xFFFF)


def mask_forbidden(text: str) -> str:
    """출처 노출 방지 - 금칙어 제거"""
    if not text:
        return text
    for word in FORBIDDEN_WORDS:
        text = text.replace(word, "")
    # 텔레그램 초대 링크 제거
    text = re.sub(r"https?://t\.me/\S+", "", text)
    # 과도한 공백 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate(text: str, limit: int, suffix: str = "...") -> str:
    """길이 초과 시 잘라내기"""
    if len(text) <= limit:
        return text
    return text[:limit - len(suffix)] + suffix


# ==========================================================
# 해시 (중복 판별)
# ==========================================================
def content_hash(text: str) -> str:
    """중복 판별용 해시 (공백 제거 후 앞 200자 기준)"""
    normalized = re.sub(r"\s+", "", text)[:200]
    return hashlib.md5(normalized.encode()).hexdigest()


# ==========================================================
# 🆕 스팸 필터
# ==========================================================
def is_spam(text: str) -> bool:
    """
    SPAM_PATTERNS 에 매칭되는 문자열이 있으면 True
    - 리딩방, 무료체험, VIP방 등 광고성 메시지 자동 제외
    """
    if not text:
        return True  # 빈 메시지도 스팸 취급
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


# ==========================================================
# 🆕 상태 관리 (이미 발행한 메시지 추적)
# ==========================================================
def load_state() -> dict:
    """
    이전에 발행한 메시지 해시 목록 로드
    반환: {"hashes": ["abc123...", "def456..."], "last_run": "2026-08-06T09:00"}
    """
    if not Path(STATE_FILE).exists():
        return {"hashes": [], "last_run": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 구조 검증
        if "hashes" not in data:
            data["hashes"] = []
        return data
    except Exception as e:
        warn(f"상태 파일 읽기 실패, 초기화: {e}")
        return {"hashes": [], "last_run": None}


def save_state(state: dict):
    """상태 저장 (최근 MAX_HASH_HISTORY 개만 유지)"""
    # 오래된 해시는 잘라냄 (파일 무한 증가 방지)
    if len(state.get("hashes", [])) > MAX_HASH_HISTORY:
        state["hashes"] = state["hashes"][-MAX_HASH_HISTORY:]

    state["last_run"] = datetime.now(KST).isoformat()

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        fail(f"상태 저장 실패: {e}")


def is_duplicate(text: str, state: dict) -> bool:
    """
    이미 발행한 메시지인지 확인
    """
    h = content_hash(text)
    return h in state.get("hashes", [])


def mark_posted(text: str, state: dict):
    """
    발행 완료한 메시지 해시를 상태에 추가
    """
    h = content_hash(text)
    if "hashes" not in state:
        state["hashes"] = []
    if h not in state["hashes"]:
        state["hashes"].append(h)
