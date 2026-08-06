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

from config import (
    KST, DATA_DIR, TARGET_CHATS,
    COLLECT_START_HOUR, COLLECT_LIMIT_PER_CHAT,
    get_env,
)
from utils import info, ok, warn


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
    session  = get_env("TELEGRAM_SESSION")

    start_kst, end_kst = _get_time_range()
    start_utc = start_kst.astimezone(timezone.utc)
    end_utc   = end_kst.astimezone(timezone.utc)

    info(f"수집 구간: {start_kst:%m-%d %H:%M} ~ {end_kst:%m-%d %H:%M} (KST)")

    if not TARGET_CHATS:
        warn("TARGET_CHATS 가 비어있음! config.py 에서 채널 추가 필요")
        return []

    results = []
    with TelegramClient(StringSession(session), api_id, api_hash) as client:
        for chat_id in TARGET_CHATS:
            try:
                entity = client.get_entity(chat_id)
                chat_name = getattr(entity, "title", str(chat_id))
            except Exception as e:
                warn(f"{chat_id} 접근 실패: {e}")
                continue

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

            info(f"  📥 {chat_name}: {count}건")

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
        print(f"\n📌 [{m['date_kst'][:16]}] {m['chat_name']}")
        print(f"   {m['text'][:100]}")
