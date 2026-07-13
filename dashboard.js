// dashboard.js – UI rendering for the stock dashboard

// 절대 주소 사용: server.py가 항상 5000번 포트로 뜨므로, html 파일을
// 파일탐색기에서 직접 더블클릭(file://)해서 열든, 서버 경유(http://localhost:5000)로
// 열든 상관없이 동일하게 동작한다. (상대 경로 '/data'를 쓰면 file://로 열었을 때
// fetch가 file:///data를 시도해 항상 실패한다.)
const API_BASE = 'http://localhost:5000/data';

// 현재기준(current, 실시간) / 장마감기준(close, 15:30 마감 고정) 전환 상태.
// 서버가 한 번에 두 값을 모두 내려주므로, 탭 전환은 재요청 없이 마지막으로
// 받아온 데이터(lastData)를 다시 그리기만 하면 된다.
let basis = 'current';
const BASIS_LABEL = { current: '현재기준', close: '장마감기준' };
let lastData = { exchange: null, indices: null, companies: null, cement: null, danpan: null, equity: null, large_holding: null, ftc: null };

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('refreshBtn')?.addEventListener('click', loadAllData);
  document.getElementById('pdfBtn')?.addEventListener('click', () => window.print());
  document.getElementById('investorModalClose')?.addEventListener('click', closeInvestorModal);
  document.getElementById('investorModalOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'investorModalOverlay') closeInvestorModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeInvestorModal();
  });
  document.querySelectorAll('#basisTabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      basis = btn.dataset.basis;
      document.querySelectorAll('#basisTabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      const note = document.getElementById('basisNote');
      if (note) note.textContent = `(${BASIS_LABEL[basis]})`;
      renderAll();
    });
  });
  document.querySelectorAll('#pageTabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#pageTabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      const page = btn.dataset.page;
      document.getElementById('page-stock').style.display = page === 'stock' ? '' : 'none';
      document.getElementById('page-disclosures').style.display = page === 'disclosures' ? '' : 'none';
      // 기준시점/실시간환율은 주가 데이터 전용이라 공시 화면에서는 숨긴다
      const stockOnly = document.getElementById('stockOnlySidebar');
      if (stockOnly) stockOnly.style.display = page === 'stock' ? '' : 'none';
      if (page === 'disclosures') {
        const activeDisclosure = document.querySelector('#disclosureTabs .tab-btn.active')?.dataset.disclosure ?? 'danpan';
        if (activeDisclosure === 'danpan' && !lastData.danpan) loadDanpan();
        if (activeDisclosure === 'ftc' && !lastData.ftc) loadFtc();
        if (activeDisclosure === 'equity') loadActiveEquitySub();
      }
    });
  });
  document.querySelectorAll('#disclosureTabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#disclosureTabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      const kind = btn.dataset.disclosure;
      document.getElementById('disclosure-danpan').style.display = kind === 'danpan' ? '' : 'none';
      document.getElementById('disclosure-ftc').style.display = kind === 'ftc' ? '' : 'none';
      document.getElementById('disclosure-equity').style.display = kind === 'equity' ? '' : 'none';
      if (kind === 'danpan' && !lastData.danpan) loadDanpan();
      if (kind === 'ftc' && !lastData.ftc) loadFtc();
      if (kind === 'equity') loadActiveEquitySub();
    });
  });
  document.querySelectorAll('#ftcRangeTabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#ftcRangeTabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      loadFtc(btn.dataset.ftcRange);
    });
  });
  document.querySelectorAll('#equitySubTabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#equitySubTabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      const sub = btn.dataset.equitySub;
      document.getElementById('equity-sub-officer').style.display = sub === 'officer' ? '' : 'none';
      document.getElementById('equity-sub-large-holding').style.display = sub === 'large_holding' ? '' : 'none';
      loadActiveEquitySub();
    });
  });
  document.querySelectorAll('.rule-btn').forEach(btn => {
    btn.addEventListener('click', () => showRuleModal(btn.dataset.rule));
  });
  document.getElementById('ruleModalClose')?.addEventListener('click', closeRuleModal);
  document.getElementById('ruleModalOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'ruleModalOverlay') closeRuleModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeRuleModal();
  });
  document.getElementById('checkSubmitBtn')?.addEventListener('click', runDanpanCheck);
  attachCommaFormatting(document.getElementById('checkAmount'));
  document.getElementById('ftcCheckSubmitBtn')?.addEventListener('click', runFtcCheck);
  document.getElementById('ftcCheckType')?.addEventListener('change', (e) => {
    const isGoods = e.target.value === 'goods_services';
    const label = document.getElementById('ftcCheckTargetLabel');
    const hint = document.getElementById('ftcCheckTargetHint');
    if (label) label.style.display = isGoods ? '' : 'none';
    if (hint) {
      hint.style.display = isGoods ? '' : 'none';
      if (isGoods) {
        const known = lastData.ftc?.meta?.known_goods_services_counterparties ?? [];
        hint.textContent = known.length
          ? `참고: 동양(주)이 최근 10년간 이 규정으로 실제 신고한 거래상대방은 ${known.join(', ')}뿐입니다(그 외 계열회사와의 상품ㆍ용역거래는 이 신고 이력이 없다는 뜻 — 다만 앞으로 다른 계열회사가 새로 20% 이상 지분을 갖게 되면 대상이 될 수 있으니 참고용으로만 쓰세요). 판단이 애매하면 자금팀에 문의하세요.`
          : '참고: "공정위공시" 탭을 한 번 열어야 실제 신고 이력 참고자료가 표시됩니다.';
      }
    }
  });
  attachCommaFormatting(document.getElementById('ftcCheckAmount'));
  attachCommaFormatting(document.getElementById('ftcCheckCapital'));
  loadAllData();
});

// 숫자 입력칸에 입력하는 즉시 천단위 콤마를 넣어준다 — 0을 세다 실수하는 걸
// 방지하려는 목적. type="number"는 콤마 표시가 아예 안 돼서 type="text"로 받고
// 이 핸들러로 서식을 입힌다(전송 시에는 콤마를 다시 제거해서 보낸다).
function attachCommaFormatting(input) {
  if (!input) return;
  input.addEventListener('input', () => {
    const digitsBeforeCursor = input.value.slice(0, input.selectionStart).replace(/[^\d]/g, '').length;
    const digitsOnly = input.value.replace(/[^\d]/g, '');
    input.value = digitsOnly ? Number(digitsOnly).toLocaleString('ko-KR') : '';
    let seen = 0, pos = input.value.length;
    for (let i = 0; i < input.value.length; i++) {
      if (/\d/.test(input.value[i])) seen++;
      if (seen === digitsBeforeCursor) { pos = i + 1; break; }
    }
    input.setSelectionRange(pos, pos);
  });
}

async function safeFetch(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  return resp.json();
}

async function loadAllData() {
  const lastEl = document.getElementById('lastUpdated');
  if (lastEl) lastEl.textContent = '데이터 로딩 중…';
  try {
    const [exchange, indices, themes, companies, cement] = await Promise.all([
      safeFetch(`${API_BASE}?section=exchange`),
      safeFetch(`${API_BASE}?section=indices`),
      safeFetch(`${API_BASE}?section=themes`),
      safeFetch(`${API_BASE}?section=companies`),
      safeFetch(`${API_BASE}?section=cement`),
    ]);
    lastData = { exchange, indices, themes, companies, cement };
    renderAll();
    if (lastEl) {
      const now = new Date();
      lastEl.textContent = `마지막 업데이트: ${now.toLocaleString('ko-KR')}`;
    }
  } catch (err) {
    console.warn('Dashboard load error:', err);
    // alert 대신 화면 우측 상단이나 상태 텍스트로만 표시
    if (lastEl) lastEl.textContent = '오류 발생 (서버 확인 필요)';
  }

  // 수급 분석 + 뉴스 스크랩이 필요해 시간이 더 걸리므로 메인 렌더와 분리해서
  // 별도로 불러온다 (실패해도 나머지 대시보드에는 영향 없음).
  loadCommentary();
}

async function loadCommentary() {
  const list = document.getElementById('commentary-list');
  if (!list) return;
  try {
    const data = await safeFetch(`${API_BASE}?section=commentary`);
    const lines = Array.isArray(data.lines) ? data.lines : [];
    list.innerHTML = lines.length
      ? lines.map(line => `<li>${line}</li>`).join('')
      : '<li>코멘트 없음</li>';
  } catch (err) {
    list.innerHTML = `<li>코멘트 로드 실패: ${err.message}</li>`;
  }
}

// ── 단판공시(단일판매ㆍ공급계약체결) 모니터링 ──────────────────
async function loadDanpan() {
  const note = document.getElementById('danpanNote');
  const tbody = document.querySelector('#danpan-table tbody');
  if (note) note.textContent = 'DART 공시 원문을 조회하는 중… (수십 건을 하나씩 받아오므로 다소 걸릴 수 있습니다)';
  if (tbody) tbody.innerHTML = '<tr><td colspan="9">로딩 중…</td></tr>';
  try {
    const data = await safeFetch(`${API_BASE}?section=danpan`);
    lastData.danpan = data;
    renderDanpan(data);
  } catch (err) {
    if (note) note.textContent = `조회 실패: ${err.message}`;
    if (tbody) tbody.innerHTML = `<tr><td colspan="9">조회 실패: ${err.message}</td></tr>`;
  }
}

function fmtMillion(won) {
  if (won == null) return '';
  return Math.round(won / 1_000_000).toLocaleString('ko-KR');
}

function fmtPct(rate) {
  if (rate == null) return '';
  const pct = rate * 100;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(1)}%`;
}

function escapeAttr(text) {
  return String(text ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

function renderDanpan(payload) {
  const tbody = document.querySelector('#danpan-table tbody');
  const note = document.getElementById('danpanNote');
  if (!tbody) return;

  const list = Array.isArray(payload) ? payload : (payload?.sites ?? []);
  const meta = Array.isArray(payload) ? {} : (payload?.meta ?? {});

  if (!Array.isArray(list) || list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9">진행 중인 단판공시 현장이 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
    if (note) note.textContent = '';
    return;
  }

  if (note) {
    let text = `총 ${list.length}건. `;
    if (meta.periodic_check_available && meta.periodic_report_base_date) {
      text += `가장 최근 정기보고서(기준일 ${meta.periodic_report_base_date})의 "단일판매ㆍ공급계약체결공시에 대한 진행 현황"에 남아있는 현장만 표시합니다 (그 표에서 빠지면 준공 등으로 관리가 종료된 것으로 판단). `
        + `이 기준일 이후 새로 신고된 현장은 아직 정기보고서에 반영되지 않아 공사기간 종료일로만 판단합니다.`;
    } else {
      text += `정기보고서 진행현황 조회에 실패해 공사기간 종료일 기준으로만 판단했습니다 — 종료일이 없는 "미정" 건은 실제로 이미 끝났을 수 있어 별도 확인이 필요합니다.`;
    }
    note.textContent = text;
  }

  tbody.innerHTML = '';
  list.forEach((item, idx) => {
    const period = (item.period_start || item.period_end)
      ? `${item.period_start ?? '?'} ~ ${item.period_end ?? '?'}`
      : '미정';
    const rate = item.change_rate;
    const rateClass = rate > 0 ? 'up' : rate < 0 ? 'down' : '';
    const revisionLabel = item.revision_count > 0 ? `${item.revision_count}차 정정` : '최초';
    const siteName = item.site_name ?? '';
    const counterparty = item.counterparty ?? '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="num">${idx + 1}</td>
      <td title="${escapeAttr(siteName)}">${siteName}</td>
      <td title="${escapeAttr(counterparty)}">${counterparty}</td>
      <td class="num">${item.initial_contract_date ?? ''}</td>
      <td class="num">${item.latest_disclosure_date ?? ''} (${revisionLabel})</td>
      <td class="num">${fmtMillion(item.amount)}</td>
      <td class="num ${rateClass}">${fmtPct(rate)}</td>
      <td class="num">${period}</td>
      <td><a href="${item.dart_url}" target="_blank" class="clickable-name">보기</a></td>`;
    tbody.appendChild(tr);
  });
}

// ── 공정위 공시(계열회사간 거래) 이력 ────────────────────────
let ftcRange = 'recent';

async function loadFtc(range = ftcRange) {
  ftcRange = range;
  const note = document.getElementById('ftcNote');
  const tbody = document.querySelector('#ftc-table tbody');
  if (note) note.textContent = 'DART 공시 원문을 조회하는 중… (처음 조회 시 최근 10년치를 하나씩 받아오므로 다소 걸릴 수 있습니다)';
  if (tbody) tbody.innerHTML = '<tr><td colspan="8">로딩 중…</td></tr>';
  try {
    const data = await safeFetch(`${API_BASE}?section=ftc&range=${range}`);
    lastData.ftc = data;
    renderFtc(data);
  } catch (err) {
    if (note) note.textContent = `조회 실패: ${err.message}`;
    if (tbody) tbody.innerHTML = `<tr><td colspan="8">조회 실패: ${err.message}</td></tr>`;
  }
}

function renderFtc(payload) {
  const tbody = document.querySelector('#ftc-table tbody');
  const note = document.getElementById('ftcNote');
  if (!tbody) return;

  const list = Array.isArray(payload) ? payload : (payload?.records ?? []);
  const meta = Array.isArray(payload) ? {} : (payload?.meta ?? {});
  const isRecent = meta.range !== 'all';

  if (!Array.isArray(list) || list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8">공정위 공시 이력이 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
    if (note) {
      note.textContent = isRecent && meta.total_count_all_years > 0
        ? `최근 1년간은 해당 이력이 없습니다(전체 ${meta.lookback_years ?? 10}년간 ${meta.total_count_all_years}건 있음 — "전체 이력" 탭에서 확인).`
        : '';
    }
    return;
  }

  if (note) {
    note.textContent = isRecent
      ? `최근 1년간 ${list.length}건. 특수관계인에대한출자ㆍ채권매도, 동일인등출자계열회사와의상품ㆍ용역거래 3종만 집계했습니다 `
        + `(대규모기업집단현황공시, 지급수단별ㆍ지급기간별지급금액및분쟁조정기구에관한사항은 범위 밖). 접수일 최신순 — `
        + `전체 ${meta.lookback_years ?? 10}년간은 총 ${meta.total_count_all_years ?? list.length}건입니다("전체 이력" 탭 참고).`
      : `최근 ${meta.lookback_years ?? 10}년간 총 ${list.length}건. 특수관계인에대한출자ㆍ채권매도, 동일인등출자계열회사와의상품ㆍ용역거래 3종만 `
        + `집계했습니다(대규모기업집단현황공시, 지급수단별ㆍ지급기간별지급금액및분쟁조정기구에관한사항은 범위 밖). 접수일 최신순입니다.`;
  }

  tbody.innerHTML = '';
  list.forEach((item, idx) => {
    const counterparty = item.counterparty ?? '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="num">${idx + 1}</td>
      <td>${item.type_label ?? ''}</td>
      <td title="${escapeAttr(counterparty)}">${counterparty}</td>
      <td>${item.relation ?? ''}</td>
      <td class="num">${item.disclosure_date ?? ''}</td>
      <td class="num">${item.board_date ?? ''}</td>
      <td class="num">${item.amount_label ?? ''}</td>
      <td><a href="${item.dart_url}" target="_blank" class="clickable-name">보기</a></td>`;
    tbody.appendChild(tr);
  });
}

// ── 공정위 공시(대규모내부거래) 대상여부 사전검증 ─────────────────
async function runFtcCheck() {
  const typeSelect = document.getElementById('ftcCheckType');
  const amountInput = document.getElementById('ftcCheckAmount');
  const capitalInput = document.getElementById('ftcCheckCapital');
  const targetCheckbox = document.getElementById('ftcCheckTarget');
  const result = document.getElementById('ftcCheckResult');
  if (!result) return;

  const transactionType = typeSelect?.value;
  const amount = amountInput?.value?.replace(/,/g, '');
  const capitalBase = capitalInput?.value?.replace(/,/g, '');
  if (!amount || !capitalBase) {
    result.innerHTML = '<p class="check-error">거래금액과 자본총계ㆍ자본금 중 큰 금액을 모두 입력해주세요.</p>';
    return;
  }

  result.innerHTML = '<p class="info">판단하는 중…</p>';
  try {
    const isTarget = transactionType === 'goods_services' ? (targetCheckbox?.checked ? '1' : '0') : '1';
    const resp = await fetch(`${API_BASE}?section=ftc_check&transaction_type=${encodeURIComponent(transactionType)}`
      + `&amount=${encodeURIComponent(amount)}&capital_base=${encodeURIComponent(capitalBase)}&is_goods_services_target=${isTarget}`);
    const data = await resp.json();
    if (!resp.ok) {
      result.innerHTML = `<p class="check-error">${escapeAttr(data.error ?? `조회 실패 (HTTP ${resp.status})`)}</p>`;
      return;
    }
    result.innerHTML = renderFtcCheckResult(data);
  } catch (err) {
    result.innerHTML = `<p class="check-error">조회 실패: ${escapeAttr(err.message)}</p>`;
  }
}

function renderFtcCheckResult(r) {
  const verdictClass = r.is_disclosure_required ? 'required' : 'not-required';
  const verdictText = r.is_disclosure_required ? '이사회 의결 및 공시 대상입니다' : '공시대상이 아닙니다';
  const checkMark = (ok) => ok ? '<span class="up">✓ 충족</span>' : '<span class="down">✗ 미충족</span>';
  const typeLabel = r.transaction_type === 'goods_services' ? '상품ㆍ용역 거래' : '자금ㆍ유가증권ㆍ자산 거래';

  let targetRow = '';
  if (r.transaction_type === 'goods_services') {
    // is_goods_services_target=false로 판단이 끝난 경우만 reason에 "해당하지 않아"가 들어있음
    const failedTarget = r.reason.includes('해당하지 않아');
    targetRow = `<li>거래상대방 요건("동일인·동일인 친족 20%이상 출자 계열회사 또는 그 50%초과 자회사"): ${checkMark(!failedTarget)}</li>`;
  }

  return `
    <div class="check-verdict ${verdictClass}">${verdictText}</div>
    <p class="info">거래유형: <b>${typeLabel}</b></p>
    <ul class="info" style="margin:4px 0 8px; padding-left:20px;">
      <li>거래금액 100억원 이상: ${checkMark(r.amount_ge_100eok)}</li>
      <li>자본총계ㆍ자본금 중 큰 금액의 5%(최소 5억원) 이상: ${checkMark(r.amount_ge_capital_pct)}</li>
      ${targetRow}
    </ul>
    <p class="info">${escapeAttr(r.reason)}</p>
    <p class="info">기준금액(자본총계ㆍ자본금 중 큰 금액의 5%, 최소 5억원): <b>${fmtWon(r.threshold_amount)}원</b></p>`;
}

// 지분공시 탭 안에는 임원ㆍ주요주주(officer) / 대량보유상황보고서(large_holding)
// 두 하위 탭이 있다 — 현재 선택된 쪽만, 아직 안 불러왔으면 불러온다.
function loadActiveEquitySub() {
  const sub = document.querySelector('#equitySubTabs .tab-btn.active')?.dataset.equitySub ?? 'officer';
  if (sub === 'officer' && !lastData.equity) loadEquity();
  if (sub === 'large_holding' && !lastData.large_holding) loadLargeHolding();
}

// ── 지분공시(임원ㆍ주요주주 소유상황보고서) 이력 ────────────────
async function loadEquity() {
  const note = document.getElementById('equityNote');
  const tbody = document.querySelector('#equity-table tbody');
  if (note) note.textContent = 'DART 공시 원문을 조회하는 중… (최근 10년치를 하나씩 받아오므로 다소 걸릴 수 있습니다)';
  if (tbody) tbody.innerHTML = '<tr><td colspan="8">로딩 중…</td></tr>';
  try {
    const data = await safeFetch(`${API_BASE}?section=equity`);
    lastData.equity = data;
    renderEquity(data);
  } catch (err) {
    if (note) note.textContent = `조회 실패: ${err.message}`;
    if (tbody) tbody.innerHTML = `<tr><td colspan="8">조회 실패: ${err.message}</td></tr>`;
  }
}

function fmtWon(won) {
  if (won == null) return '';
  return Math.round(won).toLocaleString('ko-KR');
}

function renderEquity(payload) {
  const tbody = document.querySelector('#equity-table tbody');
  const note = document.getElementById('equityNote');
  if (!tbody) return;

  const list = Array.isArray(payload) ? payload : (payload?.records ?? []);
  const meta = Array.isArray(payload) ? {} : (payload?.meta ?? {});

  if (!Array.isArray(list) || list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8">매수 이력이 있는 지분공시가 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
    if (note) note.textContent = '';
    return;
  }

  if (note) {
    note.textContent = `총 ${list.length}명. 최근 ${meta.lookback_years ?? 10}년간 "임원ㆍ주요주주특정증권등소유상황보고서" 중 장내매수 이력만 집계했습니다 (매도ㆍ증여ㆍ주식병합 등은 제외). `
      + (meta.officer_roster_available
          ? '현재 정기보고서의 임원 현황에 없는(=퇴임한) 임원은 제외했습니다(주요주주 법인은 예외). '
          : '정기보고서 임원 현황 조회에 실패해 퇴임 여부를 걸러내지 못했습니다 — 지난 임원이 섞여 있을 수 있습니다. ')
      + `DART 신고는 거래일로부터 최대 5영업일까지 걸릴 수 있어 아주 최근 거래는 아직 반영되지 않았을 수 있습니다.`;
  }

  tbody.innerHTML = '';
  list.forEach((item, idx) => {
    const holderName = item.holder_name ?? '';
    const roleLabel = item.role_label ?? '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="num">${idx + 1}</td>
      <td title="${escapeAttr(holderName)}">${holderName}</td>
      <td>${roleLabel}</td>
      <td class="num">${item.first_buy_date ?? ''}</td>
      <td class="num">${item.latest_buy_date ?? ''}</td>
      <td class="num">${fmtWon(item.total_qty)}</td>
      <td class="num">${fmtWon(item.avg_price)}</td>
      <td><a href="${item.dart_url}" target="_blank" class="clickable-name">보기</a></td>`;
    tbody.appendChild(tr);
  });
}

// ── 지분공시(주식등의 대량보유상황보고서, "5% Rule") 이력 ──────────
async function loadLargeHolding() {
  const note = document.getElementById('largeHoldingNote');
  const tbody = document.querySelector('#large-holding-table tbody');
  if (note) note.textContent = 'DART 공시 원문을 조회하는 중… (최근 10년치를 하나씩 받아오므로 다소 걸릴 수 있습니다)';
  if (tbody) tbody.innerHTML = '<tr><td colspan="7">로딩 중…</td></tr>';
  try {
    const data = await safeFetch(`${API_BASE}?section=large_holding`);
    lastData.large_holding = data;
    renderLargeHolding(data);
  } catch (err) {
    if (note) note.textContent = `조회 실패: ${err.message}`;
    if (tbody) tbody.innerHTML = `<tr><td colspan="7">조회 실패: ${err.message}</td></tr>`;
  }
}

function fmtPct1(ratio) {
  if (ratio == null) return '';
  return `${ratio.toFixed(2)}%`;
}

function renderLargeHolding(payload) {
  const tbody = document.querySelector('#large-holding-table tbody');
  const note = document.getElementById('largeHoldingNote');
  if (!tbody) return;

  const list = Array.isArray(payload) ? payload : (payload?.records ?? []);
  const meta = Array.isArray(payload) ? {} : (payload?.meta ?? {});

  if (!Array.isArray(list) || list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7">대량보유상황보고서 이력이 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
    if (note) note.textContent = '';
    return;
  }

  if (note) {
    note.textContent = `총 ${list.length}명(법인 포함). 최근 ${meta.lookback_years ?? 10}년간 "주식등의 대량보유상황보고서"에 함께 연명 신고된 `
      + `"보고자 및 특별관계자별 보유내역" 표를 신고자 단위로 펼쳐 집계했습니다 — 보고자 본인뿐 아니라 특별관계자(계열회사ㆍ공동보유자ㆍ임원 등)도 각자 한 행입니다. `
      + `같은 사람/법인이 여러 회차에 걸쳐 나오면 가장 최근 회차의 보유수량을 "누적 주식수"로 표시하며, 가장 최근 등장 이후 새 보고가 없는 경우 그 시점 수치가 최신 그대로 유지됩니다.`;
  }

  // 서버가 이미 보고자명 기준으로 그룹핑해 정렬해 보내주므로, 같은 보고자명이
  // 연속된 구간의 길이(rowspan)만 미리 세어둔다 — 그룹 첫 행에만 보고자명 셀을
  // rowspan으로 찍고 나머지 행에는 그 컬럼 자체를 생략해 시각적으로 병합한다.
  tbody.innerHTML = '';
  list.forEach((item, idx) => {
    const reporterName = item.reporter_name ?? '';
    const holderName = item.holder_name ?? '';
    const roleLabel = item.role_label ?? '';
    const qtyLabel = item.total_qty != null
      ? `${fmtWon(item.total_qty)}${item.ratio != null ? ` (${fmtPct1(item.ratio)})` : ''}`
      : '';
    const isGroupStart = idx === 0 || list[idx - 1].reporter_name !== reporterName;
    let reporterCell = '';
    if (isGroupStart) {
      let span = 1;
      while (idx + span < list.length && list[idx + span].reporter_name === reporterName) span++;
      reporterCell = `<td rowspan="${span}" title="${escapeAttr(reporterName)}">${reporterName}</td>`;
    }
    const tr = document.createElement('tr');
    tr.innerHTML = `
      ${reporterCell}
      <td title="${escapeAttr(holderName)}">${holderName}</td>
      <td>${roleLabel}</td>
      <td class="num">${item.first_disclosure_date ?? ''}</td>
      <td class="num">${item.latest_disclosure_date ?? ''}</td>
      <td class="num">${qtyLabel}</td>
      <td><a href="${item.dart_url}" target="_blank" class="clickable-name">보기</a></td>`;
    tbody.appendChild(tr);
  });
}

// ── 공시 규정 안내 모달 ──────────────────────────────────────
function fmtEok(won) {
  // 억원 단위로 보기 좋게 (예: 31,531,394,952 → "약 315.3억원")
  if (won == null) return '';
  return `약 ${(won / 100_000_000).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}억원`;
}

function showRuleModal(kind) {
  const overlay = document.getElementById('ruleModalOverlay');
  const title = document.getElementById('ruleModalTitle');
  const body = document.getElementById('ruleModalBody');
  if (!overlay || !body) return;

  if (kind === 'danpan') {
    title.textContent = '단판공시 — 수시공시 의무기준';
    const rule = lastData.danpan?.meta?.disclosure_rule;
    body.innerHTML = ruleDanpanHtml(rule);
  } else if (kind === 'large_holding') {
    title.textContent = '대량보유상황보고서 — "5% Rule"';
    body.innerHTML = ruleLargeHoldingHtml();
  } else if (kind === 'ftc') {
    title.textContent = '공정위 공시 — 대규모내부거래 이사회 의결ㆍ공시';
    body.innerHTML = ruleFtcHtml();
  } else {
    title.textContent = '지분공시 — 소유상황 보고의무';
    body.innerHTML = ruleEquityHtml();
  }
  overlay.classList.add('show');
}

function closeRuleModal() {
  document.getElementById('ruleModalOverlay')?.classList.remove('show');
}

function ruleDanpanHtml(rule) {
  if (!rule) {
    return '<p>매출액 기준 정보를 불러오지 못했습니다 (DART 재무제표 조회 실패). 잠시 후 "단판공시" 탭을 다시 열어보세요.</p>';
  }
  const pctLabel = `${(rule.threshold_pct * 100).toFixed(1)}%`;
  const largeLabel = rule.is_large_corp ? '대규모법인 (자산총액 2조원 이상)' : '일반법인 (대규모법인 아님)';
  return `
    <p>동양(주)이 단일판매ㆍ공급계약을 공시해야 하는 기준은 <b>최근 사업연도 연결 매출액의 5%</b>
    (자산총액 2조원 이상 대규모법인은 2.5%) 이상입니다. 계약해지도 같은 기준으로 공시 대상입니다.</p>
    <div class="rule-flow">
      <div class="rule-flow-box">
        <div class="rule-flow-label">${rule.fiscal_year}년 연결 매출액</div>
        <div class="rule-flow-value">${fmtWon(rule.revenue)}원</div>
      </div>
      <div class="rule-flow-arrow">×</div>
      <div class="rule-flow-box">
        <div class="rule-flow-label">${largeLabel}</div>
        <div class="rule-flow-value">${pctLabel}</div>
      </div>
      <div class="rule-flow-arrow">=</div>
      <div class="rule-flow-box highlight">
        <div class="rule-flow-label">공시 의무 기준금액</div>
        <div class="rule-flow-value">${fmtEok(rule.threshold_amount)}</div>
      </div>
    </div>
    <p class="info">즉, 계약(또는 해지)금액이 <b>${fmtWon(rule.threshold_amount)}원(${fmtEok(rule.threshold_amount)}) 이상</b>이면
    다음날까지 공시해야 합니다. (참고: ${rule.fiscal_year}년 연결 자산총계 ${fmtWon(rule.assets)}원 —
    2조원 미만이라 대규모법인 완화 기준은 적용되지 않습니다.)</p>
    <h4>그 외 관련 기준</h4>
    <ul>
      <li>공시시한: 계약 체결ㆍ해지일 다음날(익일)까지</li>
      <li>변경공시: 계약금액이 최초 대비 50% 이상 변경되면 재공시</li>
      <li>변경 신고 면제: 계약기간 시작일ㆍ종료일이 20일(계약기간 1년 이상이면 3개월) 이내로 변경되거나,
        계약금액이 최초 대비 10% 이내로 변경되는 경우</li>
    </ul>
    <p class="rule-cite">근거: 유가증권시장 공시규정 제7조제1항제1호다목 (출처:
    <a href="https://rule.krx.co.kr/out/index.do" target="_blank" class="clickable-name">KRX 법규서비스</a>).
    매출액ㆍ자산총계는 DART 연결재무제표 기준으로 매일 자동 계산되며, 사업보고서가 갱신되면 자동으로 반영됩니다.</p>`;
}

function ruleEquityHtml() {
  return `
    <p>임원ㆍ주요주주는 <b>매출액이나 금액 기준(%) 없이</b>, 소유 지분에 변동이 생길 때마다 무조건
    보고해야 합니다 — 단판공시처럼 "일정 규모 이상만" 공시하는 게 아니라 전건 대상입니다.</p>
    <div class="rule-flow">
      <div class="rule-flow-box">
        <div class="rule-flow-label">임원ㆍ주요주주가 된 날</div>
        <div class="rule-flow-value">최초 소유상황</div>
      </div>
      <div class="rule-flow-arrow">→</div>
      <div class="rule-flow-box highlight">
        <div class="rule-flow-label">보고기한</div>
        <div class="rule-flow-value">5일 이내</div>
      </div>
    </div>
    <div class="rule-flow">
      <div class="rule-flow-box">
        <div class="rule-flow-label">소유 특정증권등 변동 발생일</div>
        <div class="rule-flow-value">매수ㆍ매도ㆍ증여 등</div>
      </div>
      <div class="rule-flow-arrow">→</div>
      <div class="rule-flow-box highlight">
        <div class="rule-flow-label">보고기한</div>
        <div class="rule-flow-value">변동일로부터 5일 이내</div>
      </div>
    </div>
    <h4>보고의무 면제</h4>
    <ul>
      <li>1회 변동수량이 <b>1,000주 미만</b>이면서 취득ㆍ처분금액이 <b>1천만원 미만</b>인 경우</li>
    </ul>
    <h4>단판공시와 차이점</h4>
    <p>이건 거래소(KRX) 공시규정이 아니라 <b>자본시장법 제173조</b>(금융위원회 소관)에 따른 의무입니다.
    그래서 매출액ㆍ자산 대비 몇 % 같은 규모 기준이 없고, "임원ㆍ주요주주 본인"이 직접 보고 주체라는
    점도 다릅니다(단판공시는 회사가 직접 공시).</p>
    <p class="rule-cite">근거: 자본시장법 제173조, 동법 시행령 제200조 (출처:
    <a href="https://www.law.go.kr" target="_blank" class="clickable-name">국가법령정보센터</a>,
    <a href="https://dart.fss.or.kr/info/main.do?menu=320" target="_blank" class="clickable-name">DART 기업공시 길라잡이</a>).</p>`;
}

function ruleFtcHtml() {
  return `
    <p>특수관계인(국외 계열회사는 제외)을 상대방으로 하거나 특수관계인을 위하여 <b>대통령령으로
    정하는 규모 이상</b>의 거래를 하려는 경우, 미리 <b>이사회 의결</b>을 거친 후 <b>공시</b>해야
    합니다 — "대규모내부거래".</p>
    <div class="rule-flow">
      <div class="rule-flow-box">
        <div class="rule-flow-label">거래금액</div>
        <div class="rule-flow-value">100억원 이상</div>
      </div>
      <div class="rule-flow-arrow">또는</div>
      <div class="rule-flow-box">
        <div class="rule-flow-label">자본총계ㆍ자본금 중 큰 금액</div>
        <div class="rule-flow-value">5% 이상(최소 5억원)</div>
      </div>
      <div class="rule-flow-arrow">→</div>
      <div class="rule-flow-box highlight">
        <div class="rule-flow-label">기준 충족 시</div>
        <div class="rule-flow-value">이사회 의결 + 공시</div>
      </div>
    </div>
    <h4>거래유형별 차이 — 상품ㆍ용역거래만 상대방 요건이 따로 있음</h4>
    <ul>
      <li><b>자금ㆍ유가증권ㆍ자산 거래</b>: 특수관계인(동일인, 동일인관련자, 동일인이 사실상 지배하는
        국내 계열회사 등 — 국외 계열회사는 제외) 상대방이면 위 금액기준으로 판단</li>
      <li><b>상품ㆍ용역 거래</b>: 위 금액기준을 충족해도, 거래상대방이 반드시
        <b>"동일인 및 동일인 친족이 발행주식총수의 20% 이상을 소유한 계열회사(A)" 또는
        "A의 상법상 50% 초과 자회사(B)"</b>인 경우에만 대상입니다. 그 외 일반 계열회사와의
        상품ㆍ용역거래는 금액이 아무리 커도 이 규정의 대상이 아닙니다.</li>
    </ul>
    <h4>거래금액 산정 기준</h4>
    <ul>
      <li>자금ㆍ유가증권ㆍ자산: 실제 거래금액 (담보제공은 담보한도액, 부동산임대차는
        연간임대료+환산 보증금)</li>
      <li>상품ㆍ용역: <b>분기에 이루어질 매출ㆍ매입 거래금액의 합계액</b>(부가세 제외)</li>
    </ul>
    <h4>공시시기</h4>
    <p>이사회 의결 후 <b>상장법인 3영업일 이내</b>, 비상장법인ㆍ공익법인은 7영업일 이내 공시.</p>
    <p class="rule-cite">근거: 독점규제 및 공정거래에 관한 법률 제26조, 동법 시행령 제33조,
    공정위 고시 "대규모내부거래 등에 대한 이사회 의결 및 공시에 관한 규정" (출처:
    <a href="https://www.law.go.kr" target="_blank" class="clickable-name">국가법령정보센터</a>,
    <a href="https://www.ftc.go.kr" target="_blank" class="clickable-name">공정거래위원회</a>).</p>`;
}

function ruleLargeHoldingHtml() {
  return `
    <p>발행주식 등의 <b>5% 이상</b>을 보유하게 된 자는 그 날로부터 <b>5영업일 이내</b>에 보유상황을
    보고해야 합니다("5% Rule"). 이후 보유비율이 <b>1%포인트 이상</b> 변동하거나, 보유 목적ㆍ
    주요계약내용이 바뀌는 경우에도 같은 기한 내에 다시 보고해야 합니다.</p>
    <div class="rule-flow">
      <div class="rule-flow-box">
        <div class="rule-flow-label">발행주식 등의 보유비율</div>
        <div class="rule-flow-value">5% 이상 도달</div>
      </div>
      <div class="rule-flow-arrow">→</div>
      <div class="rule-flow-box highlight">
        <div class="rule-flow-label">신규보고 기한</div>
        <div class="rule-flow-value">5영업일 이내</div>
      </div>
    </div>
    <div class="rule-flow">
      <div class="rule-flow-box">
        <div class="rule-flow-label">보유비율 변동</div>
        <div class="rule-flow-value">1%p 이상 증감</div>
      </div>
      <div class="rule-flow-arrow">→</div>
      <div class="rule-flow-box highlight">
        <div class="rule-flow-label">변동보고 기한</div>
        <div class="rule-flow-value">5영업일 이내</div>
      </div>
    </div>
    <h4>"연명보고"(공동보고)</h4>
    <p>본인(보고자)뿐 아니라 계열회사ㆍ공동보유자ㆍ임원 등 <b>특별관계자</b>의 보유분까지 합산해서
    기준을 판단하며, 보고서 한 건 안에 "보고자 및 특별관계자별 보유내역" 표로 각자의 보유수량을
    함께 신고합니다. 그래서 이 표는 회사당 신고자가 여러 명(법인 포함)일 수 있습니다.</p>
    <h4>임원ㆍ주요주주 소유상황보고와 차이점</h4>
    <p>임원ㆍ주요주주 소유상황보고(자본시장법 제173조)는 지분율과 무관하게 임원ㆍ주요주주 본인이
    변동 건마다 개별 보고하는 제도이고, 대량보유상황보고(제147조)는 <b>5% 이상 보유자</b>(특별관계자
    포함 합산 기준)가 대상이라는 점이 다릅니다. 동일인이 두 제도 모두에 해당해 이중으로 보고되는
    경우도 있습니다(예: 최대주주가 임원을 겸하는 경우).</p>
    <p class="rule-cite">근거: 자본시장법 제147조, 동법 시행령 제153조 (출처:
    <a href="https://www.law.go.kr" target="_blank" class="clickable-name">국가법령정보센터</a>,
    <a href="https://dart.fss.or.kr/info/main.do?menu=320" target="_blank" class="clickable-name">DART 기업공시 길라잡이</a>).</p>`;
}

// ── 단판공시 대상여부 사전검증 계산기 ────────────────────────────
async function runDanpanCheck() {
  const dateInput = document.getElementById('checkContractDate');
  const amountInput = document.getElementById('checkAmount');
  const result = document.getElementById('checkResult');
  if (!result) return;

  const contractDate = dateInput?.value;
  const amount = amountInput?.value?.replace(/,/g, '');
  if (!contractDate || amount === '' || amount == null) {
    result.innerHTML = '<p class="check-error">계약(예정)일자와 계약금액을 모두 입력해주세요.</p>';
    return;
  }

  result.innerHTML = '<p class="info">판단하는 중…</p>';
  try {
    const resp = await fetch(`${API_BASE}?section=danpan_check&contract_date=${encodeURIComponent(contractDate)}&amount=${encodeURIComponent(amount)}`);
    const data = await resp.json();
    if (!resp.ok) {
      result.innerHTML = `<p class="check-error">${escapeAttr(data.error ?? `조회 실패 (HTTP ${resp.status})`)}</p>`;
      return;
    }
    result.innerHTML = renderDanpanCheckResult(data);
  } catch (err) {
    result.innerHTML = `<p class="check-error">조회 실패: ${escapeAttr(err.message)}</p>`;
  }
}

function renderDanpanCheckResult(r) {
  const verdictClass = r.is_disclosure_required ? 'required' : 'not-required';
  const verdictText = r.is_disclosure_required
    ? '공시 대상입니다 — 계약체결(또는 해지)일 다음날까지 공시 필요'
    : '공시 대상이 아닙니다 (기준금액 미만)';
  const largeLabel = r.is_large_corp ? '대규모법인(2.5% 기준)' : '일반법인(5% 기준)';
  return `
    <div class="check-verdict ${verdictClass}">${verdictText}</div>
    <div class="check-detail">
      계약일자 <b>${r.contract_date}</b> 시점 기준 "최근 사업연도"는
      <b>${r.applicable_fiscal_year}년</b>입니다 (근거: <b>${escapeAttr(r.applicable_report_nm ?? '')}</b>,
      ${r.applicable_report_date} 제출) — 오늘 기준 최신 매출액이 아니라 그 계약 시점에 실제로
      참조 가능했던 매출액입니다.<br>
      ${r.applicable_fiscal_year}년 연결 매출액 <b>${fmtWon(r.revenue)}원</b> × ${largeLabel}
      <b>${(r.threshold_pct * 100).toFixed(1)}%</b> = 기준금액 <b>${fmtWon(r.threshold_amount)}원</b><br>
      입력하신 계약금액(부가세 포함) <b>${fmtWon(r.amount)}원</b>과 비교한 결과입니다.
    </div>`;
}

function renderAll() {
  if (lastData.exchange) renderExchange(lastData.exchange);
  if (lastData.indices) renderIndices(lastData.indices);
  if (lastData.themes) renderThemes(lastData.themes);
  if (lastData.companies) renderTable('companies-table', lastData.companies);
  if (lastData.cement) renderTable('cement-table', lastData.cement);
}

// ── Exchange ──────────────────────────────────────────────────
function renderExchange(data) {
  const el = document.getElementById('exchangeRate');
  if (!el) return;
  const d = data[basis] ?? data.current ?? {};
  const rate = d.usd_to_krw ?? 'N/A';
  const dirClass = d.direction === 'up' ? 'up' : d.direction === 'down' ? 'down' : '';
  const change = d.change
    ? `<span class="exr-change ${dirClass}">${d.change}</span>`
    : '';
  el.innerHTML = `<span class="exr-label">USD/KRW (${BASIS_LABEL[basis]})</span><span class="exr-value ${dirClass}">${rate}</span>${change}`;
}

// ── Indices ───────────────────────────────────────────────────
function renderIndices(data) {
  renderIndexCard('kospi-index',  'KOSPI',  data.kospi);
  renderIndexCard('kosdaq-index', 'KOSDAQ', data.kosdaq);
}

function renderIndexCard(id, label, obj) {
  const el = document.getElementById(id);
  if (!el) return;
  const d = obj?.[basis] ?? obj?.current;
  if (!d || d.value === 'N/A') { el.textContent = `${label}: N/A`; return; }
  const isUp = (d.direction === '↑');
  const dirClass = d.direction ? (isUp ? 'up' : 'down') : '';
  el.innerHTML = `
    <div class="idx-name">${label}</div>
    <div class="idx-value ${dirClass}">${d.value ?? 'N/A'}</div>
    <div class="idx-detail">${d.detail ?? ''}</div>`;
}

// ── Themes ────────────────────────────────────────────────────
function renderThemes(data) {
  const grid = document.getElementById('themes-grid');
  if (!grid) return;
  grid.innerHTML = '';
  if (!Array.isArray(data)) return;
  data.forEach(({ name, change }) => {
    const isUp = String(change).includes('↑');
    const isDown = String(change).includes('↓');
    const cls = isUp ? 'up' : isDown ? 'down' : '';
    const card = document.createElement('div');
    card.className = 'card theme-card';
    card.innerHTML = `<div class="theme-name">${name}</div><div class="theme-change ${cls}">${change}</div>`;
    grid.appendChild(card);
  });
}

// ── Generic Table ─────────────────────────────────────────────
function renderTable(tableId, list) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  if (!tbody) return;
  tbody.innerHTML = '';
  if (!Array.isArray(list)) { tbody.innerHTML = '<tr><td colspan="10">데이터 없음</td></tr>'; return; }
  list.forEach(item => {
    const b = item[basis] ?? item.current ?? {};
    const changeRate = b.change_rate ?? '';
    const isUp   = changeRate.includes('+') && !changeRate.includes('-');
    const isDown = changeRate.startsWith('-');
    const rateClass = isUp ? 'up' : isDown ? 'down' : '';
    const name = item.display_name ?? item.name ?? '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="clickable-name" onclick="showInvestorModal('${item.ticker ?? ''}', '${name}')">${name}</span></td>
      <td class="num">${item.shares ?? ''}</td>
      <td class="num">${item.capital_billion ?? ''}</td>
      <td class="num">${item.price_prev_year ?? ''}</td>
      <td class="num">${b.price ?? ''}</td>
      <td class="num">${item.marketcap_prev ?? ''}</td>
      <td class="num">${b.marketcap ?? ''}</td>
      <td class="num ${rateClass}">${changeRate}</td>
      <td class="num">${item.high_52w ?? ''}</td>
      <td class="num">${item.low_52w ?? ''}</td>`;
    tbody.appendChild(tr);
  });
}

// ── 수급 동향 모달 ────────────────────────────────────────────
function netClass(val) {
  const n = Number(String(val ?? '').replace(/,/g, ''));
  if (Number.isNaN(n)) return '';
  return n > 0 ? 'up' : n < 0 ? 'down' : '';
}

async function showInvestorModal(code, name) {
  const overlay = document.getElementById('investorModalOverlay');
  const title = document.getElementById('investorModalTitle');
  const tbody = document.querySelector('#investorModalTable tbody');
  if (!overlay || !tbody) return;

  if (title) title.textContent = `${name} 수급 동향 (최근 5일)`;
  tbody.innerHTML = '<tr><td colspan="7">로딩 중…</td></tr>';
  overlay.classList.add('show');

  if (!code) {
    tbody.innerHTML = '<tr><td colspan="7">종목코드 없음</td></tr>';
    return;
  }

  try {
    const data = await safeFetch(`${API_BASE}?section=investor_detail&code=${code}`);
    if (!Array.isArray(data) || data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = '';
    data.forEach(d => {
      const rateClass = String(d.change_rate ?? '').startsWith('-') ? 'down'
        : String(d.change_rate ?? '').includes('+') ? 'up' : '';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${d.date ?? ''}</td>
        <td class="num">${d.close ?? ''}</td>
        <td class="num ${rateClass}">${d.change_rate ?? ''}</td>
        <td class="num">${d.total_value ?? ''}</td>
        <td class="num ${netClass(d.individual)}">${d.individual ?? ''}</td>
        <td class="num ${netClass(d.institution)}">${d.institution ?? ''}</td>
        <td class="num ${netClass(d.foreign)}">${d.foreign ?? ''}</td>`;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7">조회 실패: ${err.message}</td></tr>`;
  }
}

function closeInvestorModal() {
  document.getElementById('investorModalOverlay')?.classList.remove('show');
}
