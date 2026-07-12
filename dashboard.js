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
let lastData = { exchange: null, indices: null, companies: null, cement: null, danpan: null, equity: null };

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
        if (activeDisclosure === 'equity' && !lastData.equity) loadEquity();
      }
    });
  });
  document.querySelectorAll('#disclosureTabs .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#disclosureTabs .tab-btn').forEach(b => b.classList.toggle('active', b === btn));
      const kind = btn.dataset.disclosure;
      document.getElementById('disclosure-danpan').style.display = kind === 'danpan' ? '' : 'none';
      document.getElementById('disclosure-equity').style.display = kind === 'equity' ? '' : 'none';
      if (kind === 'danpan' && !lastData.danpan) loadDanpan();
      if (kind === 'equity' && !lastData.equity) loadEquity();
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
  loadAllData();
});

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

// ── 지분공시(임원ㆍ주요주주 소유상황보고서) 이력 ────────────────
async function loadEquity() {
  const note = document.getElementById('equityNote');
  const tbody = document.querySelector('#equity-table tbody');
  if (note) note.textContent = 'DART 공시 원문을 조회하는 중… (최근 10년치를 하나씩 받아오므로 다소 걸릴 수 있습니다)';
  if (tbody) tbody.innerHTML = '<tr><td colspan="7">로딩 중…</td></tr>';
  try {
    const data = await safeFetch(`${API_BASE}?section=equity`);
    lastData.equity = data;
    renderEquity(data);
  } catch (err) {
    if (note) note.textContent = `조회 실패: ${err.message}`;
    if (tbody) tbody.innerHTML = `<tr><td colspan="7">조회 실패: ${err.message}</td></tr>`;
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
    tbody.innerHTML = '<tr><td colspan="7">매수 이력이 있는 지분공시가 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
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
    const displayName = roleLabel ? `${holderName}(${roleLabel})` : holderName;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="num">${idx + 1}</td>
      <td title="${escapeAttr(displayName)}">${displayName}</td>
      <td class="num">${item.first_buy_date ?? ''}</td>
      <td class="num">${item.latest_buy_date ?? ''}</td>
      <td class="num">${fmtWon(item.total_qty)}</td>
      <td class="num">${fmtWon(item.avg_price)}</td>
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
