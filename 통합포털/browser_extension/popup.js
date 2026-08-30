const DEFAULT_BASE_URL = 'http://10.62.15.197:9000';
const statusEl = document.getElementById('status');
const sendBtn = document.getElementById('sendBtn');
const baseUrlInput = document.getElementById('baseUrlInput');

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = cls || '';
}

function getBaseUrl() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['portalBaseUrl'], (r) => resolve(r.portalBaseUrl || DEFAULT_BASE_URL));
  });
}

getBaseUrl().then((url) => { baseUrlInput.value = url; });

document.getElementById('saveBaseUrlBtn').addEventListener('click', () => {
  const url = (baseUrlInput.value || DEFAULT_BASE_URL).trim().replace(/\/$/, '');
  chrome.storage.local.set({ portalBaseUrl: url }, () => setStatus('저장했습니다: ' + url, 'ok'));
});

// 페이지(그룹웨어 기안 화면) 안에서 실행되는 함수 — 화면에 보이는 텍스트를 그대로
// 읽는다. 그룹웨어 화면 구조가 서식마다 달라질 수 있어서, 특정 셀렉터에 의존하지
// 않고 innerText 전체를 읽는 가장 튼튼한 방식을 쓴다(get_page_text로 실제 검증됨).
function extractPageContent() {
  const bodyText = document.body ? document.body.innerText : '';
  // "제목" 행이 있으면 그 값을 문서 제목으로 뽑아본다(참고용, 실패해도 무방).
  let title = document.title || '';
  const rows = document.querySelectorAll('tr, div');
  for (const row of rows) {
    const t = (row.textContent || '').trim();
    if (t.startsWith('제목') && t.length < 200) {
      const guess = t.replace(/^제목\s*/, '').trim();
      if (guess) { title = guess; break; }
    }
  }
  return { title: title.slice(0, 200), text: bodyText };
}

sendBtn.addEventListener('click', async () => {
  sendBtn.disabled = true;
  setStatus('문서 내용을 읽는 중...');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) throw new Error('활성 탭을 찾지 못했습니다.');

    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractPageContent,
    });
    if (!result || !result.text || !result.text.trim()) {
      throw new Error('이 페이지에서 읽을 수 있는 본문 내용이 없습니다.');
    }

    setStatus('통합포털로 전송 중...');
    const baseUrl = await getBaseUrl();
    const resp = await fetch(baseUrl + '/common/document-check/import', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: result.title, document_text: result.text, source_url: tab.url }),
    });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '알 수 없는 오류로 전송에 실패했습니다.');

    setStatus('전송 완료 — 새 탭에서 검토 화면을 엽니다.', 'ok');
    chrome.tabs.create({ url: data.redirect });
  } catch (e) {
    setStatus('오류: ' + (e && e.message ? e.message : e), 'error');
  } finally {
    sendBtn.disabled = false;
  }
});
