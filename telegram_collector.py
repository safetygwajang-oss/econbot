"""
텔레그램 수집기
- TARGET_CHATS 에 지정된 채널에서
- 어제 08:00 ~ 오늘 08:00 (KST) 사이 메시지 수집
- data/YYYY-MM-DD.json 저장
"""
import json
from datetime import datetime, timezone, timedelta
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Message
from telethon.errors import AuthKeyError, UnauthorizedError

from config import (
    KST, DATA_DIR, TARGET_CHATS,
    COLLECT_START_HOUR, COLLECT_LIMIT_PER_CHAT,
    get_env,
)
from utils import info, ok, warn


class TelegramSessionError(RuntimeError):
    """자동 실행에서는 로그인 입력을 받지 않고 세션 복구를 안내한다."""


SESSION_HELP = (
    "개인 PC에서 python generate_telegram_session.py 를 실행하여 로그인한 뒤, "
    "생성된 telegram-session.txt의 내용을 GitHub 저장소 Settings → Secrets and "
    "variables → Actions → TELEGRAM_SESSION에 등록하세요. "
    "이 세션을 발급할 때 사용한 TELEGRAM_API_ID와 TELEGRAM_API_HASH도 함께 확인하세요."
)


def _load_session() -> StringSession:
    """공백·복사한 따옴표를 정리하고, 비어 있거나 잘못된 세션을 거부한다."""
    try:
        raw_session = get_env("TELEGRAM_SESSION").strip()
    except RuntimeError:
        raise TelegramSessionError("TELEGRAM_SESSION이 설정되지 않았습니다. " + SESSION_HELP) from None
    if len(raw_session) >= 2 and raw_session[0] == raw_session[-1] and raw_session[0] in "\"'":
        raw_session = raw_session[1:-1].strip()
    if not raw_session:
        raise TelegramSessionError("TELEGRAM_SESSION이 비어 있습니다. " + SESSION_HELP)
    try:
        session = StringSession(raw_session)
    except Exception:
        # 잘못된 세션 문자열을 예외나 로그에 출력하지 않는다.
        raise TelegramSessionError("TELEGRAM_SESSION 문자열 형식이 올바르지 않습니다. " + SESSION_HELP) from None
    if not session.auth_key:
        raise TelegramSessionError("TELEGRAM_SESSION에 인증 정보가 없습니다. " + SESSION_HELP)
    return session


def _get_time_range():
    """어제 08:00 ~ 오늘 08:00 (KST)"""
    now = datetime.now(KST)
    today_start = now.replace(
        hour=COLLECT_START_HOUR, minute=0, second=0, microsecond=0
    )
    yesterday_start = today_start - timedelta(days=1)
    return yesterday_start, today_start


def fetch_messages():
    api_id   = int(get_env("TELEGRAM_API_ID"))
    api_hash = get_env("TELEGRAM_API_HASH")
    session = _load_session()

    start_kst, end_kst = _get_time_range()
    start_utc = start_kst.astimezone(timezone.utc)
    end_utc   = end_kst.astimezone(timezone.utc)

    info(f"수집 구간: {start_kst:%m-%d %H:%M} ~ {end_kst:%m-%d %H:%M} (KST)")

    if not TARGET_CHATS:
        warn("TARGET_CHATS 가 비어있음! config.py 에서 채널 추가 필요")
        return []

    results = []
    # with/start는 인증 실패 시 input()을 호출하므로 자동 실행에서는 사용하지 않는다.
    client = TelegramClient(session, api_id, api_hash)
    try:
        client.connect()
        if not client.is_user_authorized():
            raise TelegramSessionError("TELEGRAM_SESSION으로 로그인할 수 없습니다. " + SESSION_HELP)
        if client.is_bot():
            raise TelegramSessionError("뉴스 수집에는 봇 토큰이 아닌 개인 계정 세션이 필요합니다. " + SESSION_HELP)
        # StringSession에는 채널의 access_hash가 저장되지 않으므로 ID 조회 전에 준비한다.
        client.get_dialogs()
        accessible_channels = 0
        for chat_id in TARGET_CHATS:
            try:
                entity = client.get_entity(chat_id)
                chat_name = getattr(entity, "title", str(chat_id))
            except (AuthKeyError, UnauthorizedError):
                raise
            except Exception as e:
                warn(f"{chat_id} 접근 실패: {e}")
                continue

            accessible_channels += 1
            count = 0
            for msg in client.iter_messages(
                entity, offset_date=end_utc, limit=COLLECT_LIMIT_PER_CHAT
            ):
                if not isinstance(msg, Message):
                    continue
                if msg.date < start_utc:
                    break
                text = (msg.message or "").strip()
                if not text:
                    continue

                results.append({
                    "chat_id":   str(chat_id),
                    "chat_name": chat_name,
                    "msg_id":    f"{chat_id}_{msg.id}",
                    "date_kst":  msg.date.astimezone(KST).isoformat(),
                    "text":      text,
                })
                count += 1

            info(f"  {chat_name}: {count}건")

        if not accessible_channels:
            raise RuntimeError(
                "지정된 채널에 접근할 수 없습니다. 세션을 만든 계정의 채널 참여 여부와 "
                "config.py의 TARGET_CHATS를 확인하세요."
            )
    except (AuthKeyError, UnauthorizedError):
        raise TelegramSessionError("텔레그램 세션 인증이 해제되었거나 인증 키를 사용할 수 없습니다. " + SESSION_HELP) from None
    finally:
        client.disconnect()

    results.sort(key=lambda x: x["date_kst"])
    ok(f"총 수집: {len(results)}건")
    return results


def save_results(messages):
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"{today_str}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    ok(f"저장 완료: {output_file}")
    return output_file


def build_digest_list(messages: list) -> list:
    """
    수집한 메시지들을 채널별로 그룹핑
    cafe_poster 에서 쓸 수 있는 형태로 변환
    """
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    # 채널별 그룹핑
    grouped = {}
    for m in messages:
        chat_name = m["chat_name"]
        if chat_name not in grouped:
            grouped[chat_name] = []
        grouped[chat_name].append({
            "date_kst": m["date_kst"],
            "body":     m["text"],
        })

    digest_list = []
    for chat_name, items in grouped.items():
        digest_list.append({
            "date":      today_str,
            "chat_name": chat_name,
            "count":     len(items),
            "items":     items,
        })

    return digest_list


if __name__ == "__main__":
    msgs = fetch_messages()
    save_results(msgs)

    print("\n" + "=" * 60)
    print("샘플 3건")
    print("=" * 60)
    for m in msgs[:3]:
        print(f"\n[{m['date_kst'][:16]}] {m['chat_name']}")
        print(f"   {m['text'][:100]}")
