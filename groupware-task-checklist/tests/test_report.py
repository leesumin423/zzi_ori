from datetime import date

from review.models import DraftDocument, DraftReview, Finding
from review.report import build_report_html


def test_report_includes_findings_and_escapes_html():
    draft = DraftDocument(title="<script>alert(1)</script>", form_type="기안지", drafter="홍길동", url="https://example.com")
    review = DraftReview(
        draft=draft,
        overall_assessment="금리 표기가 본문과 표에서 다릅니다.",
        risk_level="주의",
        findings=[Finding(category="숫자오류", severity="주의", description="금리 불일치", quote="3.97%", suggestion="확인 필요")],
    )
    html_out = build_report_html([review], date(2026, 7, 8))
    assert "&lt;script&gt;" in html_out
    assert "<script>alert(1)</script>" not in html_out
    assert "금리 불일치" in html_out
    assert "주의" in html_out


def test_report_handles_error_and_empty():
    err_review = DraftReview(draft=DraftDocument(title="실패문서"), error="API 호출 실패: timeout")
    html_out = build_report_html([err_review], date(2026, 7, 8))
    assert "검토 실패" in html_out
    assert "timeout" in html_out

    empty_html = build_report_html([], date(2026, 7, 8))
    assert "검토 대상" in empty_html
