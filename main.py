"""
🧪 진단용 - 최소 본문 테스트
정상 작동 확인 후 원래 코드로 복구할 것!
"""
import sys
from cafe_poster import get_access_token, post_all_unified
from utils import info, ok, fail, warn


def main():
    try:
        info("🧪 진단 테스트 시작: 최소 본문으로 발행 시도")
        info("-" * 60)

        # 🧪 가짜 digest_list - 최소 데이터
        digest_list = [
            {
                "chat_name": "테스트채널",
                "messages": [
                    {
                        "date": "2026-08-06 10:00",
                        "text": "안녕하세요 테스트입니다"
                    }
                ]
            }
        ]

        info(f"테스트 digest: {digest_list}")
        info("-" * 60)
        info("네이버 카페 발행 시작")
        
        token = get_access_token()
        article_url = post_all_unified(digest_list, token)

        if article_url:
            ok(f"🎉 테스트 성공! {article_url}")
            return 0
        else:
            fail("테스트 실패")
            return 1

    except Exception as e:
        fail(f"예외 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
