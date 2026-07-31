"""담보물건지(차입금관리 프로그램의 real_estate_sites) 하나를 골라 그룹웨어 완료함에서
품의서를 찾고, 링크와 첨부파일(근저당권설정계약서ㆍ등기필증 등)을 차입금관리 DB에
그대로 저장한다 — 한 번 연결해두면 차입금관리 화면에서 다시 그룹웨어에 들어갈 필요 없이
바로 열람/다운로드할 수 있다.

find_approval_doc.py(검색 결과만 보여줌)와 다른 점: 이 스크립트는 찾은 결과 중 가장
최근 것 하나를 골라 실제로 real_estate_db(차입금관리 프로젝트)에 저장까지 한다.

사용법 (차입금관리/data/real_estate.db의 사업장 기준):
  python link_collateral_doc.py --site-name 예산공장
  python link_collateral_doc.py --site-name 예산공장 --keywords 농협 시설대
      (검색어를 안 주면 그 사업장의 담보은행(bank)을 기본 검색어로 쓴다)
  python link_collateral_doc.py --site-id 60

전제: 차입금관리 프로젝트가 이 프로젝트와 같은 상위 폴더(ai 개발관련) 안에 있어야
real_estate_db 모듈을 찾을 수 있다 — 실제로 그렇게 배치되어 있다.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

DEFAULT_FORM_TYPES = ["기안지", "법인인감신청서"]

# Windows 콘솔 기본 코드페이지(cp949)는 이모지(✅/⚠️ 등)를 인코딩하지 못해 print()가
# UnicodeEncodeError로 죽는다 — stdout/stderr을 UTF-8로 강제해서 이 문제를 피한다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 차입금관리 프로젝트의 real_estate_db.py를 그대로 재사용한다 (sqlite3/os/uuid만
# 쓰는 순수 stdlib 모듈이라 별도 설치 없이 import 가능).
# 이 스크립트는 실행 환경에 따라 다른 위치에 있을 수 있어(예: C:\Users\tyinc\-AI-\
# groupware-task-checklist 처럼 프로젝트 폴더 밖에 별도로 설치해서 쓰는 경우), __file__
# 기준 상대경로 대신 실제 데이터가 있는 절대경로를 우선 쓴다. 다른 PC/경로에서 쓰려면
# .env에 LOAN_APP_DIR을 넣거나 아래 기본값을 바꾸면 된다.
import os  # noqa: E402

LOAN_APP_DIR = Path(
    os.getenv("LOAN_APP_DIR", r"C:\Users\tyinc\Desktop\ai 개발관련\차입금관리")
)
sys.path.insert(0, str(LOAN_APP_DIR))

from config import DEBUG_DIR, config  # noqa: E402
from gw.approval_search import search_approval_docs  # noqa: E402
from gw.auth import LoginRequiredError, ensure_logged_in  # noqa: E402
from gw.browser import GWSession  # noqa: E402

try:
    import real_estate_db as redb  # noqa: E402
except ImportError:
    print(
        f"real_estate_db 모듈을 찾을 수 없습니다 ({LOAN_APP_DIR} 아래에 있어야 함). "
        "차입금관리 프로젝트 위치가 다르면 이 파일 상단의 LOAN_APP_DIR을 수정하세요.",
        file=sys.stderr,
    )
    raise

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "link_collateral_doc.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("link_collateral_doc")


def _doc_key(url: str) -> str | None:
    """URL에서 문서 정체성(processID)만 뽑아낸다. CFN_OpenWindowName은 클릭할 때마다
    바뀌는 팝업창 이름일 뿐 문서 식별자가 아니라서, 같은 문서인지 비교할 때는 이걸
    빼고 processID로만 비교해야 한다."""
    if not url:
        return None
    m = re.search(r"processID=(\d+)", url)
    return m.group(1) if m else url


def _find_conflicting_site(url: str, exclude_site_id: int) -> dict | None:
    """이 URL(문서)이 이미 다른 사업장에 연결되어 있으면 그 사업장 정보를 반환한다.
    은행명만으로 검색하면 같은 은행에서 여러 사업장이 대출을 받은 경우 완전히 다른
    사업장의 품의서를 잘못 가져올 수 있어서(실제로 겪은 문제) — 자동 저장 전에
    반드시 이 체크를 거친다."""
    key = _doc_key(url)
    if not key:
        return None
    for s in redb.list_sites():
        if s["id"] == exclude_site_id:
            continue
        if s.get("approval_doc_url") and _doc_key(s["approval_doc_url"]) == key:
            return s
    return None


def _find_site(site_id: int | None, site_name: str | None) -> dict:
    sites = redb.list_sites()
    if site_id is not None:
        matches = [s for s in sites if s["id"] == site_id]
    else:
        matches = [s for s in sites if s["site_name"] == site_name]
    if not matches:
        print(f"사업장을 찾지 못했습니다 (site_id={site_id}, site_name={site_name}).", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"이름이 같은 사업장이 {len(matches)}개 있습니다 — --site-id로 정확히 지정해주세요:", file=sys.stderr)
        for m in matches:
            print(f"  id={m['id']}  {m['site_name']} ({m['category']})", file=sys.stderr)
        sys.exit(1)
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="담보물건지 하나에 품의서+첨부파일을 자동으로 연결")
    parser.add_argument("--site-id", type=int, help="real_estate_sites.id")
    parser.add_argument("--site-name", type=str, help="사업장명 (예: 예산공장)")
    parser.add_argument("--keywords", nargs="*", default=None, help="검색어 (안 주면 담보은행명을 사용)")
    parser.add_argument("--max", type=int, default=3, help="폴더별 최대 검색 결과 수 (기본 3)")
    parser.add_argument(
        "--form-types", nargs="*", default=DEFAULT_FORM_TYPES,
        help=f"이 양식명에 해당하는 문서만 매칭 (기본: {', '.join(DEFAULT_FORM_TYPES)}). "
             "전부 허용하려면 --form-types 뒤에 아무것도 안 주면 안 되니 빈 리스트 대신 값을 다 나열하세요.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="이미 다른 사업장에 연결된 문서라도(같은 은행 공용 문서 등) 강제로 저장",
    )
    args = parser.parse_args()

    if not args.site_id and not args.site_name:
        print("--site-id 또는 --site-name 중 하나는 반드시 지정해야 합니다.", file=sys.stderr)
        sys.exit(1)

    site = _find_site(args.site_id, args.site_name)
    log.info("대상 사업장: %s (id=%d, 담보은행=%s, 담보내역=%s)",
              site["site_name"], site["id"], site.get("bank"), site.get("collateral_detail"))

    keywords = args.keywords
    if not keywords:
        if not site.get("bank"):
            print(
                f"'{site['site_name']}'에는 담보은행 정보가 없어 검색어를 자동으로 만들 수 없습니다. "
                "--keywords로 직접 지정해주세요 (예: --keywords 농협 시설대).",
                file=sys.stderr,
            )
            sys.exit(1)
        keywords = [site["bank"]]
    log.info("검색어: %s", keywords)

    completed_urls = {k: v for k, v in config.approval_urls.items() if "완료함" in k and v}
    if not completed_urls:
        print(
            "GW_APPROVAL_DEPT_COMPLETED_URL / GW_APPROVAL_PERSONAL_COMPLETED_URL 이 "
            ".env 에 설정되어 있지 않습니다. README의 2_로그인설정.bat 안내를 먼저 진행해주세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    check_url = next(iter(completed_urls.values()))
    session = GWSession(
        headed=config.headed, slowmo_ms=config.slowmo_ms, storage_state_path=config.storage_state_path
    )
    try:
        ensure_logged_in(
            session, config.login_url, check_url, config.gw_id, config.gw_pw,
            config.login_id_selector, config.login_pw_selector, config.login_submit_selector,
        )
        session.save_storage_state(config.storage_state_path)

        results = search_approval_docs(
            session, completed_urls, keywords, max_matches=args.max,
            download_attachments=True,
            attachments_dir=config.attachments_dir / "collateral_links",
            max_attachment_mb=config.max_attachment_mb,
            debug_dir=(DEBUG_DIR if config.debug_dump else None),
            form_type_filter=args.form_types,
        )
    except LoginRequiredError as e:
        print(f"로그인 필요: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        log.exception("검색 중 오류 발생")
        print("검색 중 오류가 발생했습니다. logs/link_collateral_doc.log 를 확인해주세요.", file=sys.stderr)
        sys.exit(1)
    finally:
        session.close()

    if not results:
        print(
            f"검색어 {keywords} + 양식({args.form_types}) 에 매칭되는 품의서를 찾지 못했습니다. "
            "--keywords로 다르게 시도하거나 --form-types로 허용 양식을 늘려보세요."
        )
        return

    if len(results) > 1:
        # 은행명만으로는 같은 은행에서 여러 사업장이 대출받은 경우를 구분할 수 없다
        # (실제로 겪은 문제) — 여러 건이 매칭되면 어느 게 맞는지 사람이 확인해야
        # 하므로 자동 저장하지 않고 후보를 전부 보여주기만 한다.
        print(f"⚠️ 검색어에 매칭되는 품의서가 {len(results)}건이라 어느 것이 맞는지 자동으로 정할 수 없습니다.")
        print("아래 중 맞는 문서를 확인한 뒤, 해당 URL을 차입금관리 화면에 수동으로 붙여넣어주세요.\n")
        for i, r in enumerate(results, 1):
            print(f"[{i}] {r['folder']} / 양식: {r['form_type']} — {r['title']}")
            print(f"    URL: {r['url']}")
        return

    best = results[0]
    log.info("매칭: [%s] %s -> %s (detail_opened=%s)",
              best["folder"], best["title"], best["url"], best.get("detail_opened"))

    conflict = _find_conflicting_site(best["url"], site["id"]) if best["url"] else None
    if conflict and not args.force:
        print(
            f"⚠️ 찾은 문서('{best['title']}')가 이미 다른 사업장 '{conflict['site_name']}'에 "
            f"연결되어 있습니다 — 같은 은행이라도 사업장별로 문서가 다를 수 있어 잘못 연결된 "
            "것일 가능성이 높습니다. 저장하지 않았습니다. 정말 같은 문서가 맞으면 --force로 "
            "다시 실행하거나, --keywords에 사업장명/대출과목 등을 추가해 더 좁혀서 찾아보세요."
        )
        return

    if best["url"] and best.get("detail_opened"):
        redb.update_site(site["id"], approval_doc_url=best["url"])
        print(f"✅ '{site['site_name']}'에 품의서 링크를 저장했습니다: {best['url']}")
    elif best["url"] and not best.get("detail_opened"):
        # url이 클릭 전 목록 화면과 똑같다 — 실제 상세화면이 열리지 않고 목록 URL을
        # 그대로 되돌려받은 것이라, 이걸 "품의서 링크"로 저장하면 잘못된 링크가 된다.
        # (README의 "목록 인식 방식과 한계" — 이 그룹웨어 화면 구조에 클릭 인식이
        # 맞지 않는 것으로 보인다. logs/link_collateral_doc.log 와 debug_dumps/ 폴더를
        # 확인해 실제 행 HTML을 보고 gw/scrape_common.py의 선택자를 조정해야 한다.)
        print(
            f"⚠️ '{best['title']}'을(를) 찾긴 했지만 상세화면이 실제로 열리지 않아 "
            "(목록 URL과 동일) 링크를 저장하지 않았습니다. "
            "logs/link_collateral_doc.log 와 debug_dumps/ 폴더를 확인해주세요."
        )
    else:
        print(f"⚠️ '{best['title']}' 상세 링크를 얻지 못해 URL은 저장하지 못했습니다.")

    saved_docs = 0
    for path in best.get("attachment_paths", []):
        try:
            file_bytes = path.read_bytes()
        except Exception:
            continue
        redb.add_document(
            site["id"], "품의서 사본", path.name, file_bytes,
            uploaded_by="자동검색(그룹웨어)",
            note=f"연결된 품의서: {best['title']} ({best['folder']})",
        )
        saved_docs += 1
    print(f"✅ 첨부파일 {saved_docs}건을 '{site['site_name']}'에 저장했습니다.")


if __name__ == "__main__":
    main()
