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
let lastData = { exchange: null, indices: null, companies: null, cement: null, danpan: null };

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
      document.getElementById('page-danpan').style.display = page === 'danpan' ? '' : 'none';
      if (page === 'danpan' && !lastData.danpan) loadDanpan();
    });
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

function renderDanpan(list) {
  const tbody = document.querySelector('#danpan-table tbody');
  const note = document.getElementById('danpanNote');
  if (!tbody) return;

  if (!Array.isArray(list) || list.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9">진행 중인 단판공시 현장이 없거나, DART_API_KEY 미설정으로 조회할 수 없습니다.</td></tr>';
    if (note) note.textContent = '';
    return;
  }

  if (note) {
    note.textContent = `총 ${list.length}건 (오늘 기준 만기가 지나지 않은 현장만 표시). `
      + '공사기간이 "미정"인 건은 공시에 구체적 종료일이 없어 시스템이 진행 중으로 간주한 것으로, 실제로는 이미 준공되었을 수 있어 별도 확인이 필요합니다.';
  }

  tbody.innerHTML = '';
  list.forEach((item, idx) => {
    const period = (item.period_start || item.period_end)
      ? `${item.period_start ?? '?'} ~ ${item.period_end ?? '?'}`
      : '미정';
    const rate = item.change_rate;
    const rateClass = rate > 0 ? 'up' : rate < 0 ? 'down' : '';
    const revisionLabel = item.revision_count > 0 ? `<br><span class="info">(${item.revision_count}차 정정)</span>` : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="num">${idx + 1}</td>
      <td>${item.site_name ?? ''}</td>
      <td>${item.counterparty ?? ''}</td>
      <td class="num">${item.initial_contract_date ?? ''}</td>
      <td class="num">${item.latest_disclosure_date ?? ''}${revisionLabel}</td>
      <td class="num">${fmtMillion(item.amount)}</td>
      <td class="num ${rateClass}">${fmtPct(rate)}</td>
      <td class="num">${period}</td>
      <td><a href="${item.dart_url}" target="_blank" class="clickable-name">보기</a></td>`;
    tbody.appendChild(tr);
  });
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
