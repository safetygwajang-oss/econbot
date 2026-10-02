"""개인 PC에서 한 번 로그인하여 GitHub Actions용 세션 파일을 만든다."""
import argparse
import getpass
import os
from pathlib import Path
import sys

from telethon.sync import TelegramClient
from telethon.sessions import StringSession


def main() -> int:
    parser = argparse.ArgumentParser(description="개인 PC에서 텔레그램 로그인 세션 발급")
    parser.add_argument("--output", default="telegram-session.txt", help="세션 저장 파일")
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" or not sys.stdin.isatty():
        print("이 도구는 GitHub Actions가 아닌 개인 PC의 터미널에서 실행하세요.")
        return 1
    output = Path(args.output)
    if output.exists():
        print("저장 파일이 이미 존재합니다. 기존 파일을 옮기거나 --output으로 다른 파일을 지정하세요.")
        return 1
    print("텔레그램 API ID와 API HASH는 기존 GitHub Secrets에 등록한 값과 동일하게 입력하세요.")
    try:
        api_id = int((os.environ.get("TELEGRAM_API_ID") or input("API ID: ")).strip())
        api_hash = (os.environ.get("TELEGRAM_API_HASH") or getpass.getpass("API HASH: ")).strip()
        if api_id <= 0 or not api_hash:
            print("API ID는 양수여야 하며 API HASH는 비어 있을 수 없습니다.")
            return 1
        client = TelegramClient(StringSession(), api_id, api_hash)
        try:
            client.start(
                phone=lambda: input("전화번호 (국가번호 포함, 예: +821012345678): ").strip(),
                code_callback=lambda: getpass.getpass("텔레그램으로 받은 로그인 코드: ").strip(),
                password=lambda: getpass.getpass("2단계 인증 비밀번호: "),
            )
            if client.is_bot():
                print("채널 자료 수집용 세션은 봇 토큰 대신 개인 계정으로 로그인해야 합니다.")
                return 1
            session = client.session.save()
            if not session:
                print("세션을 발급하지 못했습니다. 로그인을 다시 확인하세요.")
                return 1
            # 세션을 터미널에 출력하지 않고 새 파일에만 저장한다.
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(session)
        finally:
            client.disconnect()
    except (KeyboardInterrupt, EOFError):
        print("\n세션 발급을 취소했습니다.")
        return 1
    except Exception as exc:
        print(f"세션 발급 실패 ({type(exc).__name__}). 입력값과 네트워크를 확인하세요.")
        return 1
    print(f"세션 파일 저장 완료: {output}")
    print("파일 내용 전체를 GitHub Actions의 TELEGRAM_SESSION Secret에 붙여넣으세요.")
    print("이 파일은 계정 로그인 정보입니다. 저장소나 채팅에 올리지 마세요.")
    print("수집할 두 채널에 이 계정이 참여되어 있는지도 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
