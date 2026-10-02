"""
네이버 카페 게시글 자동 발행
- 텔레그램 채널별 발행 유지
- 한국어 제목, 기사별 소제목, 짧은 문단, 출처 링크로 구성
"""
import html
import re
import time
import urllib.parse
from datetime import datetime
import requests

from config import (
    CAFE_ID, MENU_ID,
    MAX_TOTAL_BODY, MAX_PER_ITEM, MAX_SUBJECT_LEN,
    MAX_ITEM_HEADLINE, MAX_ITEM_PARAGRAPHS,
    HTTP_TIMEOUT, RETRY_COUNT, RETRY_DELAY_SEC,
    get_env,
)
from utils import info, ok, fail, warn, remove_emojis, mask_forbidden, truncate


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
    text = re.sub(r'[\ud800-\udfff]', '', text)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    text = re.sub(r'[\u200B-\u200D\uFE00-\uFE0F\uFFFD]', '', text)
    return text.encode('utf-8', errors='ignore').decode('utf-8')


# ==========================================================
# 3. 요약
# ==========================================================
def _summarize_body(body: str, max_len: int) -> str:
    """원문 문장을 발췌한다. 수치나 의미를 임의로 다시 쓰지 않는다."""
    body = body.strip()
    paragraphs = [p.strip() for p in re.split(r'\n+', body) if p.strip()]
    selected = []
    omitted = False
    for paragraph in paragraphs:
        if len(selected) >= MAX_ITEM_PARAGRAPHS:
            omitted = True
            break
        available = max_len - len("\n\n".join(selected)) - (2 if selected else 0)
        if len(paragraph) <= available:
            selected.append(paragraph)
            continue
        # 길이가 넘으면 완결된 문장까지 발췌한다. 소수점은 분리하지 않는다.
        sentences = re.split(r'(?<=[.!?。])\s+', paragraph)
        excerpt = []
        for sentence in sentences:
            if len(" ".join(excerpt + [sentence])) > available - 1:
                break
            excerpt.append(sentence)
        if excerpt:
            selected.append(" ".join(excerpt))
        elif not selected:
            selected.append(truncate(paragraph, max_len, suffix="…"))
        omitted = True
        break
    summary = "\n\n".join(selected)
    if omitted and summary and not summary.endswith("…"):
        summary = truncate(summary, max_len - 1, suffix="") + "…"
    return summary


def _clean_news_text(text: str) -> str:
    """이모지, 마크다운 강조, 줄 앞 장식과 반복 구분선을 정리한다."""
    text = _sanitize(remove_emojis(mask_forbidden(text)))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r'\*\*(.+?)\*\*|__(.+?)__',
                  lambda match: match.group(1) or match.group(2), text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if re.fullmatch(r'[\s=\-_*─━]+', line):
            continue
        line = re.sub(r'^\s*(?:#{1,6}\s+|>\s*)', '', line)
        line = re.sub(r'^[•●○■□◆◇▶▷※★☆]+\s*', '', line)
        # '-1.2%'처럼 수치의 부호로 쓰인 기호는 남긴다.
        line = re.sub(r'^(?:[-*+]\s+)+', '', line)
        line = re.sub(r'[ \t]+', ' ', line).strip()
        lines.append(line)
    return "\n".join(lines).strip()


def _prepare_news_item(item: dict) -> tuple[str, str, list[str]]:
    text = _clean_news_text(item.get("body", ""))
    links = []
    for match in re.finditer(r'https?://[^\s<>]+', text):
        url = match.group().rstrip('.,;!?)]}。')
        try:
            valid_url = bool(urllib.parse.urlsplit(url).netloc)
        except ValueError:
            valid_url = False
        if valid_url and url not in links:
            links.append(url)
    # 링크는 본문 문장과 분리하여 하단에 표시한다.
    text = re.sub(r'\[([^\]]+)\]\(https?://[^\s)]+\)', r'\1', text)
    text = re.sub(r'https?://[^\s<>]+', '', text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line for line in lines
             if not re.fullmatch(r'(?:원문|링크|관련\s*링크|자세히)\s*[:：]?', line)]
    if not lines:
        return "", "", links
    first_line = lines[0]
    headline = truncate(first_line, MAX_ITEM_HEADLINE, suffix="…")
    # 짧은 첫 줄은 소제목으로 쓰고 중복해서 본문에 표시하지 않는다.
    body_lines = lines[1:] if len(first_line) <= MAX_ITEM_HEADLINE else lines
    summary = _summarize_body("\n".join(body_lines), MAX_PER_ITEM)
    return headline, summary, links


# ==========================================================
# 4. 제목 / 본문 빌더
# ==========================================================
def _format_date_with_weekday(date_str: str) -> str:
    """'2026-08-06' → '2026.08.06(목)'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday_map = ["월", "화", "수", "목", "금", "토", "일"]
        wd = weekday_map[dt.weekday()]
        return f"{dt.year}.{dt.month:02d}.{dt.day:02d}({wd})"
    except Exception:
        return date_str


def _build_subject(date_str: str, index: int, total: int, chat_name: str) -> str:
    """날짜, 브리핑 이름, 자료 출처만 담은 한국어 제목."""
    date_formatted = _format_date_with_weekday(date_str)
    safe_chat_name = re.sub(r'[^\w가-힣\s/]', '', _clean_news_text(chat_name)).strip()
    subject = f"{date_formatted} 경제 뉴스 브리핑 | {safe_chat_name}"
    return subject[:MAX_SUBJECT_LEN]


def _build_channel_content(digest: dict, date_str: str) -> str:
    """제목·발췌 문단·자료 링크를 담은 HTML. 외부 텍스트는 모두 이스케이프한다."""
    date_formatted = html.escape(_format_date_with_weekday(date_str))
    source = html.escape(_clean_news_text(digest['chat_name']))
    blocks = [
        "<p><strong>경제 뉴스 브리핑</strong></p>",
        f"<p>{date_formatted}<br>자료: {source}</p>",
        "<hr>",
    ]
    footer = (
        "<hr><p>출처 자료의 주요 내용을 발췌·정리했습니다. "
        "상세 내용은 해당 채널과 자료 링크를 참고해 주세요.</p>"
        "<p>참고용 정보이며, 투자 판단은 본인 책임입니다.</p>"
    )
    current_size = sum(map(len, blocks)) + len(footer)
    shown = 0
    for item_index, item in enumerate(digest["items"]):
        headline, summary, links = _prepare_news_item(item)
        if not headline:
            continue
        item_parts = [f"<p><strong>{shown + 1}. {html.escape(headline)}</strong></p>"]
        item_parts.extend(f"<p>{html.escape(p)}</p>" for p in summary.split("\n\n") if p)
        if links:
            anchors = [f'<a href="{html.escape(url, quote=True)}">링크 {n}</a>'
                       for n, url in enumerate(links, 1)]
            item_parts.append(f"<p>자료 링크: {' · '.join(anchors)}</p>")
        block = "".join(item_parts)
        if current_size + len(block) > MAX_TOTAL_BODY - 200:
            remaining = len(digest["items"]) - item_index
            blocks.append(f"<p>본문 길이 제한으로 나머지 {remaining}건은 생략했습니다.</p>")
            break
        blocks.append(block)
        current_size += len(block)
        shown += 1
    blocks.append(footer)
    return "".join(blocks)


# ==========================================================
# 5. HTTP 요청
# ==========================================================
def _post_once(subject: str, content: str, token: str) -> tuple[bool, int, str]:
    url = f"https://openapi.naver.com/v1/cafe/{CAFE_ID}/menu/{MENU_ID}/articles"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/x-www-form-urlencoded; charset=utf-8",
    }
    body = "&".join([
        f"subject={urllib.parse.quote(subject, safe='')}",
        f"content={urllib.parse.quote(content, safe='')}",
    ])
    try:
        res = requests.post(
            url, headers=headers,
            data=body.encode("utf-8"),
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:
        return False, 0, f"네트워크: {e}"

    info(f"    [DEBUG] HTTP {res.status_code} | {res.text[:200]}")

    try:
        result = res.json()
    except Exception:
        return False, res.status_code, f"파싱실패: {res.text[:200]}"

    status = result.get("message", {}).get("status")
    if status != "200":
        return False, res.status_code, f"status={status}"

    return True, res.status_code, result["message"]["result"]["articleUrl"]


# ==========================================================
# 6. 분할 발행 (채널별)
# ==========================================================
def post_all_unified(digest_list: list, token: str) -> str | None:
    """
    채널별로 나눠서 각각 발행
    - 하나라도 성공하면 마지막 성공 URL 반환
    - 각 발행 사이 15초 대기 (도배 방지)
    """
    if not digest_list:
        warn("발행할 내용 없음")
        return None

    date_str = digest_list[0]["date"]
    total = len(digest_list)

    info("=" * 60)
    info(f"분할 발행 시작: 총 {total}개 채널")
    info("=" * 60)

    success_urls = []
    failed_channels = []

    for idx, digest in enumerate(digest_list, 1):
        chat_name = digest["chat_name"]
        subject = _sanitize(remove_emojis(
            _build_subject(date_str, idx, total, chat_name)
        ))
        content = _sanitize(remove_emojis(
            _build_channel_content(digest, date_str)
        ))

        info("")
        info(f"[{idx}/{total}] {chat_name}")
        info(f"  제목: {subject}")
        info(f"  본문: {len(content)}자")

        # 각 채널당 3회 재시도
        delays = [0, 15, 45]
        posted = False

        for attempt, delay in enumerate(delays, 1):
            if delay > 0:
                info(f"  {delay}초 대기...")
                time.sleep(delay)

            info(f"  [시도 {attempt}/{len(delays)}]")
            success, code, result = _post_once(subject, content, token)

            if success:
                ok(f"  성공: {result}")
                success_urls.append(result)
                posted = True
                break
            else:
                warn(f"  실패 [HTTP {code}]: {result[:150]}")

        if not posted:
            fail(f"  {chat_name} 3회 모두 실패")
            failed_channels.append(chat_name)

        # 다음 채널로 넘어가기 전 도배 방지 대기
        if idx < total:
            info(f"  다음 채널까지 15초 대기 (도배 방지)")
            time.sleep(15)

    # 최종 결과 요약
    info("")
    info("=" * 60)
    info("최종 결과")
    info(f"  성공: {len(success_urls)}/{total}")
    info(f"  실패: {len(failed_channels)}/{total}")
    if failed_channels:
        warn(f"  실패 채널: {', '.join(failed_channels)}")
    info("=" * 60)

    if success_urls:
        for url in success_urls:
            ok(f"  {url}")
        return success_urls[-1]

    return None
