"""전자결재 완료함(부서함/개인함)에서 품의서를 검색해 상세화면 링크를 찾는다.

차입금관리 프로그램의 "담보 서류 및 품의서 링크" 화면에서 은행명ㆍ대출종류 같은
조건으로 품의서를 자동으로 찾아 연결해달라는 요청에서 시작된 도구다. main.py(업무
체크리스트)와 로그인 세션(.state/storage_state.json)을 그대로 공유하므로, 이 프로젝트를
한 번이라도 설정(login_setup.py)해뒀다면 별도 로그인 없이 바로 쓸 수 있다.

사용법:
  python find_approval_doc.py 농협 운영자금
      -> "농협"과 "운영자금"을 모두 포함하는 행을 부서함/개인함 완료함에서 찾는다.
  python find_approval_doc.py 농협 운영자금 --max 3
      -> 폴더별 최대 3건까지만 상세를 연다 (기본값 5).
  python find_approval_doc.py 농협 운영자금 --json
      -> 결과를 approval_search_results.json 에도 저장한다 (다른 프로그램이 읽어쓰기 좋게).

검색어는 공백으로 구분한 여러 단어를 모두(AND) 포함하는 행만 찾는다 — 예를 들어
"농협 운영자금 시설대"처럼 은행명+대출종류 조합으로 좁혀서 찾는 걸 권장한다(너무
막연한 검색어 하나만 쓰면 관련 없는 결재문서가 섞여 나올 수 있다).

주의: 목록/상세 인식은 gw/scrape_common.py의 범용 휴리스틱을 그대로 쓴다(README의
"목록 인식 방식과 한계" 참고) — 실제 화면에서 안 맞으면 HEADED=true로 눈으로 확인하며
조정이 필요할 수 있다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Windows 콘솔 기본 코드페이지(cp949)는 일부 문자를 인코딩하지 못해 print()가
# UnicodeEncodeError로 죽을 수 있다 — stdout/stderr을 UTF-8로 강제해서 피한다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from config import DEBUG_DIR, config
from gw.approval_search import search_approval_docs
from gw.auth import LoginRequiredError, ensure_logged_in
from gw.browser import GWSession

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "approval_search.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("find_approval_doc")


def main() -> None:
    parser = argparse.ArgumentParser(description="전자결재 완료함에서 품의서 검색")
    parser.add_argument("keywords", nargs="+", help="검색어 (공백으로 구분, 전부 포함하는 행만 찾음)")
    parser.add_argument("--max", type=int, default=5, help="폴더별 최대 결과 수 (기본 5)")
    parser.add_argument("--json", action="store_true", help="결과를 approval_search_results.json 에도 저장")
    parser.add_argument(
        "--form-types", nargs="*", default=None,
        help="이 양식명(예: 기안지 법인인감신청서)에 해당하는 문서만 검색 (기본: 전체 양식)",
    )
    args = parser.parse_args()

    completed_urls = {
        k: v for k, v in config.approval_urls.items() if "완료함" in k and v
    }
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

        log.info("검색어 %s 로 전자결재 완료함 검색 중...", args.keywords)
        results = search_approval_docs(
            session, completed_urls, args.keywords, max_matches=args.max,
            debug_dir=(DEBUG_DIR if config.debug_dump else None),
            form_type_filter=args.form_types,
        )
    except LoginRequiredError as e:
        print(f"로그인 필요: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        log.exception("검색 중 오류 발생")
        print("검색 중 오류가 발생했습니다. logs/approval_search.log 를 확인해주세요.", file=sys.stderr)
        sys.exit(1)
    finally:
        session.close()

    if not results:
        print(f"검색어 {args.keywords} 에 매칭되는 품의서를 찾지 못했습니다.")
    else:
        print(f"\n총 {len(results)}건 찾음 (최신순):\n")
        for i, r in enumerate(results, 1):
            warn = "" if r.get("detail_opened") else " ⚠️ 목록 URL과 동일 — 상세화면이 실제로 안 열렸을 수 있음"
            print(f"[{i}] {r['folder']} / 양식: {r.get('form_type')} — {r['title']}{warn}")
            print(f"    URL: {r['url']}")
            print()

    if args.json:
        out_path = Path(__file__).resolve().parent / "approval_search_results.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과를 {out_path} 에 저장했습니다.")


if __name__ == "__main__":
    main()
