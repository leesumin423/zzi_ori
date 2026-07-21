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
let lastData = { exchange: null, indices: null, companies: null, cement: null, danpan: null, equity: null, large_holding: null, ftc: null, subsidiaryCapital: null, goodsServicesTargets: null };

// 포털형 공시현황 요약 — 지금은 동양(주) 하나만 실제로 연동돼 있어 계열사
// 선택 없이 바로 보여준다. 카드를 눌러 유형별로 필터링하는 상태만 관리한다.
let portalFilterType = null; // null이면 전체

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
        const activeDisclosure = document.querySelector('#disclosureTabs .tab-btn.active')?.dataset.disclosure ?? 'summary';
        if (activeDisclosure === 'summary') loadPortalOverview();
        if (activeDisclosure === 'danpan' && !lastData.danpan) loadDanpan();
        if (activeDisclosure === 'ftc' && !lastData.ftc) loadFtc();
        if (activeDisclosure === 'ftc' && !lastData.subsidiaryCapital) loadSubsidiaryCapital();
        if (activeDisclosure === 'ftc' && !lastData.goodsServicesTargets) loadGoodsServicesTargets();
        if (activeDisclosure === 'equity') loadActiveEquitySub();
      }
    });
  });
  document.querySelectorAll('#disclosureTabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#disclosureTabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      const kind = btn.dataset.disclosure;
      document.getElementById('disclosure-summary').style.display = kind === 'summary' ? '' : 'none';
      document.getElementById('disclosure-danpan').style.display = kind === 'danpan' ? '' : 'none';
      document.getElementById('disclosure-ftc').style.display = kind === 'ftc' ? '' : 'none';
      document.getElementById('disclosure-equity').style.display = kind === 'equity' ? '' : 'none';
      if (kind === 'summary') loadPortalOverview();
      if (kind === 'danpan' && !lastData.danpan) loadDanpan();
      if (kind === 'ftc' && !lastData.ftc) loadFtc();
      if (kind === 'ftc' && !lastData.subsidiaryCapital) loadSubsidiaryCapital();
      if (kind === 'ftc' && !lastData.goodsServicesTargets) loadGoodsServicesTargets();
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
  document.querySelectorAll('.rule-btn[data-rule]').forEach(btn => {
    btn.addEventListener('click', () => showRuleModal(btn.dataset.rule));
  });
  document.getElementById('ruleModalClose')?.addEventListener('click', closeRuleModal);
  document.getElementById('ruleModalOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'ruleModalOverlay') closeRuleModal();
  });
  document.querySelectorAll('.rule-btn[data-guide]').forEach(btn => {
    btn.addEventListener('click', () => showGuideModal(btn.dataset.guide));
  });
  document.getElementById('guideModalClose')?.addEventListener('click', closeGuideModal);
  document.getElementById('guideModalOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'guideModalOverlay') closeGuideModal();
  });
  document.getElementById('docRequestModalClose')?.addEventListener('click', closeDocRequestModal);
  document.getElementById('docRequestModalOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'docRequestModalOverlay') closeDocRequestModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeRuleModal(); closeGuideModal(); closeDocRequestModal(); closeTargetListModal(); }
  });
  document.getElementById('checkSubmitBtn')?.addEventListener('click', runDanpanCheck);
  attachCommaFormatting(document.getElementById('checkAmount'));

  // ── 공정위 공시(대규모내부거래) 대상여부 사전검증 ───────────────────
  document.getElementById('ftcCheckSubmitBtn')?.addEventListener('click', runFtcCheck);
  document.getElementById('ftcCheckType')?.addEventListener('change', updateFtcTargetAutoStatus);
  document.getElementById('ftcCheckCompany')?.addEventListener('change', (e) => {
    const nameLabel = document.getElementById('ftcCheckCompanyNameLabel');
    const nameInput = document.getElementById('ftcCheckCompanyName');
    const isDirect = !e.target.value;
    if (nameLabel) nameLabel.style.display = isDirect ? '' : 'none';
    if (isDirect) {
      renderFtcCompanyInfo(null);
    } else {
      if (nameInput) nameInput.value = ''; // 드롭다운으로 골랐으면 직접입력 칸은 비워 혼동 방지
      renderFtcCompanyInfo(findCapitalRecordByName(e.target.value));
    }
    updateFtcTargetAutoStatus();
  });
  document.getElementById('ftcCheckCompanyName')?.addEventListener('input', (e) => {
    // 유진 기업집단 대표회사 공시에 실린 약 70개사 전체와 자동 대조한다 —
    // "(주)"/"㈜"/"주식회사" 표기 차이, 공백은 무시하고 비교(20% 계열사
    // 목록 대조와 같은 정규화 규칙 재사용).
    renderFtcCompanyInfo(findCapitalRecordByName(e.target.value));
    updateFtcTargetAutoStatus();
  });
  attachCommaFormatting(document.getElementById('ftcCheckAmount'));
  attachCommaFormatting(document.getElementById('ftcCheckCapital'));

  // ── "20% 계열사 목록 보기" 버튼 ─────────────────────────────────
  document.querySelectorAll('[data-show-target-list]').forEach(btn => {
    btn.addEventListener('click', showTargetListModal);
  });
  document.getElementById('targetListModalClose')?.addEventListener('click', closeTargetListModal);
  document.getElementById('targetListModalOverlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'targetListModalOverlay') closeTargetListModal();
  });

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
  loadStockSnapshot();
  loadMgmtWatch();
}

// ── 관리종목지정 모니터링 (동양 보통주 / 동양우ㆍ동양2우B 우선주) ──
async function loadMgmtWatch() {
  const note = document.getElementById('mgmtWatchNote');
  const commonBody = document.querySelector('#mgmt-watch-common-table tbody');
  const preferredBody = document.querySelector('#mgmt-watch-preferred-table tbody');
  if (!commonBody || !preferredBody) return;
  try {
    const data = await safeFetch(`${API_BASE}?section=mgmt_watch`);
    if (!data.available) {
      if (note) note.textContent = data.reason || 'KRX API를 사용할 수 없습니다.';
      commonBody.innerHTML = '';
      preferredBody.innerHTML = '';
      return;
    }
    if (note) {
      note.textContent = '유가증권시장 상장규정 기준 — 보통주(제47조제1항제9호의2)는 종가 1,000원 미만, ' +
        '우선주(제64조제1항)는 시가총액 20억원 미만ㆍ반기 월평균거래량 1만주 미만 상태가 30거래일 ' +
        '지속되는지를 매매거래일 기준으로 체크합니다 (매매거래정지 기간은 매매거래일에서 제외).';
    }

    commonBody.innerHTML = data.common.map(row => {
      if (!row.has_data) {
        return `<tr><td>${row.name}</td><td colspan="3">이력 수집 중… (KRX 과거 데이터를 백필하는 동안입니다 — 새로고침 시 이어서 채워집니다)</td></tr>`;
      }
      const priceWarn = row.price_streak_days > 0;
      return `
        <tr>
          <td>${row.name} <span class="info" style="font-size:11px;">(${row.code})</span></td>
          <td>${row.latest_date ?? '--'}</td>
          <td>${row.latest_close != null ? row.latest_close.toLocaleString('ko-KR') : '--'}원</td>
          <td class="${priceWarn ? 'down' : ''}">${row.price_status}</td>
        </tr>
      `;
    }).join('');

    preferredBody.innerHTML = data.preferred.map(row => {
      if (!row.has_data) {
        return `<tr><td>${row.name}</td><td colspan="5">이력 수집 중… (KRX 과거 데이터를 백필하는 동안입니다 — 새로고침 시 이어서 채워집니다)</td></tr>`;
      }
      const capWarn = row.cap_streak_days > 0;
      const volWarn = row.volume_status === '미달 우려';
      const mktcapEok = row.latest_mktcap != null ? Math.round(row.latest_mktcap / 100000000).toLocaleString('ko-KR') : '--';
      const volAvg = row.volume_avg_monthly != null ? row.volume_avg_monthly.toLocaleString('ko-KR') : '--';
      return `
        <tr>
          <td>${row.name} <span class="info" style="font-size:11px;">(${row.code})</span></td>
          <td>${row.latest_date ?? '--'}</td>
          <td>${mktcapEok}억원</td>
          <td class="${capWarn ? 'down' : ''}">${row.cap_status}</td>
          <td>${row.half_year_label ?? ''} ${volAvg}주 (잠정)</td>
          <td class="${volWarn ? 'down' : ''}">${row.volume_status}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    if (note) note.textContent = `관리종목 모니터링 로드 실패: ${err.message}`;
  }
}

// ── (주)동양 실시간 주가현황 위젯 (사이드바 상단) ───────────────
async function loadStockSnapshot() {
  const el = document.getElementById('stockSnapshot');
  if (!el) return;
  try {
    const d = await safeFetch(`${API_BASE}?section=company_snapshot`);
    const dirClass = d.direction === 'up' ? 'up' : d.direction === 'down' ? 'down' : '';
    const icon = d.direction === 'up' ? '↑' : d.direction === 'down' ? '↓' : '–';

    const iconEl = document.getElementById('snapshotTrendIcon');
    if (iconEl) {
      iconEl.textContent = icon;
      iconEl.className = `snapshot-trend-icon ${dirClass}`;
    }

    const priceEl = document.getElementById('snapshotPrice');
    if (priceEl) {
      priceEl.textContent = `${d.price ?? '--'}원`;
      priceEl.className = `snapshot-price ${dirClass}`;
    }

    const changeEl = document.getElementById('snapshotChange');
    if (changeEl) {
      const diff = Number(d.diff ?? 0);
      const sign = diff > 0 ? '+' : '';
      const rate = d.rate ?? 0;
      changeEl.textContent = `${sign}${diff.toLocaleString('ko-KR')}원 (${sign}${rate}%)`;
      changeEl.className = `snapshot-change ${dirClass}`;
    }

    const mcEl = document.getElementById('snapshotMarketcap');
    if (mcEl) mcEl.textContent = d.marketcap ? `${d.marketcap}억` : '--';

    const volEl = document.getElementById('snapshotVolume');
    if (volEl) volEl.textContent = d.volume ?? '--';

    const frEl = document.getElementById('snapshotForeignRatio');
    if (frEl) frEl.textContent = d.foreign_ratio ?? '--';
  } catch (err) {
    console.warn('종목 스냅샷 로드 실패:', err);
  }
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

// ── 포털형 공시현황 요약(유형별 건수 카드 + 클릭 필터) ────────────
// 뉴스ㆍ재무 카드는 빼고, 이미 서버가 갖고 있는 단판ㆍ공정위ㆍ지분(임원/대량보유)
// 공시 데이터를 유형별 건수 카드로 요약해서 보여준다. 카드를 누르면 그
// 유형의 내역만 아래 표에 필터링돼서 나온다("전체" 카드를 누르면 모두 표시).
const PORTAL_CATEGORIES = [
  { key: 'danpan', label: '단판공시', typeClass: 'type-danpan' },
  { key: 'ftc', label: '공정위공시', typeClass: 'type-ftc' },
  { key: 'equity', label: '지분공시(임원)', typeClass: 'type-equity' },
  { key: 'large_holding', label: '지분공시(대량보유)', typeClass: 'type-large_holding' },
];

async function loadPortalOverview() {
  const note = document.getElementById('portalOverviewNote');
  if (note) note.textContent = '공시현황을 불러오는 중…';
  try {
    await Promise.all([
      lastData.danpan ? null : loadDanpan(),
      lastData.ftc ? null : loadFtc(),
      lastData.equity ? null : loadEquity(),
      lastData.large_holding ? null : loadLargeHolding(),
    ]);
  } finally {
    renderPortalOverview();
  }
}

function buildPortalOverviewRows() {
  const rows = [];
  (lastData.danpan?.sites ?? []).forEach(s => rows.push({
    category: 'danpan', date: s.latest_disclosure_date,
    title: s.site_name ?? '', sub: s.counterparty ?? '', url: s.dart_url,
  }));
  (lastData.ftc?.records ?? []).forEach(r => rows.push({
    category: 'ftc', date: r.disclosure_date,
    title: r.type_label ?? '', sub: r.counterparty ?? '', url: r.dart_url,
  }));
  (lastData.equity?.records ?? []).forEach(r => rows.push({
    category: 'equity', date: r.latest_buy_date,
    title: `${r.holder_name ?? ''} 소유상황보고`, sub: r.role_label ?? '', url: r.dart_url,
  }));
  (lastData.large_holding?.records ?? []).forEach(r => rows.push({
    category: 'large_holding', date: r.latest_disclosure_date,
    title: `${r.reporter_name ?? r.holder_name ?? ''} 대량보유상황보고`, sub: r.holder_name ?? '', url: r.dart_url,
  }));
  rows.sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''));
  return rows;
}

function renderPortalSummaryCards(rows) {
  const container = document.getElementById('portalSummaryCards');
  if (!container) return;

  const countsByCategory = {};
  PORTAL_CATEGORIES.forEach(c => { countsByCategory[c.key] = 0; });
  rows.forEach(r => { countsByCategory[r.category] = (countsByCategory[r.category] ?? 0) + 1; });

  const cards = [
    { key: null, label: '전체', count: rows.length },
    ...PORTAL_CATEGORIES.map(c => ({ key: c.key, label: c.label, count: countsByCategory[c.key] ?? 0 })),
  ];

  container.innerHTML = cards.map(c => `
    <button type="button" class="portal-summary-card ${portalFilterType === c.key ? 'active' : ''}" data-filter-key="${c.key ?? ''}">
      <div class="portal-summary-card-label">${c.label}</div>
      <div class="portal-summary-card-count">${c.count}<span class="portal-summary-card-unit">건</span></div>
    </button>`).join('');

  container.querySelectorAll('.portal-summary-card').forEach(btn => {
    btn.addEventListener('click', () => {
      portalFilterType = btn.dataset.filterKey || null;
      renderPortalOverview();
    });
  });
}

function renderPortalOverview() {
  const note = document.getElementById('portalOverviewNote');
  const tbody = document.querySelector('#portal-overview-table tbody');
  if (!tbody) return;

  const rows = buildPortalOverviewRows();
  renderPortalSummaryCards(rows);

  const filtered = portalFilterType ? rows.filter(r => r.category === portalFilterType) : rows;
  const activeLabel = portalFilterType ? (PORTAL_CATEGORIES.find(c => c.key === portalFilterType)?.label ?? '') : '전체';

  if (note) {
    note.textContent = `${activeLabel} — ${filtered.length}건. 단판ㆍ공정위ㆍ지분공시를 유형별로 모았습니다 — `
      + '카드를 눌러 유형을 바꿀 수 있고, 각 유형의 세부 조건은 아래 탭에서 확인하세요.';
  }

  tbody.innerHTML = filtered.length === 0 ? '<tr><td colspan="5">데이터 없음</td></tr>' : '';
  filtered.forEach(r => {
    const category = PORTAL_CATEGORIES.find(c => c.key === r.category);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="disclosure-type-badge ${category?.typeClass ?? ''}">${category?.label ?? ''}</span></td>
      <td title="${escapeAttr(r.title)}">${r.title}</td>
      <td>${r.sub}</td>
      <td class="num">${r.date ?? ''}</td>
      <td>${r.url ? `<a href="${r.url}" target="_blank" class="clickable-name">보기</a>` : ''}</td>`;
    tbody.appendChild(tr);
  });
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

  const rangeLabel = meta.range_start ? `${meta.range_start} ~ 오늘` : '최근 1년';

  if (!Array.isArray(list) || list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10">공정위 공시 이력이 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
    if (note) {
      note.textContent = isRecent && meta.total_count_all_years > 0
        ? `${rangeLabel} 기간에는 해당 이력이 없습니다(전체 ${meta.lookback_years ?? 10}년간 ${meta.total_count_all_years}건 있음 — "전체 이력" 탭에서 확인).`
        : '';
    }
    return;
  }

  if (note) {
    note.textContent = isRecent
      ? `${rangeLabel} 기준 ${list.length}건(전년도 1월 1일부터 오늘까지 — 공정위 공시점검 등 연도 단위 자료 제출용). `
        + `특수관계인에대한출자ㆍ채권매도, 동일인등출자계열회사와의상품ㆍ용역거래(거래/변경 구분) 3종만 집계했습니다 `
        + `(대규모기업집단현황공시, 지급수단별ㆍ지급기간별지급금액및분쟁조정기구에관한사항은 범위 밖). 접수일 최신순 — `
        + `전체 ${meta.lookback_years ?? 10}년간은 총 ${meta.total_count_all_years ?? list.length}건입니다("전체 이력" 탭 참고).`
      : `최근 ${meta.lookback_years ?? 10}년간 총 ${list.length}건. 특수관계인에대한출자ㆍ채권매도, 동일인등출자계열회사와의상품ㆍ용역거래(거래/변경 구분) 3종만 `
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
      <td>${ftcTimelinessBadge(item)}</td>
      <td>${ftcReverifyBadge(item)}</td>
      <td class="num">${item.amount_label ?? ''}</td>
      <td><a href="${item.dart_url}" target="_blank" class="clickable-name">보기</a></td>`;
    tbody.appendChild(tr);
  });
}

// "공시기한"ㆍ"공시대상 재확인" 배지 — 자동 판정이 아니라 확인 필요 후보를
// 색으로 눈에 띄게 표시하는 용도(초록=정상/충족, 빨강=지연/미달, 회색=확인불가).
function ftcTimelinessBadge(item) {
  const days = item.filing_business_days;
  if (item.filing_timeliness === 'on_time') {
    return `<span class="up">✓ 준수(${days}영업일)</span>`;
  }
  if (item.filing_timeliness === 'late') {
    return `<span class="down">⚠ 지연 의심(${days}영업일)</span>`;
  }
  if (item.filing_timeliness === 'not_applicable') {
    return '<span class="rule-cite" title="변경(사후공시)은 이사회 의결 없이 분기종료 후 45일 이내에 공시하면 되므로 3영업일 규정 대상이 아닙니다.">해당없음(45일 특례)</span>';
  }
  return '<span class="rule-cite">확인불가</span>';
}

function ftcReverifyBadge(item) {
  if (item.reverify_is_required === true) return '<span class="up">✓ 충족</span>';
  if (item.reverify_is_required === false) return `<span class="down" title="${escapeAttr(item.reverify_note ?? '')}">⚠ 미달(참고)</span>`;
  return '<span class="rule-cite">확인불가</span>';
}

// ── 계열사별 자본금ㆍ자본총계(비상장 자회사 — 공정위 사전검증 계산기 드롭다운용) ──
// 별도 참고표 대신, 계산기에서 계열사를 선택하면 바로 값이 보이도록
// 드롭다운만 채우고 실제 표시는 ftcCheckCompany의 change 핸들러가 담당한다.
async function loadSubsidiaryCapital() {
  try {
    const data = await safeFetch(`${API_BASE}?section=subsidiary_capital`);
    lastData.subsidiaryCapital = data;
    renderSubsidiaryCapital(data);
  } catch (err) {
    console.warn('계열사 자본금 조회 실패:', err.message);
  }
}

function renderSubsidiaryCapital(payload) {
  const companySelect = document.getElementById('ftcCheckCompany');
  if (!companySelect) return;
  // 유진 기업집단 대표회사 공시 하나로 그룹 소속 회사 전체(약 70개사)의
  // 자본금ㆍ자본총계를 받아오지만, 드롭다운에는 재무제표를 따로 조회할 방법이
  // 없는 비상장 자회사 5개사만 노출한다 — 나머지는 "직접입력" 칸에 이름을
  // 치면 findCapitalRecordByName()이 전체 목록과 자동 대조해 채워준다.
  const list = (payload?.records ?? []).filter(r => r.is_known_subsidiary);
  const currentValue = companySelect.value;
  companySelect.innerHTML = '<option value="">직접입력</option>'
    + list.map(r => `<option value="${escapeAttr(r.name)}">${escapeAttr(r.name)}</option>`).join('');
  if (list.some(r => r.name === currentValue)) companySelect.value = currentValue;
}

// 회사명(드롭다운 선택값 또는 직접입력 텍스트)으로 자본금 데이터를 찾는다 —
// 표기 차이를 무시하는 normalizeCompanyNameForMatch()로 비교하므로 전체
// ~70개사 중 어느 이름을 쳐도(예: "동양", "유진기업 주식회사") 매칭된다.
function findCapitalRecordByName(name) {
  const target = normalizeCompanyNameForMatch(name);
  if (!target) return null;
  return (lastData.subsidiaryCapital?.records ?? []).find(r => normalizeCompanyNameForMatch(r.name) === target) ?? null;
}

function renderFtcCompanyInfo(rec) {
  const infoBox = document.getElementById('ftcCheckCompanyInfo');
  if (!infoBox) return;
  if (!rec) {
    infoBox.textContent = '계열사를 선택하거나 회사명을 입력하면 자본금ㆍ자본총계 정보가 여기 표시됩니다.';
    return;
  }
  const capitalInput = document.getElementById('ftcCheckCapital');
  if (capitalInput && rec.capital_base != null) {
    capitalInput.value = Math.round(rec.capital_base).toLocaleString('ko-KR');
  }
  const capitalTotalNote = (rec.capital_total ?? 0) < 0 ? '(자본잠식)' : '';
  const largeCoNote = rec.is_large_unlisted_co
    ? ' 자산총계가 1,000억원 이상이라 외부감사법상 대형비상장주식회사(주요사항보고서 제출대상)에도 해당할 수 있습니다.'
    : '';
  infoBox.innerHTML = `${escapeAttr(rec.name)} — 자산총계 ${fmtWon(rec.total_assets)}원 / 자본금 ${fmtWon(rec.capital)}원 / `
    + `자본총계 ${fmtWon(rec.capital_total)}원${capitalTotalNote} → 자본금ㆍ자본총계 중 큰 금액 <b>${fmtWon(rec.capital_base)}원</b>.`
    + `${largeCoNote} (<a href="${rec.dart_url}" target="_blank" class="clickable-name">원문 보기</a>)`;
}

// ── 상품ㆍ용역거래 특례 대상 회사 목록(20% 계열사 A / 그 50%초과 자회사 B) ──
// 유진 기업집단 대표회사(유진기업㈜)의 "기업집단현황공시" 소유지분현황을
// 근거로 계산한 실제 대상 회사 27개. 계산기에서 고른(또는 직접 입력한)
// 회사명을 이 목록과 자동 대조해 "거래상대방 요건"을 판정하고, 참고용으로
// "20% 계열사 목록 보기" 버튼을 누르면 전체를 모달로도 볼 수 있다.
async function loadGoodsServicesTargets() {
  try {
    const data = await safeFetch(`${API_BASE}?section=goods_services_targets`);
    lastData.goodsServicesTargets = data;
  } catch (err) {
    console.warn('20% 계열사 목록 조회 실패:', err.message);
  }
}

// "(주)"/"㈜"/"주식회사"/공백 표기 차이를 무시하고 두 회사명이 같은
// 법인을 가리키는지 비교한다.
function normalizeCompanyNameForMatch(name) {
  return (name || '').replace(/\(주\)|㈜|주식회사/g, '').replace(/\s+/g, '').trim();
}

function isKnownGoodsServicesTarget(name) {
  const target = normalizeCompanyNameForMatch(name);
  if (!target) return false;
  const companies = lastData.goodsServicesTargets?.companies ?? [];
  return companies.some(c => normalizeCompanyNameForMatch(c) === target);
}

// 계열사 드롭다운에서 골랐으면 그 이름을, "직접입력"이면 텍스트 입력값을 쓴다.
function getSelectedFtcCompanyName() {
  const select = document.getElementById('ftcCheckCompany');
  if (select?.value) return select.value;
  return document.getElementById('ftcCheckCompanyName')?.value?.trim() ?? '';
}

// 거래유형이 상품ㆍ용역거래일 때, 현재 선택/입력된 회사명을 20% 계열사
// 목록과 자동 대조해 체크박스와 안내문을 갱신한다.
function updateFtcTargetAutoStatus() {
  const isGoods = document.getElementById('ftcCheckType')?.value === 'goods_services';
  const label = document.getElementById('ftcCheckTargetLabel');
  const noteEl = document.getElementById('ftcCheckTargetAutoNote');
  const checkbox = document.getElementById('ftcCheckTarget');
  if (label) label.style.display = isGoods ? '' : 'none';
  if (!isGoods) {
    if (noteEl) noteEl.style.display = 'none';
    return;
  }
  const name = getSelectedFtcCompanyName();
  const matched = isKnownGoodsServicesTarget(name);
  if (checkbox) checkbox.checked = matched;
  if (noteEl) {
    noteEl.style.display = '';
    noteEl.innerHTML = name
      ? (matched
          ? `<b>${escapeAttr(name)}</b>은(는) 20% 계열사 목록에 있습니다 — 거래상대방 요건이 자동으로 충족 처리됩니다.`
          : `<b>${escapeAttr(name)}</b>은(는) 20% 계열사 목록에 없습니다 — 표기 차이일 수 있으니 "20% 계열사 목록 보기"로
             확인 후 필요하면 위 체크박스를 직접 조정하세요.`)
      : '계열사를 선택하거나 회사명을 입력하면 20% 계열사 목록과 자동으로 대조합니다.';
  }
}

function showTargetListModal() {
  const overlay = document.getElementById('targetListModalOverlay');
  const body = document.getElementById('targetListModalBody');
  if (!overlay || !body) return;
  const info = lastData.goodsServicesTargets;
  const companies = info?.companies ?? [];

  body.innerHTML = companies.length === 0
    ? '<p class="info">아직 목록을 불러오지 못했습니다 — "공정위공시" 탭을 한 번 열어보세요.</p>'
    : `<p class="info">유진 기업집단 대표회사(유진기업㈜)가 매년 내는 "기업집단현황공시"의 "(1) 소유지분현황"
        표를 근거로 계산한 실제 대상 회사입니다 — 동일인 지분+친족 합계 지분이 20% 이상인 회사(A), 그리고
        A(또는 이미 확정된 자회사)가 50% 초과 보유한 계열회사를 상법 제342조의2에 따라 손자회사까지 사슬로
        확장(B)해서 구했습니다(기준일 ${info.disclosure_date ?? ''},
        <a href="${info.dart_url}" target="_blank" class="clickable-name">원문 보기</a>).</p>
      <ul class="doc-request-list">${companies.map(name => `<li>${escapeAttr(name)}</li>`).join('')}</ul>
      <p class="rule-cite">총 ${companies.length}개사. 계산기의 "계열사 선택ㆍ회사명 입력"란과 자동으로 대조됩니다.</p>`;
  overlay.classList.add('show');
}

function closeTargetListModal() {
  document.getElementById('targetListModalOverlay')?.classList.remove('show');
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
    // 상품ㆍ용역거래: 회사명이 20% 계열사 목록에 있으면 자동으로 대상 처리,
    // 없으면(또는 표기 차이로 못 찾으면) 체크박스의 직접 판단을 따른다.
    const name = getSelectedFtcCompanyName();
    const isTarget = transactionType === 'goods_services'
      ? (isKnownGoodsServicesTarget(name) || targetCheckbox?.checked ? '1' : '0')
      : '1';
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
  const verdictText = r.is_disclosure_required ? '공시 대상입니다' : '공시대상이 아닙니다';
  const checkMark = (ok) => ok ? '<span class="up">✓ 충족</span>' : '<span class="down">✗ 미충족</span>';
  const typeLabel = r.transaction_type === 'goods_services' ? '상품ㆍ용역 거래' : '자금ㆍ유가증권ㆍ자산 거래';

  let targetRow = '';
  if (r.transaction_type === 'goods_services') {
    // is_goods_services_target=false로 판단이 끝난 경우만 reason에 "해당하지 않아"가 들어있음
    const failedTarget = r.reason.includes('해당하지 않아');
    targetRow = `<li>거래상대방 요건("동일인·동일인 친족 20%이상 출자 계열회사 또는 그 50%초과 자회사"): ${checkMark(!failedTarget)}</li>`;
  }

  const deadlineNote = r.is_disclosure_required
    ? `<p class="check-reason" style="border-left-color: #f87171;">이사회 의결일로부터 <b>상장법인은 3영업일 이내</b>,
        <b>비상장법인ㆍ공익법인은 7영업일 이내</b>에 공시해야 합니다 — 기한을 넘기면 그 자체로 별도의 공시위반입니다.</p>`
    : '';

  return `
    <div class="check-verdict ${verdictClass}">${verdictText}</div>
    <p class="info">거래유형: <b>${typeLabel}</b></p>
    <ul class="info" style="margin:4px 0 8px; padding-left:20px;">
      <li>거래금액 100억원 이상: ${checkMark(r.amount_ge_100eok)}</li>
      <li>자본총계ㆍ자본금 중 큰 금액의 5%(최소 5억원) 이상: ${checkMark(r.amount_ge_capital_pct)}</li>
      ${targetRow}
    </ul>
    <p class="check-reason">판단근거: ${escapeAttr(r.reason)}</p>
    <p class="info">기준금액(자본총계ㆍ자본금 중 큰 금액의 5%, 최소 5억원): <b>${fmtWon(r.threshold_amount)}원</b></p>
    ${deadlineNote}`;
}

// 지분공시 탭 안에는 임원ㆍ주요주주(officer) / 대량보유상황보고서(large_holding)
// 두 하위 탭이 있다 — 현재 선택된 쪽만, 아직 안 불러왔으면 불러온다.
function loadActiveEquitySub() {
  const sub = document.querySelector('#equitySubTabs .tab-btn.active')?.dataset.equitySub ?? 'officer';
  if (sub === 'officer' && !lastData.equity) loadEquity();
  if (sub === 'officer' && !lastData.equityAccuracy) loadEquityAccuracy();
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
    tbody.innerHTML = '<tr><td colspan="9">매수 이력이 있는 지분공시가 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
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
      <td><a href="${item.dart_url}" target="_blank" class="clickable-name">보기</a></td>
      <td><button type="button" class="doc-request-btn">${item.latest_report_type || '변동'} 서류</button></td>`;
    const docBtn = tr.querySelector('.doc-request-btn');
    if (docBtn) {
      docBtn.addEventListener('click', () => showDocRequestModal(
        holderName, item.latest_rcept_no ?? item.rcept_no, item.latest_report_type ?? '변동', item.required_documents ?? [],
      ));
    }
    tbody.appendChild(tr);
  });
}

// ── 지분공시 정확성 점검(임원 선임일ㆍ발행주식총수ㆍ주식 수) ──────
async function loadEquityAccuracy() {
  const note = document.getElementById('equityAccuracyNote');
  if (note) note.textContent = '대조하는 중…';
  try {
    const data = await safeFetch(`${API_BASE}?section=equity_accuracy`);
    lastData.equityAccuracy = data;
    renderEquityAccuracy(data);
  } catch (err) {
    if (note) note.textContent = `조회 실패: ${err.message}`;
  }
}

function renderEquityAccuracy(payload) {
  const note = document.getElementById('equityAccuracyNote');
  const sharesTbody = document.querySelector('#equity-accuracy-shares-table tbody');
  const conflictsBox = document.getElementById('equity-accuracy-shares-conflicts');
  const officerBox = document.getElementById('equity-accuracy-officer-issues');
  const shareCountBox = document.getElementById('equity-accuracy-share-count-issues');
  if (!payload) return;

  const shares = payload.issued_shares_total ?? {};
  const officerIssues = payload.officer_appointment_issues ?? [];
  const shareCountIssues = payload.share_count_issues ?? [];

  if (note) {
    note.textContent = '지분공시 보고서 원문 안에서, 보고서 간 대조로 잡아낼 수 있는 불일치만 추려서 보여줍니다 — '
      + '자동 판정은 아니므로 아래 항목은 반드시 사람이 다시 확인해야 합니다.';
  }

  if (sharesTbody) {
    sharesTbody.innerHTML = '';
    const timeline = shares.timeline ?? [];
    if (timeline.length === 0) {
      sharesTbody.innerHTML = '<tr><td colspan="3">데이터 없음</td></tr>';
    } else {
      timeline.forEach(pt => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="num">${pt.date ?? ''}</td>
          <td class="num">${fmtWon(pt.value)}</td>
          <td><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${pt.rcept_no}" target="_blank" class="clickable-name">보기</a></td>`;
        sharesTbody.appendChild(tr);
      });
    }
  }

  if (conflictsBox) {
    const conflicts = shares.same_day_conflicts ?? [];
    conflictsBox.innerHTML = conflicts.length === 0
      ? '<p class="info">같은 날짜에 서로 다른 발행주식총수가 보고된 경우는 없습니다.</p>'
      : `<ul class="guide-notes">${conflicts.map((c, i) => `<li data-n="${i + 1}">${c.date}에 서로 다른 값이 보고됨: ${c.values.map(v => fmtWon(v)).join(' / ')}</li>`).join('')}</ul>`;
  }

  if (officerBox) {
    officerBox.innerHTML = officerIssues.length === 0
      ? '<p class="info">임원 선임일이 보고서마다 다르게 기재된 사례는 없습니다.</p>'
      : `<ul class="guide-notes">${officerIssues.map((it, i) => `
          <li data-n="${i + 1}">
            <b>${escapeAttr(it.holder_name)}</b> — 보고서마다 선임일이 다르게 기재됨
            <ul class="doc-request-list" style="margin-top:6px;">
              ${(it.variants ?? []).map(v => `
                <li>
                  선임일 <b>${escapeAttr(v.value)}</b>:
                  ${(v.rcept_nos ?? []).map(no => `<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${no}" target="_blank" class="clickable-name">보기</a>`).join(' ')}
                </li>`).join('')}
            </ul>
          </li>`).join('')}</ul>`;
  }

  if (shareCountBox) {
    shareCountBox.innerHTML = shareCountIssues.length === 0
      ? '<p class="info">주식 수 산식(직전+증감=이번) 및 보고서 간 연결에 어긋난 사례는 없습니다.</p>'
      : `<ul class="guide-notes">${shareCountIssues.map((it, i) => `<li data-n="${i + 1}"><b>${escapeAttr(it.holder_name)}</b> — ${escapeAttr(it.detail)}</li>`).join('')}</ul>`;
  }
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

// ── 공시 작성 가이드 모달(서식ㆍ기재상 유의사항ㆍ관련법규) ───────────
function showGuideModal(kind) {
  const overlay = document.getElementById('guideModalOverlay');
  const title = document.getElementById('guideModalTitle');
  const body = document.getElementById('guideModalBody');
  if (!overlay || !body) return;

  const GUIDES = {
    danpan: { label: '단판공시 — 단일판매ㆍ공급계약체결', html: guideDanpanHtml },
    equity: { label: '지분공시 — 임원ㆍ주요주주 특정증권등 소유상황보고', html: guideEquityHtml },
    large_holding: { label: '지분공시 — 주식등의 대량보유상황보고(5% Rule)', html: guideLargeHoldingHtml },
    ftc: { label: '공정위공시 — 대규모내부거래(계열회사간 거래)', html: guideFtcHtml },
  };
  const guide = GUIDES[kind];
  if (!guide) return;
  title.textContent = guide.label;
  body.innerHTML = guide.html();
  body.scrollTop = 0;

  // 모달 안에 유형별 서브탭이 있는 경우(예: 공정위공시 — 출자/채권매도/상품용역거래)
  // 탭 버튼을 누르면 그 유형의 패널만 보이도록 전환한다.
  body.querySelectorAll('.guide-subtab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.ftcSubtab;
      body.querySelectorAll('.guide-subtab-btn').forEach(b => b.classList.toggle('active', b === btn));
      body.querySelectorAll('.guide-subtab-panel').forEach(panel => {
        panel.style.display = panel.dataset.ftcPanel === key ? '' : 'none';
      });
    });
  });

  overlay.classList.add('show');
}

function closeGuideModal() {
  document.getElementById('guideModalOverlay')?.classList.remove('show');
}

// ── 요청서류 체크리스트(신규 임원 vs 변동 임원별 필요 증빙) ─────────
// 서버 DB가 따로 없는 소규모 내부툴이라, "요청함ㆍ받음" 체크 상태는 브라우저
// localStorage에 rcept_no+문서명 단위로 저장한다(팀 공유 PC 기준 — 개인 브라우저마다
// 별도로 관리됨).
function docRequestStorageKey(rcptNo, docName) {
  return `docreq_${rcptNo}_${docName}`;
}

function showDocRequestModal(holderName, rcptNo, reportType, docs) {
  const overlay = document.getElementById('docRequestModalOverlay');
  const title = document.getElementById('docRequestModalTitle');
  const body = document.getElementById('docRequestModalBody');
  if (!overlay || !body) return;

  const typeLabel = reportType === '신규' ? '신규 임원 최초 소유상황보고' : '기존 임원 변동보고';
  title.textContent = `요청서류 — ${holderName} (${typeLabel})`;
  body.innerHTML = `
    <p class="info">이 보고서(${rcptNo})를 준비ㆍ검증하려면 아래 서류를 임원 본인에게
    요청해 받아둬야 합니다. 체크 상태는 이 브라우저에 저장됩니다.</p>
    <ul class="doc-request-list">
      ${docs.map(docName => {
        const key = docRequestStorageKey(rcptNo, docName);
        const checked = localStorage.getItem(key) === '1';
        return `<li>
          <label>
            <input type="checkbox" data-doc-key="${escapeAttr(key)}" ${checked ? 'checked' : ''}>
            ${escapeAttr(docName)}
          </label>
        </li>`;
      }).join('')}
    </ul>`;
  body.querySelectorAll('input[data-doc-key]').forEach(cb => {
    cb.addEventListener('change', () => {
      if (cb.checked) localStorage.setItem(cb.dataset.docKey, '1');
      else localStorage.removeItem(cb.dataset.docKey);
    });
  });
  overlay.classList.add('show');
}

function closeDocRequestModal() {
  document.getElementById('docRequestModalOverlay')?.classList.remove('show');
}

// 법규 조문을 <details>로 접어두고 클릭하면 펼쳐지는 블록을 만든다.
function lawArticle(name, text) {
  return `<details class="law-article"><summary>${escapeAttr(name)}</summary><div class="law-article-text">${escapeAttr(text)}</div></details>`;
}

function guideFieldsHtml(fields) {
  return `<div class="guide-fields">${fields.map(f => `
    <div class="guide-field">
      <div class="guide-field-label">${escapeAttr(f.label)}</div>
      ${f.note ? `<div class="guide-field-note">${escapeAttr(f.note)}</div>` : ''}
    </div>`).join('')}</div>`;
}

function guideNotesHtml(notes) {
  return `<ul class="guide-notes">${notes.map((n, i) => `<li data-n="${i + 1}">${escapeAttr(n)}</li>`).join('')}</ul>`;
}

function guideDanpanHtml() {
  return `
    <p class="info">DART 공시서식(단일판매ㆍ공급계약체결)에 실제로 들어가는 항목과, 공시 실무 매뉴얼(유가증권시장
    공시ㆍ상장 업무해설서)의 기재상 유의사항ㆍ점검사항을 그대로 정리했습니다. 실제로 공시문을 작성할 때 이 항목들이
    빠짐없이, 정확한 기준으로 채워졌는지 이 가이드와 대조해서 확인하세요.</p>

    <h4>1. 서식에 들어가야 할 항목</h4>
    ${guideFieldsHtml([
      { label: '1. 판매ㆍ공급계약 구분', note: '체결계약명 — 무엇에 대한 계약인지 구체적으로' },
      { label: '2. 계약내역 — 계약금액(원)', note: '부가가치세(VAT) 제외 금액' },
      { label: '2. 계약내역 — 최근매출액(원) / 매출액대비(%)', note: '최근 사업연도 연결 매출액 기준' },
      { label: '2. 계약내역 — 대규모법인여부', note: '자산총액 2조원 이상이면 기준이 2.5%로 낮아짐(=신고 문턱이 낮음)' },
      { label: '3. 계약상대 / 회사와의 관계', note: '법인이면 한글명 + ( )에 영문명 병기' },
      { label: '4. 판매ㆍ공급지역', note: '' },
      { label: '5. 계약기간 — 시작일 / 종료일', note: '' },
      { label: '6. 주요 계약조건 — 계약금ㆍ선급금 유무 / 대금지급 조건 등', note: '계약서를 기준으로 작성' },
      { label: '7. 계약(수주)일자', note: '' },
      { label: '8. 공시유보 관련내용', note: '유보사유ㆍ유보기간 — 유보 시 "기타 투자판단과 관련한 중요사항"란에 투자유의 문구도 기재' },
    ])}

    <h4>2. 기재상 유의사항</h4>
    ${guideNotesHtml([
      '최근 사업연도 매출액의 100분의 5(대규모법인의 경우 1,000분의 25) 이상의 단일판매 또는 공급계약을 체결(공사수주 포함)한 때 신고한다.',
      '"계약금액"은 부가가치세를 제외한 금액을 기재한다.',
      '"공시유보관련내용"은 유보사유와 유보기간에 관한 중요사항을 기재하며, "기타 투자판단과 관련한 중요사항"란에 투자유의 안내문구를 기재한다 (예: 계약의 주요내용이 매출액이나 경영상 비밀유지 필요로 비공개되었으므로, 투자자는 계약의 변경ㆍ해지 가능성 등을 고려하여 신중히 투자하시기 바랍니다).',
      '상기 기재사항 외에 투자판단에 참고할 만한 주요사항은 "기타 투자판단과 관련한 중요사항"란에 기입식으로 작성한다.',
      '지주회사의 자회사에 관한 주요경영사항 신고인 경우 "기타 투자판단과 관련한 중요사항"란에 자회사명 및 자산총액비중을 기재한다.',
      '신고내용이 기존 공시내용과 관련이 있는 경우 "관련공시"란에 그 제목 및 일자를 기재한다.',
      '계약상대방이 법인인 경우 "명칭"란에 법인의 한글명을 기재한 후 ( ) 안에 영문명을 추가로 기재한다.',
      '주요 계약조건의 "계약금ㆍ선급금 유무"는 계약서를 기준으로 작성한다.',
    ])}

    <h4>3. 관련법규 (클릭하면 조문이 펼쳐집니다)</h4>
    ${lawArticle('유가증권시장 공시규정 제7조제1항제1호다목 (+ 제1항 본문)',
      '① 유가증권시장주권상장법인은 다음 각 호의 어느 하나에 해당하는 때에는 그 사실 또는 결정 내용을 그 사유 발생일 당일에 거래소에 신고하여야 한다. 다만, 제1호다목...에 해당하는 경우에는 사유 발생일 다음 날까지 거래소에 신고하여야 한다.\n\n1. 해당 유가증권시장주권상장법인의 영업 및 생산활동에 관한 다음 각 목의 어느 하나에 해당하는 사실 또는 결정이 있은 때\n...\n다. 최근 사업연도 매출액의 100분의 5(대규모법인의 경우 1,000분의 25) 이상의 단일판매계약 또는 공급계약을 체결한 때 및 해당 계약을 해지한 때')}
    ${lawArticle('유가증권시장 공시규정 제43조의2 (신청에 의한 공시유보)',
      '① 유가증권시장주권상장법인은 경영상 비밀유지를 위하여 필요한 경우 다음 각 호의 신고사항 중 세칙에서 정하는 사항에 대하여 공시유보를 거래소에 신청할 수 있다. 이 경우 사전에 거래소와 협의하여야 한다.\n1. 제7조제1항제1호다목\n2. 제7조제1항제2호나목(1)\n3. 제7조제1항제4호\n\n② 거래소는 제1항의 공시유보 신청에 대하여 기업 경영 등 비밀유지와 투자자 보호와의 형평을 고려하여 공시유보가 필요하다고 인정되는 경우 이를 승인할 수 있다.\n\n③ 유가증권시장주권상장법인은 제1항 및 제2항에 따라 공시가 유보된 사항에 대하여 비밀을 준수하여야 하며, 해당 유보기간이 경과하거나 유보조건이 해제되는 경우에는 그 다음날까지 이를 신고하여야 한다.')}
    ${lawArticle('유가증권시장 공시규정 시행세칙 제18조',
      '단판공시 서식이 인용하는 세부 시행세칙 조항으로, 정확한 조문 원문은 KRX 법규검색서비스(law.krx.co.kr)에서 최신본 확인이 필요합니다 — 이 항목만 자동 조회에 실패했습니다.')}

    <h4>4. 공시변경(재공시) 및 면제 기준</h4>
    <ul>
      <li><b>공시변경(재공시) 필요</b>: 계약금액이 최초 대비 <b>50% 이상</b> 변경되는 경우</li>
      <li><b>변동신고 면제</b>: 계약기간의 시작일 또는 종료일이 각각 <b>20일</b>(계약기간 1년 이상이면 <b>3개월</b>) 이내로 변경되거나, 계약금액이 최초 대비 <b>10% 이내</b>로 변경되는 경우</li>
    </ul>
    <p class="rule-cite">출처: 유가증권시장 공시ㆍ상장 업무해설서(KRX), 유가증권시장 공시규정ㆍ시행세칙, DART 공시서식.</p>`;
}

function guideEquityHtml() {
  return `
    <p class="info">DART 기업공시 길라잡이(임원ㆍ주요주주 특정증권등 소유상황보고)의 보고의무자ㆍ보고기한ㆍ면제기준과
    관련법규를 정리했습니다.</p>

    <h4>1. 보고의무자</h4>
    <ul>
      <li><b>임원</b>: 이사(사외이사 포함), 감사, 사실상 임원(상법상 업무집행지시자ㆍ집행임원 포함)</li>
      <li><b>주요주주</b>: 의결권 있는 발행주식 총수의 10% 이상을 소유한 자, 또는 주요 경영사항에 사실상 영향력을
        행사하는 주주</li>
    </ul>

    <h4>2. 서식에 들어가야 할 항목</h4>
    ${guideFieldsHtml([
      { label: '보고자 (성명/명칭)', note: '' },
      { label: '등기임원 여부 / 직위', note: '사내이사ㆍ사외이사ㆍ미등기 구분' },
      { label: '주요주주 여부', note: '' },
      { label: '세부변동내역 — 보고사유', note: '장내매수ㆍ장외매도ㆍ증여ㆍ신규보고 등' },
      { label: '세부변동내역 — 변동일 / 증권종류', note: '보통주ㆍ우선주 등 구분' },
      { label: '세부변동내역 — 변동수량 / 변동후 수량', note: '' },
      { label: '세부변동내역 — 취득ㆍ처분단가', note: '' },
    ])}

    <h4>3. 기재상 유의사항 / 보고기한</h4>
    ${guideNotesHtml([
      '임원ㆍ주요주주가 된 날 또는 소유상황에 변동이 있는 날부터 5영업일 이내(토요일ㆍ공휴일 제외)에 보고한다.',
      '변동수량이 1,000주 미만이고 취득ㆍ처분금액이 1천만원 미만인 경우 변동보고 의무가 면제된다 — 단, 신규보고는 이 면제사유가 없다.',
      '누적 변동수량이 1,000주 이상이거나 누적 금액이 1천만원 이상이 되면 그 시점에 보고의무가 발생한다.',
      '보유비율 변동이 없어도 특정증권등의 종류가 바뀌면(예: 전환사채의 주식전환) 변동보고가 필요하다.',
      '당일 동종ㆍ동량을 매도 후 매수하는 경우에도 변동보고 의무가 발생한다.',
      '"누구의 명의로 하든지 자기의 계산으로" 소유하는 증권만 보고 대상이다 — 특별관계자 개념은 이 보고에는 적용되지 않는다(대량보유상황보고와 다른 점).',
    ])}

    <h4>4. 관련법규 (클릭하면 조문이 펼쳐집니다)</h4>
    ${lawArticle('자본시장법 제173조(임원 등의 특정증권등 소유상황 보고) 제1항',
      '주권상장법인의 임원 또는 주요주주는 임원 또는 주요주주가 된 날부터 5일(대통령령으로 정하는 날은 산입하지 아니한다) 이내에 누구의 명의로 하든지 자기의 계산으로 소유하고 있는 특정증권등의 소유상황을, 그 특정증권등의 소유상황에 변동이 있는 경우(대통령령으로 정하는 경미한 소유상황의 변동은 제외한다)에는 그 변동이 있는 날부터 5일까지 그 내용을 대통령령으로 정하는 방법에 따라 각각 증권선물위원회와 거래소에 보고하여야 한다.\n\n이 경우 대통령령으로 정하는 부득이한 사유에 따라 특정증권등의 소유상황에 변동이 있는 경우와 전문투자자 중 대통령령으로 정하는 자에 대하여는 그 보고 내용 및 시기를 대통령령으로 달리 정할 수 있다.')}

    <h4>5. 위반 시 제재</h4>
    <ul>
      <li>허위보고ㆍ미보고: 1년 이하 징역 또는 3천만원 이하 벌금</li>
      <li>조사요구 불응: 3년 이하 징역 또는 1억원 이하 벌금</li>
      <li>그 외 시정명령ㆍ고발ㆍ경고ㆍ주의 등 행정조치 가능</li>
    </ul>
    <p class="rule-cite">출처: DART 기업공시 길라잡이(dart.fss.or.kr/info/main.do?menu=320), 자본시장법 제173조ㆍ동법 시행령 제200조.</p>`;
}

function guideLargeHoldingHtml() {
  return `
    <p class="info">DART 기업공시 길라잡이(주식등의 대량보유상황보고, "5% Rule")의 보고의무자ㆍ보고서 구조ㆍ면제기준과
    관련법규를 정리했습니다.</p>

    <h4>1. 보고의무자 / 연명보고</h4>
    <p>본인과 특별관계자(특수관계인 + 공동보유자) 합산 보유비율이 <b>5% 이상</b>인 자. 보유 주식수가 많은 자를
    대표보고자로 선정해 <b>연명보고</b>할 수 있다 — 그래서 보고서 1건 안에 "보고자 및 특별관계자별 보유내역" 표로
    여러 명(법인 포함)의 보유수량이 함께 신고된다.</p>

    <h4>2. 서식에 들어가야 할 항목</h4>
    ${guideFieldsHtml([
      { label: '보고구분', note: '신규보고 / 변동보고 / 변경보고' },
      { label: '보유목적', note: '경영권 영향 목적(일반서식) 또는 단순ㆍ일반투자 목적(약식서식) — 서식 자체가 달라짐' },
      { label: '보고자 및 특별관계자별 보유내역', note: '관계(보고자/특별관계자), 성명(명칭), 보유주식수, 비율' },
      { label: '보유형태', note: '소유↔보유 — 경영권 영향 목적 서식에만 기재' },
      { label: '주요계약', note: '신탁ㆍ담보ㆍ대차ㆍ콜옵션 등 — 단순투자 목적은 기재 면제' },
      { label: '변동/변경 사유', note: '' },
    ])}

    <h4>3. 기재상 유의사항 / 보고기한</h4>
    ${guideNotesHtml([
      '보고의무 발생일(5% 도달일 또는 1%p 이상 변동일) 다음날부터 5영업일 이내 보고한다.',
      '단순투자 목적의 변동보고는 다음달 10일까지, 일반투자 목적은 10영업일 이내로 기한이 다르다.',
      '경영참가 목적으로 5% 이상을 새로 취득한 경우, 보고 후 5일까지 추가취득ㆍ의결권 행사가 금지된다(냉각기간).',
      '신규보고는 면제사유가 없다 — 5%에 도달하면 반드시 보고해야 한다.',
      '변동보고는 주주배정 유상증자ㆍ자본감소 등으로 인한 비율 변동, 단순투자 목적의 보유형태ㆍ주요계약 변경 등에서 면제될 수 있다.',
      '특별관계자를 추가하거나 제외하는 경우, 그로 인한 비율 변동이 1% 미만이어도 보고 의무가 발생한다.',
    ])}

    <h4>4. 관련법규 (클릭하면 조문이 펼쳐집니다)</h4>
    ${lawArticle('자본시장법 제147조(주식등의 대량보유 등의 보고) 제1항 요지',
      '주권상장법인의 주식등을 대량보유(본인과 그 특별관계자가 보유하는 주식등의 수의 합계가 그 주식등의 총수의 100분의 5 이상인 경우)하게 된 자는 그 날부터 5일 이내에 그 보유상황, 보유 목적(발행인의 경영권에 영향을 주기 위한 것인지 여부를 포함한다) 등을 대통령령으로 정하는 바에 따라 금융위원회와 거래소에 보고하여야 한다. 그 보유 주식등의 수의 합계가 그 주식등의 총수의 100분의 1 이상 변동된 경우에도 또한 같다.')}

    <h4>5. 위반 시 제재</h4>
    <ul>
      <li>행정처분: 거래정지ㆍ금지, 임원해임 권고, 고발</li>
      <li>형사처벌ㆍ과징금: 미보고, 허위ㆍ누락 기재 — 2025.7.22. 이후 과징금 부과한도가 10배 상향(시가총액의 1만분의1)</li>
    </ul>
    <p class="rule-cite">출처: DART 기업공시 길라잡이(dart.fss.or.kr/info/main.do?menu=310), 자본시장법 제147조ㆍ동법 시행령 제139~155조ㆍ시행규칙 제17조.</p>`;
}

function guideFtcHtml() {
  return `
    <p class="info">공정거래위원회가 배포한 공식 매뉴얼 "대규모내부거래 등에 대한 이사회 의결 및 공시 업무 매뉴얼"
    (2025. 4. 21.)의 서식 항목ㆍ법규 원문을 그대로 옮겼습니다. 아래 탭에서 유형을 골라 서식을 확인하세요 —
    <b>특수관계인에대한출자</b>ㆍ<b>특수관계인에대한채권매도</b>ㆍ<b>동일인등출자계열회사와의상품ㆍ용역거래</b>는
    서식 항목이 서로 다릅니다.</p>

    <h4>공통 판단기준 — 100억원 또는 자본총계ㆍ자본금 5% 이상 (3개 유형 공통)</h4>
    ${lawArticle('독점규제 및 공정거래에 관한 법률 제26조(대규모내부거래의 이사회 의결 및 공시) 제1항',
      '다음 각 호의 어느 하나에 해당하는 거래행위(이하 "대규모내부거래"라 한다)를 하려는 공시대상기업집단에 속하는 국내 회사는 특수관계인(국외 계열회사는 제외한다)을 상대방으로 하거나 특수관계인을 위하여 미리 이사회의 의결을 거친 후 이를 공시하여야 한다.\n1. 가지급금 또는 대여금 등의 자금을 제공 또는 거래하는 행위\n2. 주식 또는 회사채 등의 유가증권을 제공 또는 거래하는 행위\n3. 부동산 또는 무체재산권 등의 자산을 제공 또는 거래하는 행위\n4. 주주의 구성 등을 고려하여 대통령령으로 정하는 계열회사를 상대방으로 하거나 그 계열회사를 위하여 상품 또는 용역을 제공 또는 거래하는 행위')}
    ${lawArticle('같은 법 시행령 제33조(대규모내부거래의 이사회 의결 및 공시) 제1항',
      '법 제26조제1항 각 호에 따른 거래행위의 규모는 그 거래금액(같은 항 제4호의 경우에는 분기에 이루어질 거래금액의 합계액을 말한다)이 100억원 이상이거나 그 회사의 자본총계 또는 자본금 중 큰 금액의 100분의 5 이상인 것으로 한다.')}

    <div class="guide-subtabs" id="ftcGuideSubtabs">
      <button type="button" class="guide-subtab-btn active" data-ftc-subtab="invest">특수관계인 출자</button>
      <button type="button" class="guide-subtab-btn" data-ftc-subtab="bond">특수관계인 채권매도</button>
      <button type="button" class="guide-subtab-btn" data-ftc-subtab="goods">상품ㆍ용역거래</button>
    </div>

    <div class="guide-subtab-panel" data-ftc-panel="invest">
      <h4>서식 항목 — 특수관계인에대한출자</h4>
      <p class="info">작성대상: 특수관계인을 상대방으로 하거나 특수관계인을 위하여 자본총계 또는 자본금 중 큰
      금액의 5% 이상(그 금액이 5억원 미만인 경우 5억원) 이거나 100억원 이상을 <b>출자</b>하는 회사</p>
      ${guideFieldsHtml([
        { label: '1. 거래상대방 / 회사와의 관계', note: '계열회사ㆍ동일인 등(동일인ㆍ배우자ㆍ혈족1촌)ㆍ동일인의 친족ㆍ기타친족ㆍ임원ㆍ비영리법인 등으로 구분 기재' },
        { label: '2. 출자내역 — 가. 출자일자 / 나. 출자목적물 / 다. 출자금액 / 라. 출자상대방 총출자액', note: '"출자상대방 총출자액"은 이번 출자금액을 포함한 누계 총출자금액' },
        { label: '3. 출자목적', note: '' },
        { label: '4. 이사회 의결일 — 사외이사 참석여부 / 감사(감사위원) 참석여부', note: '' },
        { label: '5. 기타 / ※ 관련공시일', note: '변경ㆍ정정공시인 경우 관련공시일에 최초 공시 연월일 기재' },
      ])}
    </div>

    <div class="guide-subtab-panel" data-ftc-panel="bond" style="display:none">
      <h4>서식 항목 — 특수관계인에대한채권매도</h4>
      <p class="info">작성대상: 특수관계인을 상대방으로 하거나 특수관계인을 위하여 위 금액기준 이상의 <b>채권을
      매도</b>하는 회사 (채권매도의 직접 거래상대방 또는 발행자가 특수관계인인 경우)</p>
      ${guideFieldsHtml([
        { label: '1. 매도상대방 / 회사와의 관계', note: '' },
        { label: '2. 매도일자 / 3. 거래금액', note: '' },
        { label: '4. 거래상대방 잔액', note: '발행자를 기준으로 기재' },
        { label: '5. 유통수익율(%)', note: '' },
        { label: '6. 채권내역 — 가. 발행자/회사와의 관계 / 나. 종류', note: '종류에는 일반회사채ㆍ전환사채ㆍ신주인수권부사채ㆍ교환사채 등 구체적 명칭' },
        { label: '6. 채권내역 — 다. 권면금액(원)ㆍ자본금 대비(%) / 라. 표면이율(%) / 마. 발행일 / 바. 만기일', note: '' },
        { label: '7. 거래목적', note: '' },
        { label: '8. 이사회 의결일 — 사외이사 참석여부 / 감사(감사위원) 참석여부', note: '' },
        { label: '9. 기타 / ※ 관련공시일', note: '' },
      ])}
    </div>

    <div class="guide-subtab-panel" data-ftc-panel="goods" style="display:none">
      <h4>서식 항목 — 동일인등출자계열회사와의상품ㆍ용역거래 【분기공시】</h4>
      <p class="info">작성대상: 동일인 등 출자 계열회사와 분기에 이루어질 상품ㆍ용역거래금액의 합계액(매출액+매입액)이
      자본총계 또는 자본금 중 큰 금액의 5% 이상(최소 5억원)이거나 100억원 이상인 경우</p>
      ${guideFieldsHtml([
        { label: '1. 당해회사의 직전사업연도매출액(A)', note: '' },
        { label: '2. 거래기간 / 3. 이사회 의결일 — 사외이사ㆍ감사(감사위원) 참석여부', note: '거래기간에는 사업연도와 해당 분기를 기재' },
        { label: '4. 거래상대방(동일인 등 출자계열회사) — 매출액(B) / 매입액(C) / 합계액(D=B+C) / 매출액대비(D/A,%)', note: '' },
        { label: '5. 상품ㆍ용역 거래내역 — 계약명, 거래대상, 거래조건, 거래목적, 거래금액(매출/매입), 계약체결방식', note: '계약 건별로 기재. 거래조건에는 대금지급조건 등' },
        { label: '6. 계약체결방식 유형별 일괄공시', note: '계약내용이 미확정이라 건별 공시가 어려운 경우, 경쟁입찰/제한경쟁입찰/지명경쟁입찰/수의계약 유형별로 매출ㆍ매입 주요거래대상ㆍ거래금액을 일괄 기재' },
        { label: '7. 기타', note: '분기 전 예측하지 못해 미의결ㆍ미공시했다가 분기 중 대상이 된 경우, 그 구체적 사유 기재' },
      ])}

      <h4>서식 항목 — 동일인등출자계열회사와의상품ㆍ용역거래(변경)</h4>
      <p class="info">작성대상: 기공시한 상품ㆍ용역거래의 거래금액이 <b>최초 대비 20% 이상 증가ㆍ감소</b>하는 등
      주요내용을 변경하는 경우 (일괄공시로 공시했던 경우에는 기공시 거래금액보다 20% 이상 증가ㆍ감소한 분기의
      변경내역 기재)</p>
      ${guideFieldsHtml([
        { label: '1~6. (분기공시 서식과 동일)', note: '직전사업연도매출액ㆍ거래기간ㆍ이사회 의결일ㆍ거래상대방별 매출액ㆍ매입액ㆍ합계액ㆍ매출액대비ㆍ상품용역거래내역ㆍ계약체결방식 일괄공시' },
        { label: '7. 관련공시일', note: '변경내역과 관련하여 최초 공시한 연월일' },
        { label: '8. 기타', note: '주요 변동내용 등' },
      ])}

      <h4>"동일인 등 출자 계열회사(20% 계열사)" 판단기준 — 매뉴얼 원문</h4>
      <p class="info">상품ㆍ용역거래만 이 요건이 별도로 붙습니다. 거래상대방이 아래 A 또는 B에 해당해야만 대상입니다.</p>
      <ul>
        <li><b>A</b> = 자연인인 동일인이 단독으로 또는 동일인의 친족과 합하여 <b>발행주식총수의 20% 이상</b>을
          소유하고 있는 계열회사 (동일인이 자연인이 아닌 기업집단 소속 회사 — 포스코ㆍ케이티ㆍ케이티엔지 등 — 는 제외)</li>
        <li><b>B</b> = A의 「상법」 제342조의2에 따른 <b>50% 초과 자회사</b>인 계열회사</li>
        <li>동일인 및 동일인 친족이 B의 발행주식을 20% 미만 소유한 경우, A와 B 간의 상품ㆍ용역거래 시 <b>A는 이사회
          의결 및 공시의무가 없음</b>(다만 B는 이사회 의결 및 공시 필요) — 방향성이 대칭이 아님에 유의</li>
      </ul>
      ${lawArticle('공정위 고시 "대규모내부거래 등에 대한 이사회 의결 및 공시에 관한 규정" 제2조(용어의 정의) 제4호',
        '"동일인 및 동일인 친족 출자 계열회사"란 자연인인 동일인이 단독으로 또는 동일인의 친족(시행령 제6조제1항에 따라 동일인관련자로부터 제외된 자는 제외한다)과 합하여 발행주식총수의 100분의 20 이상을 소유하고 있는 계열회사 또는 그 계열회사의 「상법」 제342조의2에 따른 자회사인 계열회사를 말한다.')}
      ${lawArticle('같은 고시 제9조의2(상품 또는 용역의 대규모 내부거래행위등에 대한 특례)',
        '① 내부거래공시대상회사등이 상품 또는 용역의 대규모내부거래등을 하고자 하는 경우에는 거래금액에 대하여 이사회 의결을 1년 이내의 거래기간을 정하여 일괄하여 할 수 있다.\n② 상품 또는 용역의 실제 거래금액이 이사회에서 의결한 거래금액의 20% 이상 감소된 경우에는 이사회 의결을 거치지 아니하고 분기종료 후 45일 이내에 실제 거래금액을 공시해야 한다.\n③ 분기 전에 예측하지 못한 사유로 인해 이사회의 의결 및 공시를 하지 아니한 상품 또는 용역의 거래가 분기 중에 대규모내부거래등에 해당될 것이 예상되는 경우에는 미리 이사회의 의결을 거쳐 이를 공시해야 한다.\n④ 내부거래공시대상회사등은 계약 건별로 계약체결방식에 대하여 이사회 의결 및 공시를 하여야 한다. 다만, 이사회 의결 시점에 계약내용이 확정되지 않아 계약 건별로 이사회 의결 및 공시를 하기 어려운 경우에는 거래의 대상ㆍ금액 등 주요내용에 대하여 계약체결방식 유형별로 일괄하여 이사회 의결 및 공시를 할 수 있다.')}
    </div>

    <h4>공시시기 및 위반 시 제재 (3개 유형 공통)</h4>
    <ul>
      <li>이사회 의결 후 <b>상장법인 3영업일 이내</b>, 비상장법인ㆍ공익법인은 <b>7영업일 이내</b> 공시</li>
      <li>거래금액ㆍ거래단가ㆍ약정이자율 등이 최초 공시보다 <b>20% 이상</b> 증가ㆍ감소하면 주요내용 변경으로 보아
        이사회 의결 후 재공시 필요</li>
      <li>상품ㆍ용역거래는 특례로 실제 거래금액이 의결금액보다 20% 이상 <b>감소</b>한 경우에 한해 이사회 의결 없이
        분기종료 후 45일 이내 사후공시 가능 (20% 이상 증가가 예상되면 분기 중 사전 의결ㆍ공시 필요)</li>
      <li>위반 시: 시정조치(법 제37조① 제7호), 과태료(법 제130조① 제4호, 시행령 제94조③ 별표9)</li>
    </ul>
    <p class="rule-cite">출처: 공정거래위원회 "대규모내부거래 등에 대한 이사회 의결 및 공시 업무 매뉴얼"(2025. 4. 21., 공시점검과),
    독점규제 및 공정거래에 관한 법률 제26조, 동법 시행령 제33조, 대규모내부거래 등에 대한 이사회 의결 및 공시에 관한 규정(공정위 고시).</p>`;
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
  data.forEach((item) => {
    const change = (item[basis] ?? item.current) ?? '';
    const isUp = String(change).includes('↑');
    const isDown = String(change).includes('↓');
    const cls = isUp ? 'up' : isDown ? 'down' : '';
    const card = document.createElement('div');
    card.className = 'card theme-card';
    card.innerHTML = `<div class="theme-name">${item.name}</div><div class="theme-change ${cls}">${change}</div>`;
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
    const nxtBadge = b.source === 'NXT' ? ' <span class="nxt-badge" title="현재 넥스트레이드(NXT) 프리마켓ㆍ애프터마켓 시세">NXT</span>' : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="clickable-name" onclick="showInvestorModal('${item.ticker ?? ''}', '${name}')">${name}</span></td>
      <td class="num">${item.shares ?? ''}</td>
      <td class="num">${item.capital_billion ?? ''}</td>
      <td class="num">${item.price_prev_year ?? ''}</td>
      <td class="num">${b.price ?? ''}${nxtBadge}</td>
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
