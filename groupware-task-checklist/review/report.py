"""검토 결과를 자체완결형 HTML 리포트로 만든다 (외부 리소스 없이 브라우저에서 바로 열림)."""

from __future__ import annotations

import html
import webbrowser
from datetime import date, datetime
from pathlib import Path
from typing import List

from .models import DraftReview

_RISK_COLOR = {
    "위험": "#C62828",
    "주의": "#EF6C00",
    "참고": "#1565C0",
    "정상": "#2E7D32",
}
_SEVERITY_COLOR = {
    "위험": "#C62828",
    "주의": "#EF6C00",
    "참고": "#1565C0",
}


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _finding_html(f) -> str:
    color = _SEVERITY_COLOR.get(f.severity, "#616161")
    quote_html = f'<div class="quote">"{_esc(f.quote)}"</div>' if f.quote else ""
    suggestion_html = f'<div class="suggestion">→ {_esc(f.suggestion)}</div>' if f.suggestion else ""
    return f"""
    <div class="finding">
      <div class="finding-head">
        <span class="badge" style="background:{color}">{_esc(f.severity)}</span>
        <span class="category">{_esc(f.category)}</span>
      </div>
      <div class="desc">{_esc(f.description)}</div>
      {quote_html}
      {suggestion_html}
    </div>"""


def _review_card_html(r: DraftReview) -> str:
    d = r.draft
    if r.error:
        return f"""
    <div class="card error-card">
      <div class="card-head">
        <span class="badge" style="background:#616161">오류</span>
        <span class="title">{_esc(d.title)}</span>
      </div>
      <div class="meta">기안종류: {_esc(d.form_type) or '(알 수 없음)'} · 기안자: {_esc(d.drafter) or '(알 수 없음)'}</div>
      <div class="error-msg">검토 실패: {_esc(r.error)}</div>
    </div>"""

    color = _RISK_COLOR.get(r.risk_level, "#616161")
    if r.findings:
        findings_html = "".join(_finding_html(f) for f in r.findings)
    else:
        findings_html = '<div class="no-finding">지적사항 없음</div>'

    link_html = f'<a class="doc-link" href="{_esc(d.url)}" target="_blank" rel="noopener">원본 기안지 열기 →</a>' if d.url else ""

    return f"""
    <div class="card">
      <div class="card-head">
        <span class="badge" style="background:{color}">{_esc(r.risk_level)}</span>
        <span class="title">{_esc(d.title)}</span>
      </div>
      <div class="meta">기안종류: {_esc(d.form_type) or '(알 수 없음)'} · 기안자: {_esc(d.drafter) or '(알 수 없음)'} {link_html}</div>
      <div class="assessment">{_esc(r.overall_assessment)}</div>
      <div class="findings">{findings_html}</div>
    </div>"""


def build_report_html(reviews: List[DraftReview], run_date: date) -> str:
    # 에러난 것도 위로, 그 다음 위험도 순
    reviews_sorted = sorted(reviews, key=lambda r: (0 if r.error else r.sort_key()[0], r.draft.title))

    total = len(reviews)
    risky = sum(1 for r in reviews if not r.error and r.risk_level in ("위험", "주의"))
    errored = sum(1 for r in reviews if r.error)

    cards_html = "".join(_review_card_html(r) for r in reviews_sorted)
    if not reviews:
        cards_html = '<div class="empty">임시함에 검토 대상 기안 문서가 없습니다.</div>'

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>기안 결재 전 오류 검토 - {run_date.isoformat()}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: "Malgun Gothic", "맑은 고딕", -apple-system, sans-serif;
    max-width: 900px; margin: 0 auto; padding: 24px 16px 64px;
    background: #fafafa; color: #1a1a1a;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #1e1e1e; color: #e8e8e8; }}
    .card {{ background: #2a2a2a !important; border-color: #3a3a3a !important; }}
    .meta, .assessment {{ color: #bbb !important; }}
    .quote {{ background: #333 !important; color: #ddd !important; }}
  }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .subtitle {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
  .summary {{ display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 10px 16px; font-size: 13px; }}
  .card {{
    background: #fff; border: 1px solid #ddd; border-radius: 10px;
    padding: 16px 18px; margin-bottom: 14px;
  }}
  .error-card {{ border-left: 4px solid #616161; }}
  .card-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .badge {{
    color: #fff; font-size: 11px; font-weight: bold; padding: 2px 8px;
    border-radius: 10px; white-space: nowrap;
  }}
  .title {{ font-size: 15px; font-weight: bold; }}
  .meta {{ font-size: 12px; color: #666; margin-bottom: 8px; }}
  .doc-link {{ margin-left: 8px; color: #1565C0; text-decoration: none; }}
  .doc-link:hover {{ text-decoration: underline; }}
  .assessment {{ font-size: 13px; color: #444; margin-bottom: 10px; }}
  .error-msg {{ font-size: 13px; color: #C62828; }}
  .no-finding {{ font-size: 13px; color: #2E7D32; }}
  .finding {{ border-top: 1px solid #eee; padding: 10px 0; }}
  .finding:first-child {{ border-top: none; }}
  .finding-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
  .category {{ font-size: 12px; font-weight: bold; color: #555; }}
  .desc {{ font-size: 13px; margin-bottom: 4px; }}
  .quote {{ font-size: 12px; background: #f5f5f5; padding: 6px 10px; border-radius: 6px; margin-bottom: 4px; }}
  .suggestion {{ font-size: 12px; color: #2E7D32; }}
  .empty {{ text-align: center; color: #888; padding: 40px 0; }}
  .footer-note {{ margin-top: 32px; font-size: 12px; color: #888; border-top: 1px solid #ddd; padding-top: 12px; }}
</style>
</head>
<body>
  <h1>기안 결재 전 오류 검토</h1>
  <div class="subtitle">생성 시각: {generated_at}</div>
  <div class="summary">
    <div class="stat">전체 {total}건</div>
    <div class="stat">지적사항 있음 {risky}건</div>
    <div class="stat">검토 실패 {errored}건</div>
  </div>
  {cards_html}
  <div class="footer-note">
    이 결과는 AI(Claude)가 자동으로 검토한 내용입니다. 실제 결재 전에는 반드시 사람이 원본 문서와 첨부파일을 직접 확인해주세요.
    AI가 놓친 오류가 있을 수 있고, 지적된 내용이 실제로는 문제가 아닐 수도 있습니다.
  </div>
</body>
</html>"""


def save_report(html_content: str, reports_dir: Path, run_date: date) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"기안검토_{run_date.isoformat()}_{datetime.now().strftime('%H%M%S')}.html"
    path = reports_dir / filename
    path.write_text(html_content, encoding="utf-8")
    return path


def open_report(path: Path) -> None:
    webbrowser.open(path.resolve().as_uri())
