from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")
docx = pytest.importorskip("docx")
openpyxl = pytest.importorskip("openpyxl")

from review.attachments import extract_attachment


def test_extract_text_pdf(tmp_path: Path):
    pdf_path = tmp_path / "text.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "운영자금 차입기간 연장의 건 - 금리 3.97% 적용, 기표예정일 2026.07.18, 상환방법 만기일시상환",
        fontname="korea-s",
    )
    doc.save(str(pdf_path))
    doc.close()

    att = extract_attachment(pdf_path)
    assert "차입기간" in att.text
    assert not att.image_pngs
    assert not att.unsupported


def test_extract_scanned_pdf_falls_back_to_images(tmp_path: Path):
    pdf_path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    doc.new_page()  # 텍스트 없는 빈 페이지 -> 스캔본으로 간주되어야 함
    doc.save(str(pdf_path))
    doc.close()

    att = extract_attachment(pdf_path)
    assert len(att.image_pngs) == 1
    assert att.image_pngs[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_extract_docx(tmp_path: Path):
    docx_path = tmp_path / "doc.docx"
    d = docx.Document()
    d.add_paragraph("법인인감신청서")
    d.add_paragraph("사용목적: 대출 약정서 날인")
    d.save(str(docx_path))

    att = extract_attachment(docx_path)
    assert "법인인감신청서" in att.text
    assert "사용목적" in att.text


def test_extract_xlsx(tmp_path: Path):
    xlsx_path = tmp_path / "table.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "요약"
    ws.append(["구분", "금액"])
    ws.append(["대출", "250억원"])
    wb.save(str(xlsx_path))

    att = extract_attachment(xlsx_path)
    assert "250억원" in att.text
    assert "[시트: 요약]" in att.text


def test_extract_hwp_unsupported(tmp_path: Path):
    hwp_path = tmp_path / "doc.hwp"
    hwp_path.write_bytes(b"fake hwp content")

    att = extract_attachment(hwp_path)
    assert att.unsupported
    assert "HWP" in att.note
