// app.js - Pension Dashboard Interaction and Chart.js integration

// Register the datalabels plugin globally
Chart.register(ChartDataLabels);

// Disable datalabels by default for all charts to prevent clutter on bar/line charts
Chart.defaults.set('plugins.datalabels', {
    display: false
});

// Custom plugin: 파이/도넛 조각의 외곽 라벨을 각 조각 바로 옆(자기 각도 방향)에 짧은 선으로 표기.
// - 좌/우는 그 조각의 실제 각도(중심 기준 왼쪽/오른쪽) 그대로 쓴다 — 반대쪽으로 넘기면
//   anchor는 여전히 원래 자리인데 텍스트만 반대로 정렬돼 도넛에 파고들어 붙어 보이는
//   문제가 있어서(실제로 겪음) 넘기지 않기로 했다.
// - 같은 쪽 라벨끼리 실제로 겹칠 때만, 순서를 유지한 채 "필요한 만큼만" 세로로 밀어낸다.
// - 지시선은 anchor(도넛 테두리에서 살짝 띄움) → 조각의 자기 각도로 짧게 뻗은 꺾임점 →
//   텍스트, 이렇게 2구간으로 그려서 라벨이 세로로 밀렸을 때도 어느 조각과 이어지는
//   선인지 명확하게 보이도록 한다.
// - 비중이 아주 작은 조각(기본 2% 미만)은 외곽 라벨을 생략한다(범례/툴팁으로 확인 가능).
const smartOutsideLabelsPlugin = {
    id: 'smartOutsideLabels',
    afterDraw(chart, args, opts) {
        const formatter = opts && opts.formatter;
        if (!formatter) return;

        const ctx = chart.ctx;
        const dataset = chart.data.datasets[0];
        const meta = chart.getDatasetMeta(0);
        if (!meta.data || meta.data.length === 0) return;

        const total = dataset.data.reduce((acc, val) => acc + val, 0) || 1;
        const minRatio = opts.minRatio != null ? opts.minRatio : 0.02;
        const edgeGap = 6;          // 도넛 테두리와 지시선 시작점 사이 여백(선이 도형에 딱 붙어 보이지 않도록)
        const lineLength = 16;      // 조각 바로 바깥으로 뻗는 짧은 지시선 길이
        const lineHeight = 13;
        const blockHeight = lineHeight + 7; // 라벨 1개당 필요한 세로 공간(한 줄 + 여백)

        // 1) 라벨 후보: 조각의 실제 각도로 좌/우와 자연 위치(anchor/elbow)를 그대로 계산
        const items = [];
        meta.data.forEach((arc, index) => {
            const rawValue = dataset.data[index];
            const ratio = rawValue / total;
            if (ratio < minRatio) return; // 너무 작은 조각은 외곽 라벨 생략
            const info = formatter(index);
            if (!info) return;

            const midAngle = arc.startAngle + (arc.endAngle - arc.startAngle) / 2;
            const cos = Math.cos(midAngle);
            const sin = Math.sin(midAngle);
            items.push({
                info,
                cos,
                ratio,
                side: cos >= 0 ? 'right' : 'left',
                anchorX: arc.x + cos * (arc.outerRadius + edgeGap),
                anchorY: arc.y + sin * (arc.outerRadius + edgeGap),
                elbowX: arc.x + cos * (arc.outerRadius + edgeGap + lineLength),
                elbowY: arc.y + sin * (arc.outerRadius + edgeGap + lineLength)
            });
        });
        if (items.length === 0) return;

        // (좌우로 반대쪽에 넘기는 시도는 되돌렸다 — side만 바꾸고 anchorX/elbowX는
        // 원래 각도 그대로 두면, 실제로는 오른쪽에 있는 조각인데 텍스트만 왼쪽으로
        // 정렬돼서 그 조각 쪽(도넛)으로 파고들어 붙어 보이는 버그가 있었다. side를
        // 바꾸려면 anchor 자체를 반대쪽 여백까지 다시 계산해야 하는데, 그러면 결국
        // 큰 조각을 옮겼을 때와 같은 문제(선이 도넛을 가로지름)가 재발한다. 그래서
        // 좌/우는 각 조각의 실제 각도 그대로 두고, 아래 세로 겹침 보정만으로 정리한다.)

        // 2) 같은 쪽에서 겹치는 라벨만 순서를 유지한 채 최소한으로 세로로 밀어내기 (2-패스: 정방향 후 역방향 보정)
        ['left', 'right'].forEach(side => {
            const group = items.filter(it => it.side === side).sort((a, b) => a.elbowY - b.elbowY);
            if (group.length === 0) return;

            // chartArea는 원(도넛) 자체의 영역이고, layout.padding으로 미리 확보해둔
            // 라벨용 여백은 chartArea 바깥(캔버스 쪽)에 있다 — 그 여백까지 전부 사용한다.
            const top = blockHeight / 2 + 2;
            const bottom = chart.height - blockHeight / 2 - 2;

            group.forEach(it => { it.labelY = Math.max(it.elbowY, top); });
            for (let i = 1; i < group.length; i++) {
                const minY = group[i - 1].labelY + blockHeight;
                if (group[i].labelY < minY) group[i].labelY = minY;
            }
            const last = group[group.length - 1];
            if (last.labelY > bottom) {
                last.labelY = bottom;
                for (let i = group.length - 2; i >= 0; i--) {
                    const maxY = group[i + 1].labelY - blockHeight;
                    if (group[i].labelY > maxY) group[i].labelY = maxY;
                }
            }
        });

        // 5) 지시선 + 텍스트 그리기
        //    - 조각→라벨을 anchor→꺾임점(elbow, 자기 각도로 짧게)→텍스트 순 2구간으로
        //      잇는다(아래 bendX 계산부 참고). 라벨이 안 밀렸으면 사실상 일직선처럼
        //      보이고, 옆 라벨과 겹쳐서 밀렸을 때만 꺾인 모양이 뚜렷해져 어느 조각과
        //      이어지는 선인지 헷갈리지 않는다.
        //    - "도형 밖으로 나가야 한다"가 최우선 규칙이다. 텍스트 시작점은 항상 anchorX
        //      기준 바깥쪽으로 고정하고(절대 도형 안쪽으로 들어오지 않음), 캔버스 폭이
        //      부족하면 글꼴 크기를 줄여서 최대한 맞추되, 그래도 안 맞으면 캔버스 가장자리가
        //      살짝 잘리는 쪽을 택한다(도형과 겹치는 것보다는 낫다).
        const margin = 4;
        const baseFontSize = 10.5;
        const minFontSize = 7;
        ctx.save();
        items.forEach(it => {
            const { side, info, anchorX, anchorY, labelY } = it;
            const padX = side === 'right' ? 5 : -5;
            const fullText = `${info.title} ${info.sub}`;
            const availableWidth = Math.max(
                20,
                side === 'right' ? (chart.width - margin - anchorX - Math.abs(padX)) : (anchorX - margin - Math.abs(padX))
            );

            ctx.font = `700 ${baseFontSize}px Inter, 'Noto Sans KR'`;
            let textWidth = ctx.measureText(fullText).width;
            if (textWidth > availableWidth) {
                const fontSize = Math.max(minFontSize, baseFontSize * (availableWidth / textWidth));
                ctx.font = `700 ${fontSize}px Inter, 'Noto Sans KR'`;
                textWidth = ctx.measureText(fullText).width;
            }

            // 도형 바깥쪽(anchorX 기준)에서 시작 — 캔버스 clamp보다 이 제약이 항상 우선한다
            const textX = side === 'right' ? Math.max(anchorX, it.elbowX) : Math.min(anchorX, it.elbowX);

            // 조각 가장자리(anchor) → 자기 각도로 짧게 뻗은 꺾임점(elbowX, 다만 세로
            // 위치는 겹침 보정이 끝난 labelY로) → 텍스트 시작점까지 수평선, 이렇게
            // 2구간으로 그린다. 라벨이 안 밀렸으면(labelY가 원래 위치와 같으면)
            // 사실상 거의 일직선으로 보이고, 겹쳐서 밀렸으면 확실한 "꺾인선"으로
            // 보여 어느 조각과 이어지는지 헷갈리지 않는다(예전엔 anchor에서 밀린
            // 라벨까지 대각선 하나로 이어서, 옆 조각 라벨과 선이 교차해 보였다).
            const bendX = side === 'right' ? Math.max(it.elbowX, anchorX) : Math.min(it.elbowX, anchorX);
            ctx.beginPath();
            ctx.moveTo(anchorX, anchorY);
            ctx.lineTo(bendX, labelY);
            ctx.lineTo(textX, labelY);
            ctx.strokeStyle = 'rgba(15, 23, 42, 0.35)';
            ctx.lineWidth = 1;
            ctx.stroke();

            ctx.textAlign = side === 'right' ? 'left' : 'right';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = '#0f172a';
            ctx.shadowColor = 'rgba(255, 255, 255, 0.9)';
            ctx.shadowBlur = 3;
            ctx.fillText(fullText, textX + padX, labelY);
        });
        ctx.restore();
    }
};

let pensionData = null;
let activeDate = null;
let useMillionUnit = false;
let activeInstFilter = null;  // 기관별 파이차트 클릭 필터
let activeProductFilter = null;  // 상품유형별 파이차트 클릭 필터
let filterMaturingThisYear = false;  // 당해년도 만기 필터

// Chart references
let chartInst = null;
let chartProd = null;
let chartMaturity = null;
let chartYoY = null;

// ────────────────────────────────────────────────────────
// Initialize
// ────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    if (location.protocol === "file:") {
        document.body.innerHTML = `
            <div style="max-width:560px;margin:15vh auto;padding:2rem;text-align:center;
                        background:#111827;border:1px solid #334155;border-radius:16px;color:#e2e8f0;">
                <h2 style="margin-bottom:0.8rem;">⚠️ 잘못된 방법으로 열었습니다</h2>
                <p style="color:#94a3b8;line-height:1.7;">
                    index.html 파일을 직접 더블클릭하면 데이터를 불러올 수 없습니다.<br>
                    같은 폴더의 <strong style="color:#60a5fa;">대시보드_실행.bat</strong> 파일을
                    더블클릭해서 실행해주세요.<br>서버가 켜지고 브라우저가 자동으로 열립니다.
                </p>
            </div>`;
        return;
    }

    fetch("data.json")
        .then(res => res.json())
        .then(data => {
            pensionData = data;
            initDashboard();
        })
        .catch(err => {
            console.error("Failed to load pension data:", err);
            alert("퇴직연금 데이터 로드에 실패했습니다. 서버를 통해 접속했는지 확인해 주세요.\n(http://localhost:8000)");
        });

    // Unit Toggle
    document.getElementById("unit-toggle").addEventListener("change", (e) => {
        useMillionUnit = e.target.checked;
        updateDashboard();
    });

    // Snapshot Select (최근 3개년 · 분기별)
    document.getElementById("snapshot-select").addEventListener("change", (e) => {
        activeDate = e.target.value;
        activeInstFilter = null;   // 기준일 변경 시 필터 초기화
        activeProductFilter = null;
        filterMaturingThisYear = false;
        document.getElementById("maturing-this-year-btn").classList.remove("active");
        const legacySelect = document.getElementById("legacy-year-select");
        if (legacySelect) legacySelect.selectedIndex = 0;
        updateDashboard();
    });

    // 이전 연도 선택 (최근 3개년 이전 · 사업연도말 위주)
    const legacySelect = document.getElementById("legacy-year-select");
    if (legacySelect) {
        legacySelect.addEventListener("change", (e) => {
            if (!e.target.value) return;
            activeDate = e.target.value;
            activeInstFilter = null;
            activeProductFilter = null;
            filterMaturingThisYear = false;
            document.getElementById("maturing-this-year-btn").classList.remove("active");
            document.getElementById("snapshot-select").selectedIndex = -1;
            updateDashboard();
        });
    }

    // Search
    document.getElementById("table-search-input").addEventListener("input", () => {
        renderTable();
    });

    // Maturing this year toggle
    const maturingThisYearBtn = document.getElementById("maturing-this-year-btn");
    maturingThisYearBtn.addEventListener("click", () => {
        filterMaturingThisYear = !filterMaturingThisYear;
        if (filterMaturingThisYear) {
            maturingThisYearBtn.classList.add("active");
        } else {
            maturingThisYearBtn.classList.remove("active");
        }
        renderTable();
    });

    // Filter clear button
    document.getElementById("filter-clear-btn").addEventListener("click", () => {
        activeInstFilter = null;
        activeProductFilter = null;
        filterMaturingThisYear = false;
        document.getElementById("table-filter-badge").style.display = "none";
        document.getElementById("maturing-this-year-btn").classList.remove("active");
        document.getElementById("table-search-input").value = "";
        renderTable();
        // 차트 하이라이트 해제
        if (chartInst) chartInst.update();
        if (chartProd) chartProd.update();
    });

    // KPI 카드 클릭 → 계산 상세 모달
    document.getElementById("kpi-weighted-yield").addEventListener("click", () => openCalcModal("yield"));
    document.getElementById("kpi-expected-interest").addEventListener("click", () => openCalcModal("interest"));

    // 모달 닫기
    document.getElementById("calc-modal-close").addEventListener("click", () => {
        document.getElementById("calc-modal-overlay").style.display = "none";
    });
    document.getElementById("calc-modal-overlay").addEventListener("click", (e) => {
        if (e.target === e.currentTarget) e.currentTarget.style.display = "none";
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") document.getElementById("calc-modal-overlay").style.display = "none";
    });
});

// ────────────────────────────────────────────────────────
// Dashboard Init
// ────────────────────────────────────────────────────────
/** "YYYY-MM-DD" → "YYYY.N분기" (분기말 스냅샷). 분기말이 아닌 중간월 스냅샷은
 *  같은 분기 안에서 라벨이 겹치지 않도록 "(M월)"을 붙여 구분한다. */
function toQuarterLabel(dateStr) {
    const [y, m] = dateStr.split("-").map(Number);
    const q = Math.ceil(m / 3);
    const isQuarterEnd = m % 3 === 0;
    return isQuarterEnd ? `${y}.${q}분기` : `${y}.${q}분기(${m}월)`;
}

function initDashboard() {
    const snapSelect = document.getElementById("snapshot-select");
    const legacySelect = document.getElementById("legacy-year-select");
    const legacyGroup = document.getElementById("legacy-year-group");
    snapSelect.innerHTML = "";
    if (legacySelect) legacySelect.innerHTML = "";

    // 날짜 내림차순 정렬 (같은 해에서는 연말/최신 분기가 먼저 오도록)
    const sortedDates = Object.keys(pensionData.snapshots).sort((a, b) => b.localeCompare(a));

    const allYears = [...new Set(sortedDates.map(d => parseInt(d.split("-")[0], 10)))].sort((a, b) => b - a);
    const recentYears = allYears.slice(0, 3);   // 당해년도 포함 최근 3개년: 분기별로 전부 노출
    const legacyYears = allYears.slice(3);       // 그 이전 연도: 사업연도말 위주로 별도 선택

    // 최근 3개년: 연도별 optgroup, 그룹 내부는 최신 분기(연말)가 먼저 오도록 정렬됨
    recentYears.forEach((year, idx) => {
        const group = document.createElement("optgroup");
        group.label = idx === 0 ? `▼ ${year}년 (당해년도)` : `▼ ${year}년`;
        sortedDates
            .filter(d => d.startsWith(`${year}-`))
            .forEach(dateStr => {
                const opt = document.createElement("option");
                opt.value = dateStr;
                opt.textContent = toQuarterLabel(dateStr);
                group.appendChild(opt);
            });
        if (group.children.length > 0) snapSelect.appendChild(group);
    });

    // 최근 3개년 이전: "이전 연도" 드롭다운에서 사업연도말(해당 연도의 가장 늦은 스냅샷) 기준으로 선택
    if (legacySelect && legacyGroup) {
        if (legacyYears.length > 0) {
            const placeholder = document.createElement("option");
            placeholder.value = "";
            placeholder.textContent = "선택...";
            legacySelect.appendChild(placeholder);

            legacyYears.forEach(year => {
                const yearDates = sortedDates.filter(d => d.startsWith(`${year}-`)); // 내림차순 정렬돼 있으므로 [0]=사업연도말(최신)
                const opt = document.createElement("option");
                opt.value = yearDates[0];
                opt.textContent = `${year}년 (사업연도말)`;
                legacySelect.appendChild(opt);
            });
            legacyGroup.style.display = "";
        } else {
            legacyGroup.style.display = "none";
        }
    }

    // 최신 기준일 기본 선택
    activeDate = sortedDates[0];
    snapSelect.value = activeDate;

    updateDashboard();
}

// ────────────────────────────────────────────────────────
// Format helpers
// ────────────────────────────────────────────────────────
/** 억원 단위 표기 (만기/YoY 차트용) */
function toOkUnit(value) {
    return Math.round(value / 100000000 * 10) / 10;  // 소수 1자리
}

function formatValue(value, isPercent = false, forceWon = false) {
    if (isPercent) {
        return (value * 100).toFixed(3) + "%";
    }
    if (useMillionUnit && !forceWon) {
        const valMil = value / 1000000;
        return valMil.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 1 });
    } else {
        return Math.round(value).toLocaleString();
    }
}

// ────────────────────────────────────────────────────────
// Main update
// ────────────────────────────────────────────────────────
function updateDashboard() {
    if (!pensionData || !activeDate) return;

    // 엑셀 다운로드 링크가 항상 지금 보고 있는 기준일 데이터를 받도록 갱신
    const exportLink = document.getElementById("export-link");
    if (exportLink) exportLink.href = "/export.xlsx?base_date=" + encodeURIComponent(activeDate);

    const snap = pensionData.snapshots[activeDate];
    const prevYearEndSnap = getPrevYearEndSnapshot(activeDate);

    const unitLabel = useMillionUnit ? "백만원" : "원";
    document.getElementById("unit-total-assets").textContent = unitLabel;
    document.getElementById("unit-expected-interest").textContent = unitLabel;

    // KPI 카드
    document.getElementById("val-total-assets").textContent = formatValue(snap.total_amount);
    document.getElementById("val-weighted-yield").textContent = formatValue(snap.weighted_yield, true);
    // 연 이자: 정수 반올림
    document.getElementById("val-expected-interest").textContent = formatValue(Math.round(snap.expected_interest));

    updateKPITrends(snap, prevYearEndSnap);

    renderInstitutionChart(snap);
    renderProductChart(snap);
    renderMaturityChart(snap);
    renderYoYChart();
    renderTable();
    renderComparisonSection(snap, prevYearEndSnap);
}

function getPrevYearEndSnapshot(dateStr) {
    const year = parseInt(dateStr.split("-")[0]);
    const prevYear = year - 1;
    const targetDateStr = `${prevYear}-12-31`;
    if (pensionData.snapshots[targetDateStr]) return pensionData.snapshots[targetDateStr];
    const fallback = Object.keys(pensionData.snapshots)
        .filter(d => d.startsWith(`${prevYear}-`))
        .sort((a, b) => b.localeCompare(a))[0];
    return fallback ? pensionData.snapshots[fallback] : null;
}

function updateKPITrends(current, previous) {
    const trendAssetsEl = document.getElementById("trend-total-assets");
    const trendYieldEl = document.getElementById("trend-weighted-yield");

    if (!previous) {
        trendAssetsEl.textContent = "전년도 비교 데이터 없음";
        trendAssetsEl.className = "kpi-trend trend-neutral";
        trendYieldEl.textContent = "전년도 비교 데이터 없음";
        trendYieldEl.className = "kpi-trend trend-neutral";
        return;
    }

    const prevYear = previous.base_date.split("-")[0];

    // 자산 증감
    const assetDiff = current.total_amount - previous.total_amount;
    const assetPct = (assetDiff / previous.total_amount) * 100;
    const diffText = Math.round(Math.abs(assetDiff)).toLocaleString() + "원";

    if (assetDiff > 0) {
        trendAssetsEl.textContent = `전년말(${prevYear}년) 대비 ▲ ${assetPct.toFixed(1)}% (${diffText} 증가)`;
        trendAssetsEl.className = "kpi-trend trend-up";
    } else if (assetDiff < 0) {
        trendAssetsEl.textContent = `전년말(${prevYear}년) 대비 ▼ ${Math.abs(assetPct).toFixed(1)}% (${diffText} 감소)`;
        trendAssetsEl.className = "kpi-trend trend-down";
    } else {
        trendAssetsEl.textContent = `전년말(${prevYear}년) 대비 변동 없음`;
        trendAssetsEl.className = "kpi-trend trend-neutral";
    }

    // 수익률 변동
    const yieldDiff = (current.weighted_yield - previous.weighted_yield) * 100;
    const yieldDiffText = Math.abs(yieldDiff).toFixed(3) + "%p";
    if (yieldDiff > 0) {
        trendYieldEl.textContent = `전년말(${prevYear}년) 대비 ▲ ${yieldDiffText} 상승`;
        trendYieldEl.className = "kpi-trend trend-up";
    } else if (yieldDiff < 0) {
        trendYieldEl.textContent = `전년말(${prevYear}년) 대비 ▼ ${yieldDiffText} 하락`;
        trendYieldEl.className = "kpi-trend trend-down";
    } else {
        trendYieldEl.textContent = `전년말(${prevYear}년) 대비 변동 없음`;
        trendYieldEl.className = "kpi-trend trend-neutral";
    }
}

// ────────────────────────────────────────────────────────
// CHART: Institution (Doughnut) — 클릭 시 테이블 필터
// ────────────────────────────────────────────────────────
const INST_COLORS = [
    '#3b82f6', '#10b981', '#06b6d4', '#f59e0b',
    '#c084fc', '#f472b6', '#ec4899', '#6366f1',
    '#14b8a6', '#64748b'
];

function renderInstitutionChart(snap) {
    if (chartInst) chartInst.destroy();

    const ctx = document.getElementById("chart-institution").getContext("2d");
    const labels = snap.institution_distribution.map(d => d.institution);
    const data = snap.institution_distribution.map(d =>
        useMillionUnit ? d.amount / 1000000 : d.amount
    );
    const percentages = snap.institution_distribution.map(d => (d.ratio * 100).toFixed(1) + "%");

    chartInst = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: INST_COLORS.slice(0, labels.length),
                borderWidth: 2,
                borderColor: 'rgba(15, 23, 42, 0.8)'
            }]
        },
        plugins: [smartOutsideLabelsPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: 85
            },
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    applyInstFilter(labels[elements[0].index]);
                }
            },
            plugins: {
                legend: {
                    display: false // 커스텀 범례 사용
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const index = context.dataIndex;
                            const amt = context.raw.toLocaleString(undefined, { maximumFractionDigits: 1 });
                            const unit = useMillionUnit ? "백만원" : "원";
                            return ` ${context.label}: ${amt} ${unit} (${percentages[index]})`;
                        }
                    }
                },
                datalabels: {
                    display: false
                },
                smartOutsideLabels: {
                    formatter: (index) => {
                        const d = snap.institution_distribution[index];
                        const percentage = (d.ratio * 100).toFixed(1) + "%";
                        const okUnit = (d.amount / 100000000).toFixed(1);
                        return { title: d.institution, sub: `${okUnit}억원(${percentage})` };
                    }
                }
            }
        }
    });

    // 범례 생성 (클릭 시 테이블 필터)
    generateCustomLegend("legend-institution", chartInst, (instName) => applyInstFilter(instName));
}

// 기관별 필터 적용/해제 (차트 클릭·범례 클릭 공용) — 상품유형 필터와는 동시 적용 안 함
function applyInstFilter(instName) {
    activeProductFilter = null;
    if (activeInstFilter === instName) {
        activeInstFilter = null; // 동일 항목 재클릭 → 필터 해제
        document.getElementById("table-filter-badge").style.display = "none";
    } else {
        activeInstFilter = instName;
        const badge = document.getElementById("table-filter-badge");
        badge.textContent = `🔍 ${instName} 필터 적용 중`;
        badge.style.display = "inline-flex";
    }
    document.getElementById("table-search-input").value = "";
    renderTable();
    if (chartProd) chartProd.update();
    document.querySelector(".table-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

// 상품유형별 필터 적용/해제 (차트 클릭·범례 클릭 공용)
function applyProductFilter(productType) {
    activeInstFilter = null;
    if (activeProductFilter === productType) {
        activeProductFilter = null; // 동일 항목 재클릭 → 필터 해제
        document.getElementById("table-filter-badge").style.display = "none";
    } else {
        activeProductFilter = productType;
        const badge = document.getElementById("table-filter-badge");
        badge.textContent = `🔍 ${productType} 필터 적용 중`;
        badge.style.display = "inline-flex";
    }
    document.getElementById("table-search-input").value = "";
    renderTable();
    if (chartInst) chartInst.update();
    document.querySelector(".table-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ────────────────────────────────────────────────────────
// CHART: Product (Pie)
// ────────────────────────────────────────────────────────
function renderProductChart(snap) {
    if (chartProd) chartProd.destroy();

    const ctx = document.getElementById("chart-product").getContext("2d");
    // 금액 0 제외
    const dist = snap.product_distribution.filter(d => d.amount > 0);
    const labels = dist.map(d => d.product_type);
    const data = dist.map(d => useMillionUnit ? d.amount / 1000000 : d.amount);
    const percentages = dist.map(d => (d.ratio * 100).toFixed(1) + "%");

    chartProd = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: ['#0284c7', '#10b981', '#f59e0b', '#a855f7', '#64748b'],
                borderWidth: 2,
                borderColor: 'rgba(15, 23, 42, 0.8)'
            }]
        },
        plugins: [smartOutsideLabelsPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: 85
            },
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    applyProductFilter(labels[elements[0].index]);
                }
            },
            plugins: {
                legend: {
                    display: false // 커스텀 범례 사용
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const index = context.dataIndex;
                            const amt = context.raw.toLocaleString(undefined, { maximumFractionDigits: 1 });
                            const unit = useMillionUnit ? "백만원" : "원";
                            return ` ${context.label}: ${amt} ${unit} (${percentages[index]})`;
                        }
                    }
                },
                datalabels: {
                    display: false
                },
                smartOutsideLabels: {
                    formatter: (index) => {
                        const item = dist[index];
                        const percentage = (item.ratio * 100).toFixed(1) + "%";
                        const okUnit = (item.amount / 100000000).toFixed(1);
                        return { title: item.product_type, sub: `${okUnit}억원(${percentage})` };
                    }
                }
            }
        }
    });
    document.getElementById("chart-product").style.cursor = "pointer";

    // 범례 생성 (클릭 시 테이블 필터)
    generateCustomLegend("legend-product", chartProd, (productType) => applyProductFilter(productType));
}

// ────────────────────────────────────────────────────────
// Custom HTML Legend Generator (2 Columns)
// ────────────────────────────────────────────────────────
function generateCustomLegend(containerId, chart, clickHandler = null) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = "";

    const datasets = chart.data.datasets[0];
    const labels = chart.data.labels;

    labels.forEach((label, index) => {
        const color = datasets.backgroundColor[index];

        const itemDiv = document.createElement("div");
        itemDiv.className = "legend-item";

        // Color box
        const colorBox = document.createElement("span");
        colorBox.className = "legend-color-box";
        colorBox.style.backgroundColor = color;

        // Label text
        const labelSpan = document.createElement("span");
        labelSpan.className = "legend-label";
        labelSpan.textContent = label;

        itemDiv.appendChild(colorBox);
        itemDiv.appendChild(labelSpan);

        // Click interaction if available
        if (clickHandler) {
            itemDiv.addEventListener("click", () => {
                clickHandler(label, index);
            });
        }

        // Hover highlighting effect
        itemDiv.addEventListener("mouseenter", () => {
            chart.setActiveElements([{ datasetIndex: 0, index: index }]);
            chart.update();
        });
        itemDiv.addEventListener("mouseleave", () => {
            chart.setActiveElements([]);
            chart.update();
        });

        container.appendChild(itemDiv);
    });
}

// ────────────────────────────────────────────────────────
// CHART: Maturity (Bar) — 단위: 억원
// ────────────────────────────────────────────────────────
function renderMaturityChart(snap) {
    if (chartMaturity) chartMaturity.destroy();

    const ctx = document.getElementById("chart-maturity").getContext("2d");
    const labels = snap.maturity_distribution.map(d => d.category);
    const amounts = snap.maturity_distribution.map(d => toOkUnit(d.amount));
    const yields = snap.maturity_distribution.map(d => (d.yield * 100).toFixed(3));

    chartMaturity = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '만기금액 (억원)',
                    data: amounts,
                    backgroundColor: 'rgba(59, 130, 246, 0.55)',
                    borderColor: '#3b82f6',
                    borderWidth: 1,
                    yAxisID: 'y'
                },
                {
                    label: '구간 평균금리 (%)',
                    data: yields,
                    type: 'line',
                    borderColor: '#10b981',
                    backgroundColor: '#10b981',
                    borderWidth: 2,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { color: 'rgba(15,23,42,0.06)' }, ticks: { color: '#94a3b8' } },
                y: {
                    type: 'linear', position: 'left',
                    grid: { color: 'rgba(15,23,42,0.06)' },
                    ticks: {
                        color: '#94a3b8',
                        callback: v => v.toLocaleString() + "억"
                    },
                    title: { display: true, text: '억원', color: '#64748b', font: { size: 11 } }
                },
                y1: {
                    type: 'linear', position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#94a3b8', callback: v => parseFloat(v).toFixed(2) + "%" }
                }
            },
            plugins: {
                legend: { labels: { color: '#94a3b8' } },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            if (context.datasetIndex === 0) {
                                return ` ${context.label}: ${context.raw.toLocaleString()}억원`;
                            }
                            return ` 평균금리: ${context.raw}%`;
                        }
                    }
                }
            }
        }
    });
}

// ────────────────────────────────────────────────────────
// CHART: YoY Trend — 단위: 억원
// ────────────────────────────────────────────────────────
function renderYoYChart() {
    if (chartYoY) chartYoY.destroy();

    const ctx = document.getElementById("chart-yoy").getContext("2d");
    const yoyData = [...pensionData.yoy_comparison].sort((a, b) => a.year - b.year);
    const labels = yoyData.map(d => {
        const yr = d.year;
        const suffix = d.date.includes("06-30") ? " (반기)" : "년말";
        return yr + suffix;
    });
    const amounts = yoyData.map(d => toOkUnit(d.total_amount));
    const yields = yoyData.map(d => (d.weighted_yield * 100).toFixed(3));

    chartYoY = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '총 운용자산 (억원)',
                    data: amounts,
                    backgroundColor: 'rgba(96, 165, 250, 0.45)',
                    borderColor: '#60a5fa',
                    borderWidth: 1,
                    yAxisID: 'y'
                },
                {
                    label: '가중평균 수익률 (%)',
                    data: yields,
                    type: 'line',
                    borderColor: '#10b981',
                    backgroundColor: '#10b981',
                    borderWidth: 3,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { color: 'rgba(15,23,42,0.06)' }, ticks: { color: '#94a3b8' } },
                y: {
                    type: 'linear', position: 'left',
                    grid: { color: 'rgba(15,23,42,0.06)' },
                    ticks: {
                        color: '#94a3b8',
                        callback: v => v.toLocaleString() + "억"
                    },
                    title: { display: true, text: '억원', color: '#64748b', font: { size: 11 } }
                },
                y1: {
                    type: 'linear', position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#94a3b8', callback: v => parseFloat(v).toFixed(2) + "%" }
                }
            },
            plugins: {
                legend: { labels: { color: '#94a3b8' } },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const index = context.dataIndex;
                            const item = yoyData[index];
                            if (context.datasetIndex === 0) {
                                let label = ` 총 자산: ${context.raw.toLocaleString()}억원`;
                                if (item.growth_amount !== 0) {
                                    const sign = item.growth_amount > 0 ? "▲" : "▼";
                                    const growthOk = toOkUnit(Math.abs(item.growth_amount));
                                    label += ` (전년비 ${sign} ${(Math.abs(item.growth_rate) * 100).toFixed(1)}%, ${growthOk.toLocaleString()}억)`;
                                }
                                return label;
                            } else {
                                let label = ` 가중수익률: ${context.raw}%`;
                                if (item.yield_change !== 0) {
                                    const sign = item.yield_change > 0 ? "+" : "";
                                    label += ` (전년비 ${sign}${item.yield_change.toFixed(3)}%p)`;
                                }
                                return label;
                            }
                        }
                    }
                }
            }
        }
    });
}

// ────────────────────────────────────────────────────────
// TABLE
// ────────────────────────────────────────────────────────
function getInstBadgeClass(inst) {
    if (inst.includes("농협")) return "inst-nh";
    if (inst.includes("산업")) return "inst-kdb";
    if (inst.includes("우리")) return "inst-woori";
    if (inst.includes("기업") || inst.includes("IBK")) return "inst-ibk";
    if (inst.includes("국민") || inst.includes("KB")) return "inst-kdbbank";
    if (inst.includes("삼성")) return "inst-samsung";
    if (inst.includes("하나")) return "inst-hana";
    if (inst.includes("신한")) return "inst-shinhan";
    return "";
}

function renderTable() {
    if (!pensionData || !activeDate) return;

    const snap = pensionData.snapshots[activeDate];
    const searchVal = document.getElementById("table-search-input").value.toLowerCase().replace(/\s/g, "");
    const tbody = document.getElementById("table-body");
    tbody.innerHTML = "";

    let filtered = snap.items;

    // 기관 필터 (파이차트 클릭)
    if (activeInstFilter) {
        filtered = filtered.filter(item => item.institution === activeInstFilter);
    }

    // 상품유형 필터 (파이차트 클릭)
    if (activeProductFilter) {
        filtered = filtered.filter(item => item.product_type === activeProductFilter);
    }

    // 당해년도 만기 필터
    if (filterMaturingThisYear) {
        const activeYear = activeDate.split("-")[0]; // E.g., '2026'
        filtered = filtered.filter(item => {
            if (!item.end) return false;
            const endYear = item.end.split("-")[0];
            return endYear === activeYear;
        });
    }

    // 텍스트 검색 필터
    if (searchVal) {
        filtered = filtered.filter(item => {
            const inst = (item.institution || "").toLowerCase().replace(/\s/g, "");
            const prod = (item.product || "").toLowerCase().replace(/\s/g, "");
            return inst.includes(searchVal) || prod.includes(searchVal);
        });
    }

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:2rem;">검색 결과가 없습니다.</td></tr>`;
        return;
    }

    filtered.forEach(item => {
        const tr = document.createElement("tr");
        const badgeClass = getInstBadgeClass(item.institution);
        const instCell = `<td><span class="inst-badge ${badgeClass}">${item.institution}</span></td>`;

        // 실적배당형 표기
        const isPerfBased = item.is_performance;
        const prodDisplay = isPerfBased
            ? `${item.product} <span class="perf-badge">실적배당</span>`
            : item.product;
        const prodCell = `<td>${prodDisplay}</td>`;

        // 금리: 실적배당형은 "(연환산)"으로 표기
        const rateDisplay = item.rate > 0
            ? (item.rate * 100).toFixed(2) + "%"
            : "-";
        const rateNote = isPerfBased && item.rate > 0 ? " <span class='rate-note'>(연환산)</span>" : "";
        const rateCell = `<td>${rateDisplay}${rateNote}</td>`;

        const startCell = `<td>${item.start || "-"}</td>`;
        const newDateCell = `<td>${item.new_date || "-"}</td>`;
        const endCell = `<td>${item.end || "-"}</td>`;

        const amtVal = formatValue(item.amount);
        const unitSuffix = useMillionUnit ? " 백만원" : " 원";
        const amtCell = `<td class="text-right amount-cell">${amtVal}<span style="font-size:0.75rem;color:var(--text-muted);font-weight:400;">${unitSuffix}</span></td>`;

        tr.innerHTML = instCell + prodCell + rateCell + startCell + newDateCell + endCell + amtCell;
        tbody.appendChild(tr);
    });
}

// ────────────────────────────────────────────────────────
// MODAL: 계산 상세 내역 (가중평균 수익률 / 예상 연이자)
// ────────────────────────────────────────────────────────
function openCalcModal(type) {
    if (!pensionData || !activeDate) return;
    const snap = pensionData.snapshots[activeDate];
    const prevSnap = getPrevYearEndSnapshot(activeDate);

    const overlay = document.getElementById("calc-modal-overlay");
    const title   = document.getElementById("calc-modal-title");
    const body    = document.getElementById("calc-modal-body");

    const totalAmt      = snap.total_amount;
    const totalInterest = snap.expected_interest;
    const weightedYield = snap.weighted_yield;

    // 제목
    title.textContent = type === "yield"
        ? "가중평균 수익률 계산 상세 내역"
        : "예상 연이자 계산 상세 내역";

    // ── 집계 헬퍼 (기관별/상품유형별 공용) ──
    const aggregateBy = (items, keyFn) => {
        const map = {};
        for (const item of items) {
            const k = keyFn(item);
            if (!map[k]) map[k] = { amount: 0, interest: 0 };
            map[k].amount   += item.amount;
            map[k].interest += item.rate * item.amount;
        }
        return map;
    };

    // ── 은행별 / 상품유형별 집계 (현재 + 전년말, 증감 비교용) ──
    const byBank     = aggregateBy(snap.items, (i) => i.institution);
    const byProd      = aggregateBy(snap.items, (i) => i.product_type || "기타");
    const prevByBank = prevSnap ? aggregateBy(prevSnap.items, (i) => i.institution) : {};
    const prevByProd = prevSnap ? aggregateBy(prevSnap.items, (i) => i.product_type || "기타") : {};
    const prevYearLabel = prevSnap ? prevSnap.base_date.split("-")[0] + "년말" : null;

    const fmtOk  = (v) => (v / 1e8).toFixed(2) + "억";
    const fmtPct = (v) => (v * 100).toFixed(3) + "%";
    const fmtShare = (v) => (v / totalAmt * 100).toFixed(1) + "%";
    const fmtDiffOk = (v) => (v >= 0 ? "▲ " : "▼ ") + fmtOk(Math.abs(v));
    const diffClass = (v) => v >= 0 ? "trend-up" : "trend-down";

    // ── 공식 박스 ──
    let html = `
        <div class="calc-formula-box">
            <div class="formula-title">계산 공식</div>
            <div class="formula-body">
                가중평균 수익률 = Σ (상품금리 × 운용금액) ÷ 총 운용자산<br>
                = <strong>${Math.round(totalInterest).toLocaleString()}원</strong>
                ÷ <strong>${Math.round(totalAmt).toLocaleString()}원</strong>
                = <strong class="text-accent">${fmtPct(weightedYield)}</strong><br>
                예상 연이자 합계 = <strong class="text-accent">${fmtOk(totalInterest)}</strong>
                (${Math.round(totalInterest).toLocaleString()}원)
            </div>
        </div>`;

    // ── 은행별 테이블 ──
    html += `<div class="calc-section-title">🏦 금융기관별 운용수익 내역</div>
        <table class="calc-table">
            <thead><tr>
                <th>금융기관</th>
                <th class="text-right">운용금액</th>
                <th class="text-right">평균 금리</th>
                <th class="text-right">예상 연이자</th>
                <th class="text-right">비중</th>
                ${prevSnap ? `<th class="text-right">${prevYearLabel} 이자</th><th class="text-right">이자 증감</th>` : ''}
            </tr></thead>
            <tbody>`;

    const bankEntries = Object.entries(byBank).sort((a, b) => b[1].amount - a[1].amount);
    let bankInterestDiffTotal = 0;
    for (const [inst, v] of bankEntries) {
        const rate = v.amount > 0 ? v.interest / v.amount : 0;
        let diffCells = '';
        if (prevSnap) {
            const prevV = prevByBank[inst] || { amount: 0, interest: 0 };
            const diff = v.interest - prevV.interest;
            bankInterestDiffTotal += diff;
            diffCells = `<td class="text-right">${fmtOk(prevV.interest)}</td>
                <td class="text-right ${diffClass(diff)}">${fmtDiffOk(diff)}</td>`;
        }
        html += `<tr>
            <td>${inst}</td>
            <td class="text-right">${fmtOk(v.amount)}</td>
            <td class="text-right">${(rate * 100).toFixed(2)}%</td>
            <td class="text-right text-accent">${fmtOk(v.interest)}</td>
            <td class="text-right">${fmtShare(v.amount)}</td>
            ${diffCells}
        </tr>`;
    }
    html += `</tbody>
        <tfoot><tr>
            <td><strong>합계</strong></td>
            <td class="text-right"><strong>${fmtOk(totalAmt)}</strong></td>
            <td class="text-right"><strong>${fmtPct(weightedYield)}</strong></td>
            <td class="text-right text-accent"><strong>${fmtOk(totalInterest)}</strong></td>
            <td class="text-right"><strong>100%</strong></td>
            ${prevSnap ? `<td></td><td class="text-right ${diffClass(bankInterestDiffTotal)}"><strong>${fmtDiffOk(bankInterestDiffTotal)}</strong></td>` : ''}
        </tr></tfoot>
        </table>`;

    // ── 상품유형별 테이블 ──
    html += `<div class="calc-section-title">📦 상품유형별 운용수익 내역</div>
        <table class="calc-table">
            <thead><tr>
                <th>상품유형</th>
                <th class="text-right">운용금액</th>
                <th class="text-right">평균 금리</th>
                <th class="text-right">예상 연이자</th>
                <th class="text-right">비중</th>
                ${prevSnap ? `<th class="text-right">${prevYearLabel} 이자</th><th class="text-right">이자 증감</th>` : ''}
            </tr></thead>
            <tbody>`;

    const prodEntries = Object.entries(byProd).sort((a, b) => b[1].amount - a[1].amount);
    for (const [pt, v] of prodEntries) {
        const rate = v.amount > 0 ? v.interest / v.amount : 0;
        let diffCells = '';
        if (prevSnap) {
            const prevV = prevByProd[pt] || { amount: 0, interest: 0 };
            const diff = v.interest - prevV.interest;
            diffCells = `<td class="text-right">${fmtOk(prevV.interest)}</td>
                <td class="text-right ${diffClass(diff)}">${fmtDiffOk(diff)}</td>`;
        }
        html += `<tr>
            <td>${pt}</td>
            <td class="text-right">${fmtOk(v.amount)}</td>
            <td class="text-right">${(rate * 100).toFixed(2)}%</td>
            <td class="text-right text-accent">${fmtOk(v.interest)}</td>
            <td class="text-right">${fmtShare(v.amount)}</td>
            ${diffCells}
        </tr>`;
    }
    html += `</tbody></table>`;
    if (!prevSnap) {
        html += `<div style="font-size:0.76rem;color:var(--text-muted);margin-top:-0.3rem;margin-bottom:0.5rem;">* 전년말 비교 데이터가 없어 증감은 표시되지 않았습니다.</div>`;
    }

    // ── 개별 상품 상세 ──
    html += `<div class="calc-section-title">📋 개별 상품 상세 (금리 × 금액 = 예상이자)</div>
        <table class="calc-table">
            <thead><tr>
                <th>금융기관</th>
                <th>상품명</th>
                <th class="text-right">금리</th>
                <th class="text-right">운용금액</th>
                <th class="text-right">예상 연이자</th>
            </tr></thead>
            <tbody>`;

    const sortedItems = [...snap.items].sort((a, b) => b.amount - a.amount);
    for (const item of sortedItems) {
        const itemInterest = item.rate * item.amount;
        const rateDisp = item.rate > 0 ? (item.rate * 100).toFixed(2) + "%" : "-";
        const intDisp  = itemInterest > 0 ? fmtOk(itemInterest) : "-";
        html += `<tr>
            <td>${item.institution}</td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${item.product}</td>
            <td class="text-right">${rateDisp}</td>
            <td class="text-right">${fmtOk(item.amount)}</td>
            <td class="text-right text-accent">${intDisp}</td>
        </tr>`;
    }
    html += `</tbody></table>`;

    body.innerHTML = html;
    overlay.style.display = "flex";
}

// ────────────────────────────────────────────────────────
// SECTION: 금융기관별 · 상품유형별 운용자산 증감 비교
// ────────────────────────────────────────────────────────
// 동일 상품(기관+상품명+만기일이 같음 = 롤오버되지 않은 동일 계좌)인데 전년 대비 금리가
// 달라진 항목을 찾는다. 확정금리형 상품은 만기일이 같으면 가입 시점 금리가 고정이므로,
// 금리가 달라졌다면 상품이 실제로 교체됐거나(정상) 둘 중 한 해의 데이터 입력 오류일 가능성이 높다.
function findRateAnomalies(snap, prevSnap) {
    if (!prevSnap) return [];
    const prevMap = {};
    for (const item of prevSnap.items) {
        if (!item.end || !item.rate) continue;
        prevMap[`${item.institution}|${item.product}|${item.end}`] = item;
    }
    const anomalies = [];
    for (const item of snap.items) {
        if (!item.end || !item.rate) continue;
        const prevItem = prevMap[`${item.institution}|${item.product}|${item.end}`];
        if (prevItem && Math.abs(prevItem.rate - item.rate) > 0.0001) {
            anomalies.push({
                institution: item.institution,
                product: item.product,
                end: item.end,
                prevRate: prevItem.rate,
                curRate: item.rate
            });
        }
    }
    return anomalies;
}

function renderRateAnomalies(snap, prevSnap) {
    const box = document.getElementById("rate-anomaly-box");
    if (!box) return;

    if (!prevSnap) {
        box.innerHTML = `<div class="rate-anomaly-box rate-anomaly-box--neutral">
            <div class="rate-anomaly-title rate-anomaly-title--neutral">ℹ️ 금리 불일치 점검</div>
            <div style="font-size:0.76rem;color:var(--text-muted);">전년말 비교 데이터가 없어 점검할 수 없습니다.</div>
        </div>`;
        return;
    }

    const anomalies = findRateAnomalies(snap, prevSnap);
    const prevYear = prevSnap.base_date.split("-")[0];

    if (anomalies.length === 0) {
        box.innerHTML = `<div class="rate-anomaly-box rate-anomaly-box--ok">
            <div class="rate-anomaly-title rate-anomaly-title--ok">✅ 금리 불일치 점검 — 이상 없음</div>
            <div style="font-size:0.76rem;color:var(--text-muted);">
                ${prevYear}년말 대비, 만기일이 동일한(=롤오버 안 된 동일 계좌) 상품의 금리 불일치가 발견되지 않았습니다.
            </div>
        </div>`;
        return;
    }
    const rows = anomalies.map(a => `
        <div class="rate-anomaly-row">
            <strong>${a.institution}</strong> · ${a.product} · 만기 ${a.end}:
            ${prevYear}년 <span class="rate-old">${(a.prevRate * 100).toFixed(2)}%</span> →
            현재 <span class="rate-new">${(a.curRate * 100).toFixed(2)}%</span>
        </div>`).join("");
    box.innerHTML = `
        <div class="rate-anomaly-box">
            <div class="rate-anomaly-title">⚠️ 금리 불일치 ${anomalies.length}건 — 확인 필요</div>
            <div style="font-size:0.76rem;color:var(--text-muted);margin-bottom:0.6rem;">
                만기일이 동일한(=롤오버 안 된 동일 계좌) 상품인데 전년 대비 금리가 달라졌습니다.
                상품이 실제로 교체된 게 아니라면 ${prevYear}년 또는 현재 금리 입력을 확인해주세요.
            </div>
            <div class="rate-anomaly-list">${rows}</div>
        </div>`;
}

function renderComparisonSection(snap, prevSnap) {
    renderRateAnomalies(snap, prevSnap);

    const container = document.getElementById("compare-grid");
    if (!container) return;

    if (!prevSnap) {
        container.innerHTML = `<div style="color:var(--text-muted);text-align:center;padding:1.5rem;grid-column:1/-1;">전년말 비교 데이터가 없습니다.</div>`;
        return;
    }

    const prevYear  = prevSnap.base_date.split("-")[0];
    const curLabel  = snap.label || activeDate;

    // ── 집계 헬퍼 ──
    const aggregate = (items, keyFn) => {
        const map = {};
        for (const item of items) {
            const k = keyFn(item);
            if (!map[k]) map[k] = { amount: 0, interest: 0 };
            map[k].amount   += item.amount;
            map[k].interest += item.rate * item.amount;
        }
        return map;
    };

    const curBank  = aggregate(snap.items,     (i) => i.institution);
    const prevBank = aggregate(prevSnap.items,  (i) => i.institution);
    const curProd  = aggregate(snap.items,     (i) => i.product_type || "기타");
    const prevProd = aggregate(prevSnap.items,  (i) => i.product_type || "기타");

    const buildRows = (curMap, prevMap) => {
        const allKeys = new Set([...Object.keys(curMap), ...Object.keys(prevMap)]);
        const sorted  = [...allKeys].sort((a, b) => (curMap[b]?.amount || 0) - (curMap[a]?.amount || 0));

        return sorted.map(key => {
            const cur  = curMap[key]  || { amount: 0, interest: 0 };
            const prev = prevMap[key] || { amount: 0, interest: 0 };
            const diffAmt  = cur.amount - prev.amount;
            const curRate  = cur.amount  > 0 ? cur.interest  / cur.amount  : 0;
            const prevRate = prev.amount > 0 ? prev.interest / prev.amount : 0;
            const diffRate = (curRate - prevRate) * 100;

            const amtSign   = diffAmt  >= 0 ? "▲" : "▼";
            const amtClass  = diffAmt  >= 0 ? "trend-up" : "trend-down";
            const rateSign  = diffRate >= 0 ? "+" : "";
            const rateClass = diffRate >= 0 ? "trend-up" : "trend-down";

            return `<tr>
                <td>${key}</td>
                <td class="text-right">${(prev.amount / 1e8).toFixed(1)}억</td>
                <td class="text-right">${(cur.amount  / 1e8).toFixed(1)}억</td>
                <td class="text-right ${amtClass}">${amtSign} ${(Math.abs(diffAmt) / 1e8).toFixed(1)}억</td>
                <td class="text-right">${(prevRate * 100).toFixed(2)}%</td>
                <td class="text-right">${(curRate  * 100).toFixed(2)}%</td>
                <td class="text-right ${rateClass}">${rateSign}${diffRate.toFixed(2)}%p</td>
            </tr>`;
        }).join("");
    };

    const headerRow = (prevYr, curLbl) => `<tr>
        <th>구분</th>
        <th class="text-right">${prevYr}년말</th>
        <th class="text-right">${curLbl}</th>
        <th class="text-right">자산 증감</th>
        <th class="text-right">${prevYr} 금리</th>
        <th class="text-right">현재 금리</th>
        <th class="text-right">금리 변동</th>
    </tr>`;

    container.innerHTML = `
        <div class="compare-sub">
            <div class="compare-sub-title">🏦 금융기관별 운용자산 증감</div>
            <div style="overflow-x:auto;">
                <table class="compare-table">
                    <thead>${headerRow(prevYear, curLabel)}</thead>
                    <tbody>${buildRows(curBank, prevBank)}</tbody>
                </table>
            </div>
        </div>
        <div class="compare-sub">
            <div class="compare-sub-title">📦 상품유형별 운용자산 증감</div>
            <div style="overflow-x:auto;">
                <table class="compare-table">
                    <thead>${headerRow(prevYear, curLabel)}</thead>
                    <tbody>${buildRows(curProd, prevProd)}</tbody>
                </table>
            </div>
        </div>`;
}
