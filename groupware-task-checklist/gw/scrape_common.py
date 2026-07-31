"""사이트 구조를 모르는 상태에서도 최대한 동작하도록 만든 범용(휴리스틱) 목록 스크래퍼.

- 페이지(또는 iframe) 안에서 '목록처럼 반복되는 요소'를 자동으로 찾는다.
  (row가 2개 이상 <td>를 가진 <table><tr> 이거나, 같은 태그+class를 3개 이상 공유하는 요소들)
- 찾은 행들을 window.__gwRows 에 저장해두고, 인덱스로 다시 클릭해서 상세 화면을 열 수 있게 한다.

사이트 구조를 알게 되면 이 파일 대신 정확한 CSS 선택자를 쓰는 방식으로 바꾸는 게 더 안정적이다.
(README 참고)
"""

from __future__ import annotations

from typing import List

from playwright.sync_api import Frame

_SCAN_JS = """
() => {
  function pickRows() {
    const tables = Array.from(document.querySelectorAll('table'));
    let best = [];
    for (const t of tables) {
      const rows = Array.from(t.querySelectorAll('tr')).filter(r => r.querySelectorAll('td').length >= 2);
      if (rows.length > best.length) best = rows;
    }
    if (best.length < 2) {
      const all = Array.from(document.querySelectorAll('body *'));
      const byKey = {};
      for (const el of all) {
        if (!el.className || typeof el.className !== 'string' || !el.className.trim()) continue;
        const key = el.tagName + '.' + el.className.trim().split(/\\s+/).join('.');
        (byKey[key] = byKey[key] || []).push(el);
      }
      let bestList = [];
      for (const key in byKey) {
        if (byKey[key].length > bestList.length && byKey[key].length >= 3) bestList = byKey[key];
      }
      if (bestList.length > best.length) best = bestList;
    }
    return best;
  }
  const rows = pickRows();
  const pairs = rows
    .map(el => ({ el, text: (el.innerText || '').trim() }))
    .filter(p => p.text.length > 0);
  window.__gwRows = pairs.map(p => p.el);
  return pairs.map(p => p.text);
}
"""

_GET_LINK_JS = """
(idx) => {
  const el = window.__gwRows && window.__gwRows[idx];
  if (!el) return null;
  // 메일함처럼 한 행 안에 링크가 여러 개 있을 때(보낸사람 이름 링크, 중요도 아이콘,
  // 플래그, 카테고리 등) 첫 번째 <a>를 그냥 집으면 엉뚱한 링크(예: 보낸사람 정보)를
  // 클릭하게 된다. 실제 "제목/본문 열기" 링크는 보통 name="aSubject" 처럼 subject를
  // 가리키는 이름을 쓰므로 이를 최우선으로 찾는다.
  // 실제 eugenes.co.kr 그룹웨어(전자결재 완료함) 화면을 열어보니, "열람"이라는 별도
  // 액션 링크가 제목 링크보다 DOM상 먼저 나와서 그걸 클릭해버리면 인라인 미리보기만
  // 뜨고 상세화면 URL은 안 바뀌는 문제가 있었다 — 실제 제목 링크는
  // class="taTit" 이거나 onclick="onClickPopButton(...)"(새 팝업창을 여는 함수)로
  // 식별할 수 있어서 이를 최우선으로 찾는다.
  const subjectLink = el.querySelector(
    'a.taTit, a[onclick*="onClickPopButton"], ' +
    'a[name="aSubject"], a[id*="aSubject" i], a[name*="subject" i], a[id*="subject" i]'
  );
  if (subjectLink) return subjectLink;
  return el.querySelector('a') || el;
}
"""

_GOTO_PAGE_JS = """
(pageNum) => {
  const target = String(pageNum);
  const candidates = Array.from(document.querySelectorAll('a, button, span[onclick], li[onclick], td[onclick]'));
  // 1순위: 페이지 번호 숫자가 그대로 텍스트로 보이는 링크 (예: "2") - 아이콘 폰트라 텍스트를
  // 못 읽는 '>' 버튼보다 훨씬 안정적으로 잡힌다.
  const exact = candidates.find(el => (el.innerText || '').trim() === target && el.offsetParent !== null);
  if (exact) {
    exact.click();
    return true;
  }
  // 2순위: '다음/>' 류 텍스트 버튼 (숫자 링크를 못 찾았을 때 대비)
  const nextTexts = ['>', '»', '다음', '다음페이지', '다음 페이지', 'next'];
  const isNextLike = (t) => nextTexts.includes((t || '').trim().toLowerCase());
  const next = candidates.find(el => isNextLike(el.innerText) && el.offsetParent !== null);
  if (next) {
    next.click();
    return true;
  }
  return false;
}
"""


_ROW_HTML_JS = """
(idx) => {
  const el = window.__gwRows && window.__gwRows[idx];
  return el ? el.outerHTML : null;
}
"""

_ROW_META_JS = """
(idx) => {
  const el = window.__gwRows && window.__gwRows[idx];
  if (!el) return null;
  // 메일함 행의 체크박스 <input>에는 subject/sender/senderemail/receivedate 같은
  // 정확한 값이 속성으로 이미 박혀있다 (본문 텍스트를 정규식으로 긁는 것보다 훨씬
  // 정확하다). 있으면 이 값을 최우선으로 쓴다.
  const input = el.querySelector('input[subject]') || el.querySelector('input[mid]');
  if (!input) return null;
  return {
    subject: input.getAttribute('subject') || '',
    sender: input.getAttribute('sender') || '',
    senderemail: input.getAttribute('senderemail') || '',
    receivedate: input.getAttribute('receivedate') || '',
  };
}
"""


def scan_rows(frame: Frame, max_rows: int = 80) -> List[str]:
    try:
        rows = frame.evaluate(_SCAN_JS)
    except Exception:
        return []
    return rows[:max_rows]


def row_html(frame: Frame, index: int) -> str:
    """진단용: index번째 행의 실제 HTML(outerHTML)을 반환한다.

    클릭/더블클릭 모두 아무 반응이 없을 때, 실제로 어떤 태그/onclick 구조인지
    직접 눈으로 확인하기 위한 함수 (디버그 덤프에 포함시켜서 원인 파악에 쓴다).
    """
    try:
        html = frame.evaluate(_ROW_HTML_JS, index)
        return html or ""
    except Exception:
        return ""


def row_meta(frame: Frame, index: int) -> dict:
    """index번째 행의 subject/sender/senderemail/receivedate 속성을 그대로 읽어온다.

    (있으면) 본문을 정규식으로 긁어서 추측하는 것보다 훨씬 정확한 값이라, 제목/
    발신자/수신일 판단에 최우선으로 쓴다. 이런 속성이 없는 화면(전자결재 등)이면
    빈 dict를 반환하니 호출하는 쪽에서 기존 방식으로 대체해야 한다.
    """
    try:
        meta = frame.evaluate(_ROW_META_JS, index)
        return meta or {}
    except Exception:
        return {}


def open_row(frame: Frame, index: int) -> bool:
    """행을 클릭해서 상세 화면을 연다.

    스크립트(frame.evaluate)에서 DOM의 .click()을 직접 호출하면 브라우저가 이를
    '진짜 사용자 조작'으로 인정하지 않아서, 그 클릭으로 뜨는 새 창(window.open)이
    팝업 차단으로 조용히 막히는 경우가 있다. 그래서 Playwright의 ElementHandle로
    실제 마우스 클릭 이벤트를 보낸다.

    (실제 사이트 HTML을 확인해보니 제목 링크에 onclick="aSubject_click(...)" 같은
    단일 클릭 핸들러가 붙어있었다 - 더블클릭은 오히려 핸들러를 두 번 호출해서
    열었다 닫았다 하는 부작용이 생길 수 있으므로 단일 클릭만 사용한다.)
    """
    try:
        handle = frame.evaluate_handle(_GET_LINK_JS, index)
        el = handle.as_element()
        if el is None:
            return False
        el.click(timeout=3000)
        return True
    except Exception:
        return False


def go_to_next_page(frame: Frame, next_page_num: int) -> bool:
    """목록 화면에서 다음 페이지로 이동한다. 못 찾으면 False.

    우선 '다음 페이지 번호'(예: 2페이지에 있으면 "3")가 그대로 텍스트로 보이는 링크를
    찾아서 클릭하고, 없으면 '>'/'다음' 같은 화살표/텍스트 버튼을 시도한다.
    (숫자 링크를 우선하는 이유: '>' 화살표가 아이콘 폰트로 그려지는 사이트가 많아
    innerText 로는 안 잡히는 경우가 있기 때문)
    """
    try:
        return bool(frame.evaluate(_GOTO_PAGE_JS, next_page_num))
    except Exception:
        return False


def is_excluded(text: str, exclude_keywords: List[str]) -> bool:
    return any(kw in text for kw in exclude_keywords if kw)
