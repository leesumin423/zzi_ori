"""전자결재 완료함에서 조건(은행명ㆍ키워드 등)에 맞는 품의서를 찾아 링크를 반환한다.

gw/approval.py(마감일 체크리스트용)와 같은 목록 스캔 인프라(scrape_common.py, GWSession)를
재사용하지만, 목적이 다르다: "마감일이 언급된 항목 전부"가 아니라 "검색어를 전부 포함하는
행 중 가장 최근 것"을 찾아 그 상세화면 URL을 얻는 것이 목표다.

목록이 최신순 정렬이라는 기존 전제를 그대로 쓰므로, 매칭된 행을 위에서부터 순서대로
모으면 자연히 "가장 최근 품의서가 먼저" 나온다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from .browser import GWSession
from .scrape_common import go_to_next_page, open_row, row_html, scan_rows

log = logging.getLogger(__name__)

_ATTACHMENT_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|hwp|zip|jpe?g|png)(\?|$)", re.I)


def _looks_like_attachment_link(href: str, text: str) -> bool:
    """review/drafts.py의 동일 휴리스틱과 같은 기준 — 확장자가 보이거나 '다운로드'/
    '첨부' 텍스트가 있으면 첨부파일 링크로 간주한다."""
    href = href or ""
    text = (text or "").strip()
    if _ATTACHMENT_EXT_RE.search(href) or _ATTACHMENT_EXT_RE.search(text):
        return True
    return any(kw in text for kw in ("다운로드", "첨부"))


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return name or "attachment"


def _download_attachments(detail_frame, dest_dir: Path, max_attachment_mb: int) -> List[Path]:
    """상세화면(detail_frame) 안에서 첨부파일로 보이는 링크를 전부 눌러 dest_dir에
    받는다. review/drafts.py의 _download_attachments와 같은 방식(Playwright의
    expect_download으로 실제 다운로드 이벤트를 잡는다)."""
    saved: List[Path] = []
    try:
        owner_page = detail_frame.page
        links = detail_frame.locator("a")
        count = links.count()
    except Exception:
        return saved

    candidates = []
    for i in range(count):
        try:
            el = links.nth(i)
            href = el.get_attribute("href") or ""
            text = el.inner_text(timeout=500) or ""
        except Exception:
            continue
        if _looks_like_attachment_link(href, text):
            candidates.append(i)

    if not candidates:
        return saved

    max_bytes = max_attachment_mb * 1024 * 1024
    for i in candidates:
        try:
            with owner_page.expect_download(timeout=5000) as download_info:
                links.nth(i).click()
            download = download_info.value
            dest_dir.mkdir(parents=True, exist_ok=True)
            filename = _sanitize_filename(download.suggested_filename)
            dest_path = dest_dir / filename
            download.save_as(str(dest_path))
            if dest_path.stat().st_size > max_bytes:
                dest_path.unlink(missing_ok=True)
                continue
            saved.append(dest_path)
        except Exception:
            continue

    return saved


_ROW_ACTION_LABELS = {"열람", "결재", "승인", "반려", "회람", "확인", "완료"}


def _extract_form_type(row_text: str) -> Optional[str]:
    """행 텍스트에서 "양식명"(기안지/법인인감신청서/거래처 지급계좌 등록 신청서 등)을
    뽑아낸다. 이 그룹웨어 완료함 목록은 라벨이 안 붙어있는 표라서(구분/제목/기안부서/
    기안자/파일/양식명/문서번호/일시 순), 파일 칸에 고정으로 찍히는 "첨부"(또는 첨부가
    없으면 "-") 바로 다음 줄이 양식명이라는 위치 규칙으로 찾는다."""
    lines = [ln.strip() for ln in row_text.splitlines()]
    for i, ln in enumerate(lines):
        if ln == "첨부":
            for nxt in lines[i + 1:]:
                if nxt:
                    return nxt
            break
    return None


def _extract_title(row_text: str) -> str:
    """행 텍스트의 첫 줄은 보통 "열람"/"결재" 같은 액션 버튼 라벨이라(실제 제목이
    아님), 그런 라벨과 빈 줄을 건너뛰고 처음 나오는 의미 있는 줄을 제목으로 쓴다."""
    for line in row_text.splitlines():
        line = line.strip()
        if line and line not in _ROW_ACTION_LABELS:
            return line[:120]
    return "(제목 없음)"


def _row_matches(row_text: str, keywords: List[str]) -> bool:
    """행 텍스트가 검색 키워드를 전부(AND) 포함하는지 확인. 대소문자 구분 없음."""
    lowered = row_text.lower()
    return all(kw.lower() in lowered for kw in keywords if kw)


def search_approval_docs(
    session: GWSession,
    folder_urls: Dict[str, str],
    keywords: List[str],
    max_matches: int = 5,
    max_rows_per_page: int = 80,
    max_pages: int = 5,
    download_attachments: bool = False,
    attachments_dir: Optional[Path] = None,
    max_attachment_mb: int = 15,
    debug_dir: Optional[Path] = None,
    form_type_filter: Optional[List[str]] = None,
) -> List[dict]:
    """folder_urls의 각 완료함을 훑어 keywords를 모두 포함하는 행을 찾아 상세 링크를 연다.

    목록이 최신순 정렬이라는 전제이므로, 페이지를 순서대로 훑으며 찾은 매칭 결과는
    자연히 최신순이다 — 굳이 날짜를 따로 추출해 정렬하지 않는다.

    form_type_filter를 주면(예: ["기안지", "법인인감신청서"]) 그 양식명에 해당하는
    행만 매칭 대상으로 삼는다 — 은행명만으로 검색하면 "거래처 지급계좌 등록 신청서"
    같은, 차입 품의서가 아닌 문서까지 걸리는 문제가 있어서 추가했다.

    download_attachments=True면(attachments_dir 필수) 매칭된 품의서 상세화면에서
    첨부파일(근저당권설정계약서ㆍ등기필증 등)까지 같은 번에 다운로드한다 — 담보물건지를
    품의서와 연결할 때, 나중에 또 그룹웨어에 들어가서 찾을 필요 없이 이 프로그램 안에
    첨부파일까지 같이 저장해두기 위함이다.

    반환: [{"folder", "title", "row_text", "url", "form_type", "attachment_paths"}, ...]
    폴더별로 max_matches건까지만 상세를 연다(품의서는 보통 개수가 많지 않고, 매 건마다
    실제로 화면을 열어야 해서 너무 많이 찾으면 느려진다).
    """
    page = session.page
    results: List[dict] = []

    for folder_name, url in folder_urls.items():
        if not url:
            log.info("전자결재[%s]: URL 이 비어있어 건너뜀", folder_name)
            continue

        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        folder_matches = 0
        for page_num in range(1, max_pages + 1):
            if folder_matches >= max_matches:
                break
            list_frame = session.largest_text_frame()
            row_texts = scan_rows(list_frame, max_rows=max_rows_per_page)
            log.info("전자결재[%s] %d페이지: %d개 행 스캔됨", folder_name, page_num, len(row_texts))
            if not row_texts:
                break

            for idx, row_text in enumerate(row_texts):
                if folder_matches >= max_matches:
                    break
                if not _row_matches(row_text, keywords):
                    continue
                form_type = _extract_form_type(row_text)
                if form_type_filter and form_type not in form_type_filter:
                    log.info(
                        "전자결재[%s] 행 %d: 양식명 '%s'이(가) 필터(%s)에 없어 건너뜀",
                        folder_name, idx, form_type, form_type_filter,
                    )
                    continue

                url_before_click = page.url
                clicked = {"ok": False}

                def _click(idx=idx):
                    clicked["ok"] = open_row(list_frame, idx)

                detail_url = None
                attachment_paths: List[Path] = []
                detail_body_snippet = ""
                popup = None
                try:
                    # 기본 900ms는 사내망 그룹웨어에서 onClickPopButton 류가 새 창을
                    # 띄우기 전에 AJAX 왕복이 있으면 부족할 수 있어, 이 스크립트는
                    # 매칭 건수가 적어(최대 몇 건) 넉넉하게 기다려도 된다.
                    popup, frame = session.open_detail(_click, popup_wait_ms=4000)
                    if popup is not None:
                        detail_url = popup.url
                    else:
                        detail_url = page.url
                    try:
                        detail_body_snippet = frame.locator("body").inner_text(timeout=2000)[:800]
                    except Exception:
                        pass
                    if download_attachments and attachments_dir is not None:
                        # 팝업을 닫기 전에(=frame이 아직 살아있을 때) 첨부파일을 받는다.
                        raw_title = row_text.splitlines()[0] if row_text else "doc"
                        dest_dir = attachments_dir / _sanitize_filename(f"{folder_name}_{idx}_{raw_title[:40]}")
                        attachment_paths = _download_attachments(frame, dest_dir, max_attachment_mb)
                except Exception:
                    log.exception("전자결재[%s] 행 %d 상세 열람 실패", folder_name, idx)
                finally:
                    if popup is not None:
                        try:
                            popup.close()
                        except Exception:
                            pass

                # 클릭이 실제로 상세화면을 연 것인지 진단용으로 기록한다 — url이
                # 클릭 전(목록)과 똑같으면 클릭이 엉뚱한 요소를 누르고 있었거나 상세화면이
                # 안 열린 것이다(README의 "목록 인식 방식과 한계" 참고).
                url_unchanged = popup is None and detail_url == url_before_click
                log.info(
                    "전자결재[%s] 행 %d: clicked_ok=%s popup=%s url_unchanged=%s url=%s",
                    folder_name, idx, clicked["ok"], popup is not None, url_unchanged, detail_url,
                )
                if debug_dir is not None:
                    try:
                        debug_dir.mkdir(parents=True, exist_ok=True)
                        raw_title = row_text.splitlines()[0] if row_text else "doc"
                        dump_path = debug_dir / _sanitize_filename(f"{folder_name}_{idx}_{raw_title[:40]}.txt")
                        dump_path.write_text(
                            f"=== row_text ===\n{row_text}\n\n"
                            f"=== row_html ===\n{row_html(list_frame, idx)}\n\n"
                            f"=== clicked_ok: {clicked['ok']} / popup: {popup is not None} / "
                            f"url_unchanged: {url_unchanged} ===\n"
                            f"url_before: {url_before_click}\nurl_after: {detail_url}\n\n"
                            f"=== detail_body_snippet ===\n{detail_body_snippet}\n",
                            encoding="utf-8",
                        )
                    except Exception:
                        log.exception("디버그 덤프 저장 실패")

                title = _extract_title(row_text) if row_text else "(제목 없음)"
                results.append({
                    "folder": folder_name,
                    "title": title,
                    "form_type": form_type,
                    "row_text": row_text[:500],
                    "url": detail_url,
                    "detail_opened": not url_unchanged,
                    "attachment_paths": attachment_paths,
                })
                folder_matches += 1

            if folder_matches >= max_matches:
                break
            if page_num >= max_pages:
                break
            if not go_to_next_page(list_frame, page_num + 1):
                break
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(500)

        log.info("전자결재[%s]: 검색어 매칭 %d건", folder_name, folder_matches)

    return results
