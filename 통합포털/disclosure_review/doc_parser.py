"""DART 정기보고서 XML(dart4.xsd 계열) 공용 파서.

두 가지 입력을 모두 이 모듈로 파싱한다:
  - 서식작성기 초안(.dsd, zip 안의 contents.xml)
  - DART Open API로 받은 이미 제출된 원문(zip 안의 document.xml)

두 파일 모두 같은 dart4.xsd 스키마를 쓰지만, 초안(.dsd)에는 서식작성기 편집용
지시 태그(APPENDIX, INSERTION, LIBRARYLIST, COMMENT)가 섞여 있어 실제 제출본에는
없는 것들이라 파싱 시 무시한다.

문서를 "섹션(TITLE ATOC 태그로 구분되는 목차 단위) > 블록(문단/표)" 구조로
평탄화한다. 섹션 정렬 키는 AASSOCNOTE 속성(있으면)을 우선 쓰는데, 이 값은 조번호가
바뀌어도(예: 3번 항목이 4번이 되어도) 안정적으로 유지되는 DART 내부 코드라
전기/당기 비교에 훨씬 안정적이다.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

HEADING_TAGS = {'TITLE', 'COVER-TITLE'}
CELL_TAGS = {'TD', 'TU', 'TE', 'TH'}
IGNORE_TAGS = {'APPENDIX', 'INSERTION', 'COMMENT', 'LIBRARYLIST'}
NUMERIC_UNIT_HINTS = {
    'WON', 'WONPERCENT', 'STOCK', 'STOCKPERCENT', 'PERCENT', 'DAT', 'DATE',
    'DT', 'AMNT', 'CNT', 'PIS',
}


def _clean_text(raw: str) -> str:
    # DART 서식은 줄바꿈을 실제 개행이 아니라 "&cr;" 리터럴로 표현한다.
    text = (raw or '').replace('&cr;', '\n')
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.split('\n')]
    return '\n'.join(line for line in lines if line)


def _element_text(el) -> str:
    return _clean_text(''.join(el.itertext()))


@dataclass
class Cell:
    tag: str
    text: str
    unit: str = ''

    @property
    def is_numeric_like(self) -> bool:
        if self.unit and any(hint in self.unit for hint in NUMERIC_UNIT_HINTS):
            return True
        stripped = self.text.replace(',', '').replace('%', '').replace('-', '').strip()
        return bool(stripped) and bool(re.fullmatch(r'[\d.\s()]+', stripped))


@dataclass
class Row:
    cells: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.cells[0].text if self.cells else ''


@dataclass
class Table:
    rows: list = field(default_factory=list)


@dataclass
class Block:
    kind: str  # 'paragraph' | 'heading' | 'table'
    text: str = ''
    table: Table = None


@dataclass
class Section:
    key: str
    atocid: str
    title: str
    title_eng: str
    top_level: bool
    blocks: list = field(default_factory=list)

    @property
    def paragraphs(self):
        return [b.text for b in self.blocks if b.kind in ('paragraph', 'heading') and b.text]

    @property
    def tables(self):
        return [b.table for b in self.blocks if b.kind == 'table']


@dataclass
class ParsedDocument:
    company_name: str
    doc_name: str
    sections: list = field(default_factory=list)

    def section_by_key(self, key: str):
        for s in self.sections:
            if s.key == key:
                return s
        return None


def _parse_table(table_el) -> Table:
    table = Table()
    for tr in table_el.iter('TR'):
        row = Row()
        for cell_el in tr:
            tag = cell_el.tag
            if tag not in CELL_TAGS:
                continue
            row.cells.append(Cell(
                tag=tag,
                text=_element_text(cell_el),
                unit=cell_el.attrib.get('AUNIT', ''),
            ))
        if row.cells:
            table.rows.append(row)
    return table


def _new_section(counter: list, atocid: str = '', title: str = '', title_eng: str = '',
                  assocnote: str = '', top_level: bool = False) -> Section:
    counter[0] += 1
    key = assocnote or (f"ATOC-{atocid}" if atocid else f"AUTO-{counter[0]}")
    return Section(key=key, atocid=atocid, title=title, title_eng=title_eng, top_level=top_level)


def _walk(el, sections: list, counter: list):
    tag = el.tag
    if tag in IGNORE_TAGS:
        return

    if tag in HEADING_TAGS:
        title = _element_text(el)
        section = _new_section(
            counter,
            atocid=el.attrib.get('ATOCID', ''),
            title=title,
            title_eng=el.attrib.get('ENG', ''),
            assocnote=el.attrib.get('AASSOCNOTE', ''),
            top_level=el.attrib.get('ATOC', '') == 'Y',
        )
        sections.append(section)
        # 제목 태그 자신도 문단으로 한 번 더 들어가지 않도록 자식 순회 없이 종료
        return

    if tag == 'TABLE':
        if not sections:
            sections.append(_new_section(counter, title='(머리말)'))
        sections[-1].blocks.append(Block(kind='table', table=_parse_table(el)))
        return  # 표 내부는 _parse_table에서 이미 다 처리했으므로 재귀 중단

    if tag in ('P', 'SPAN'):
        text = _element_text(el)
        if text:
            if not sections:
                sections.append(_new_section(counter, title='(머리말)'))
            sections[-1].blocks.append(Block(kind='paragraph', text=text))
        return  # P/SPAN 내부에 더 파고들 구조 없음

    for child in el:
        _walk(child, sections, counter)


_STRAY_AMPERSAND_RE = re.compile(r'&(?!(?:amp|lt|gt|quot|apos|cr);|#\d+;|#x[0-9a-fA-F]+;)')


def _sanitize_xml_text(text: str) -> str:
    # DART 문서에는 "M&A"처럼 이스케이프 안 된 "&"가 종종 섞여 있어 그대로
    # 파싱하면 ParseError가 난다. 유효한 엔티티가 아닌 "&"만 골라 이스케이프.
    return _STRAY_AMPERSAND_RE.sub('&amp;', text)


def parse_xml_bytes(raw: bytes) -> ParsedDocument:
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode('utf-8', errors='replace')
    text = _sanitize_xml_text(text)
    root = ET.fromstring(text)
    company_name = ''
    doc_name = ''
    for el in root.iter():
        if el.tag == 'COMPANY-NAME':
            company_name = _element_text(el) or el.attrib.get('AREGCIK', '')
        elif el.tag == 'DOCUMENT-NAME':
            doc_name = _element_text(el)
        if company_name and doc_name:
            break

    sections = []
    counter = [0]
    body = root.find('.//BODY')
    walk_root = body if body is not None else root
    for child in walk_root:
        _walk(child, sections, counter)

    return ParsedDocument(company_name=company_name, doc_name=doc_name, sections=sections)


def parse_dsd_or_document_zip(zip_bytes: bytes) -> ParsedDocument:
    """.dsd (contents.xml) 또는 DART document.xml zip 응답을 파싱."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = z.namelist()
        target = next((n for n in names if n.lower() == 'contents.xml'), names[0])
        raw = z.read(target)
    return parse_xml_bytes(raw)
