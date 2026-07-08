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

_CLICK_JS = """
(idx) => {
  const el = window.__gwRows && window.__gwRows[idx];
  if (!el) return false;
  const link = el.querySelector('a') || el;
  link.click();
  return true;
}
"""


def scan_rows(frame: Frame, max_rows: int = 80) -> List[str]:
    try:
        rows = frame.evaluate(_SCAN_JS)
    except Exception:
        return []
    return rows[:max_rows]


def open_row(frame: Frame, index: int) -> bool:
    try:
        return bool(frame.evaluate(_CLICK_JS, index))
    except Exception:
        return False


def is_excluded(text: str, exclude_keywords: List[str]) -> bool:
    return any(kw in text for kw in exclude_keywords if kw)
