"""
전체 실행 파이프라인
1. 텔레그램 수집
2. 데이터 저장 (JSON)
3. 채널별 그룹핑
4. 네이버 카페 발행
"""
import sys
from telegram_collector import fetch_messages, save_results, build_digest_list
from cafe_poster import get_access_token, post_all_unified
from utils import info, ok, fail, warn


def main():
    try:
        # 1. 텔레그램 수집
        info("🚀 시작: 텔레그램 → 네이버 카페 자동 발행")
        info("-" * 60)

        messages = fetch_messages()
        if not messages:
            warn("수집된 메시지 없음. 종료")
            return 0

        # 2. JSON 저장
        save_results(messages)

        # 3. 채널별 digest 구성
        digest_list = build_digest_list(messages)
        info(f"채널별 그룹핑 완료: {len(digest_list)}개 채널")

        # 4. 네이버 카페 발행
        info("-" * 60)
        info("네이버 카페 발행 시작")
        token = get_access_token()
        article_url = post_all_unified(digest_list, token)

        if article_url:
            ok(f"🎉 최종 완료! {article_url}")
            return 0
        else:
            fail("발행 실패")
            return 1

    except Exception as e:
        fail(f"예외 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
