# econbot

텔레그램의 경제·시황 자료를 수집하여 네이버 카페에 경제 뉴스 브리핑으로 게시합니다.

## 이번 수정

- 기존 텔레그램 수집 채널과 매일 오전 8시 10분 자동 실행을 유지했습니다.
- 영문 제목을 `2026.08.06(목) 경제 뉴스 브리핑 | 채널명` 형태로 바꿨습니다.
- 이모지, 줄 앞 장식, 반복 구분선, 마크다운 강조 기호를 정리합니다.
- 기사별 소제목을 굵게 표시하고 본문을 짧은 문단으로 나눕니다.
- 메시지에 포함된 웹 링크는 본문 하단의 클릭 가능한 자료 링크로 분리합니다.
- 숫자, 소수점, %, +/-, 통화 기호, 등락 화살표는 유지합니다.

AI로 내용을 새로 작성하는 방식이 아니라, 원문의 첫 줄을 소제목으로 쓰고 뒤쪽 문장을 발췌합니다. 원문에 없는 사실·해석은 추가하지 않습니다. 첫 줄이 긴 경우에는 소제목을 줄이고 본문에 원문을 남깁니다. 문단 수나 길이를 초과해 생략된 내용은 말줄임표로 표시합니다.

## 실행

Python 3.11 이상에서 실행합니다.

```bash
pip install -r requirements.txt
python main.py
```

기존 환경변수 여섯 개를 그대로 사용합니다. GitHub Actions에서는 저장소의 Secrets에 등록하세요.

| 환경변수 | 용도 |
| --- | --- |
| `TELEGRAM_API_ID` | 텔레그램 API ID |
| `TELEGRAM_API_HASH` | 텔레그램 API 해시 |
| `TELEGRAM_SESSION` | 기존 텔레그램 문자열 세션 |
| `NAVER_CLIENT_ID` | 네이버 앱 ID |
| `NAVER_CLIENT_SECRET` | 네이버 앱 시크릿 |
| `NAVER_REFRESH_TOKEN` | 네이버 토큰 갱신 |

카페와 게시판은 기존 `config.py`의 `CAFE_ID`, `MENU_ID`를 사용합니다. 지정된 두 텔레그램 채널에서 전날 오전 8시부터 오늘 오전 8시까지(KST)의 자료를 수집하여 채널별로 게시합니다.

## 전화번호 입력 / EOFError 해결

`Please enter your phone (or bot token)` 뒤에 `EOFError`가 나오면 저장된 `TELEGRAM_SESSION`으로 로그인이 복원되지 않은 상태입니다. GitHub Actions에서는 전화번호와 로그인 코드를 입력할 수 없습니다. 빈 값, 잘못 복사한 값, 인증이 해제된 세션인지 확인하고 다음 순서로 다시 발급하세요.

1. 수정 파일을 개인 PC에 풀고 터미널에서 해당 폴더로 이동합니다.
2. 아래 명령을 실행합니다. **GitHub Actions에서 세션 발급 도구를 실행하지 마세요.**

   ```bash
   pip install -r requirements.txt
   python generate_telegram_session.py
   ```

3. 기존 Secrets에 등록한 것과 동일한 API ID와 API HASH를 입력합니다. API 정보는 [텔레그램 개발자 페이지](https://my.telegram.org/apps)에서 확인할 수 있습니다.
4. 수집할 채널에 참여한 개인 계정의 전화번호를 국가번호 포함 형식(예: `+821012345678`)으로 입력합니다. 로그인 코드와 필요한 경우 2단계 인증 비밀번호를 입력합니다.
5. 생성된 `telegram-session.txt`를 열고 내용 전체를 복사합니다. GitHub 저장소의 `Settings → Secrets and variables → Actions`에서 `TELEGRAM_SESSION`을 수정하여 붙여넣고 저장합니다. 따옴표나 변수명은 붙이지 않습니다.
6. `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`가 발급에 사용한 값과 같은지 확인하고 Actions의 `Daily Auto Post`를 다시 실행합니다.

세션 파일은 계정 로그인 정보이므로 저장소나 채팅에 올리지 마세요. 기본 파일명은 `.gitignore`에 포함되어 있습니다. 다른 파일명을 `--output`으로 지정한다면 해당 파일도 커밋하지 마세요. 이미 저장 파일이 존재하면 덮어쓰지 않으므로, 기존 파일을 옮기거나 다른 출력 파일을 지정하세요.

이번 수정에서는 자동 수집에 `with TelegramClient(...)` / `start()`를 사용하지 않고 `connect()` 후 인증 상태를 검사합니다. 인증에 실패하면 입력을 요청하지 않고 세션 재발급 방법을 안내한 뒤 실패 코드로 종료합니다. 채널 ID를 조회하기 전에 대화 목록을 읽어 채널 정보도 준비합니다. 모든 대상 채널에 접근하지 못한 경우에는 계정의 채널 참여 여부를 확인하도록 오류를 표시합니다.

공식 참고: [Telethon 문자열 세션](https://docs.telethon.dev/en/stable/concepts/sessions.html#string-sessions)

## 글 길이 조정

`config.py`에서 다음 값을 바꿀 수 있습니다.

| 설정 | 기본값 | 용도 |
| --- | --- | --- |
| `MAX_ITEM_HEADLINE` | 80 | 기사 소제목 최대 글자 수 |
| `MAX_PER_ITEM` | 900 | 기사 본문 발췌 최대 글자 수 |
| `MAX_ITEM_PARAGRAPHS` | 3 | 기사 본문 최대 문단 수 |
| `MAX_TOTAL_BODY` | 30000 | HTML을 포함한 게시글 최대 길이 |

원문 줄바꿈을 문단 경계로 사용합니다. 한 문단이 길면 완결된 문장까지 발췌하며, 한 문장 자체가 제한보다 길면 잘라서 말줄임표를 붙입니다. 전체 게시글 길이를 넘는 항목은 생략 건수를 표시합니다.

## 확인

```bash
python -m unittest discover -s tests -v
```

`examples/cafe-preview.html`을 브라우저로 열면 가상 자료로 만든 게시글 모양을 확인할 수 있습니다. 실제 뉴스나 실제 발행 결과가 아닙니다. 테스트는 외부 발행 요청을 모의 처리하므로 카페에 글을 올리지 않습니다.
