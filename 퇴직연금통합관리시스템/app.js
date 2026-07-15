// app.js - Pension Dashboard Interaction and Chart.js integration

// Register the datalabels plugin globally
Chart.register(ChartDataLabels);

// Disable datalabels by default for all charts to prevent clutter on bar/line charts
Chart.defaults.set('plugins.datalabels', {
    display: false
});

// Custom plugin to draw connector lines from slices to outside labels
const customConnectorLinesPlugin = {
    id: 'customConnectorLines',
    afterDraw(chart) {
        const ctx = chart.ctx;
        ctx.save();
        
        const dataset = chart.data.datasets[0];
        const meta = chart.getDatasetMeta(0);
        if (!meta.data || meta.data.length === 0) return;
        
        const total = dataset.data.reduce((acc, val) => acc + val, 0);
        
        meta.data.forEach((arc, index) => {
            const rawValue = dataset.data[index];
            const ratio = rawValue / (total || 1);
            if (ratio < 0.0001) return; // Hide lines only for extremely tiny or zero slices
            
            const midAngle = arc.startAngle + (arc.endAngle - arc.startAngle) / 2;
            
            // Start of line (outer edge of slice)
            const startX = arc.x + Math.cos(midAngle) * arc.outerRadius;
            const startY = arc.y + Math.sin(midAngle) * arc.outerRadius;
            
            // End of line extension
            const lineLength = 16;
            const endX = arc.x + Math.cos(midAngle) * (arc.outerRadius + lineLength);
            const endY = arc.y + Math.sin(midAngle) * (arc.outerRadius + lineLength);
            
            // Draw line
            ctx.beginPath();
            ctx.moveTo(startX, startY);
            ctx.lineTo(endX, endY);
            
            // Horizontal elbow line
            const isRightSide = Math.cos(midAngle) > 0;
            const horizLength = 8;
            const textX = endX + (isRightSide ? horizLength : -horizLength);
            ctx.lineTo(textX, endY);
            
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
            ctx.lineWidth = 1.2;
            ctx.stroke();
        });
        
        ctx.restore();
    }
};

let pensionData = null;
let activeDate = null;
let useMillionUnit = false;
let activeInstFilter = null;  // 기관별 파이차트 클릭 필터
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

    // Snapshot Select
    document.getElementById("snapshot-select").addEventListener("change", (e) => {
        activeDate = e.target.value;
        activeInstFilter = null;   // 기준일 변경 시 필터 초기화
        filterMaturingThisYear = false;
        document.getElementById("maturing-this-year-btn").classList.remove("active");
        updateDashboard();
    });

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
        filterMaturingThisYear = false;
        document.getElementById("table-filter-badge").style.display = "none";
        document.getElementById("maturing-this-year-btn").classList.remove("active");
        document.getElementById("table-search-input").value = "";
        renderTable();
        // 차트 하이라이트 해제
        if (chartInst) chartInst.update();
    });
});

// ────────────────────────────────────────────────────────
// Dashboard Init
// ────────────────────────────────────────────────────────
function initDashboard() {
    const snapSelect = document.getElementById("snapshot-select");
    snapSelect.innerHTML = "";

    const now = new Date();
    const oneYearAgo = new Date(now);
    oneYearAgo.setFullYear(now.getFullYear() - 1);

    // 날짜 내림차순 정렬
    const sortedDates = Object.keys(pensionData.snapshots).sort((a, b) => b.localeCompare(a));

    const recentGroup = document.createElement("optgroup");
    recentGroup.label = "▼ 최근 1개년 (상세 조회)";
    const histGroup = document.createElement("optgroup");
    histGroup.label = "▼ 과거 참고 자료";

    sortedDates.forEach(dateStr => {
        const snap = pensionData.snapshots[dateStr];
        const opt = document.createElement("option");
        opt.value = dateStr;
        opt.textContent = snap.label;

        const snapDate = new Date(dateStr);
        if (snapDate >= oneYearAgo) {
            recentGroup.appendChild(opt);
        } else {
            histGroup.appendChild(opt);
        }
    });

    if (recentGroup.children.length > 0) snapSelect.appendChild(recentGroup);
    if (histGroup.children.length > 0) snapSelect.appendChild(histGroup);

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
        plugins: [customConnectorLinesPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: 50
            },
            onClick: (event, elements) => {
                if (elements.length > 0) {
                    const idx = elements[0].index;
                    const instName = labels[idx];
                    if (activeInstFilter === instName) {
                        // 동일 항목 재클릭 → 필터 해제
                        activeInstFilter = null;
                        document.getElementById("table-filter-badge").style.display = "none";
                    } else {
                        activeInstFilter = instName;
                        const badge = document.getElementById("table-filter-badge");
                        badge.textContent = `🔍 ${instName} 필터 적용 중`;
                        badge.style.display = "inline-flex";
                    }
                    document.getElementById("table-search-input").value = "";
                    renderTable();
                    // 테이블로 스크롤
                    document.querySelector(".table-section").scrollIntoView({ behavior: "smooth", block: "start" });
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
                    display: true,
                    anchor: 'end',
                    align: 'end',
                    offset: 16,
                    formatter: (value, context) => {
                        const rawAmount = snap.institution_distribution[context.dataIndex].amount;
                        const percentage = (snap.institution_distribution[context.dataIndex].ratio * 100).toFixed(1) + "%";
                        const okUnit = (rawAmount / 100000000).toFixed(1);

                        // 0.01% 미만 슬라이스는 라벨 숨김
                        const ratio = rawAmount / (snap.total_amount || 1);
                        if (ratio < 0.0001) return null;

                        return `${context.chart.data.labels[context.dataIndex]}\n${okUnit}억 (${percentage})`;
                    },
                    color: '#e2e8f0',
                    font: {
                        family: 'Inter, Noto Sans KR',
                        size: 8.5,
                        weight: '600'
                    },
                    textAlign: 'center',
                    textShadowColor: 'rgba(0, 0, 0, 0.9)',
                    textShadowBlur: 3
                }
            }
        }
    });

    // 2열 커스텀 범례 생성
    generateCustomLegend("legend-institution", chartInst, (instName, index) => {
        if (activeInstFilter === instName) {
            activeInstFilter = null;
            document.getElementById("table-filter-badge").style.display = "none";
        } else {
            activeInstFilter = instName;
            const badge = document.getElementById("table-filter-badge");
            badge.textContent = `🔍 ${instName} 필터 적용 중`;
            badge.style.display = "inline-flex";
        }
        document.getElementById("table-search-input").value = "";
        renderTable();
        document.querySelector(".table-section").scrollIntoView({ behavior: "smooth", block: "start" });
    });
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
        plugins: [customConnectorLinesPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: 50
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
                    display: true,
                    anchor: 'end',
                    align: 'end',
                    offset: 16,
                    formatter: (value, context) => {
                        const item = dist[context.dataIndex];
                        const rawAmount = item.amount;
                        const percentage = (item.ratio * 100).toFixed(1) + "%";
                        const okUnit = (rawAmount / 100000000).toFixed(1);

                        // 0.01% 미만 슬라이스는 라벨 숨김
                        const ratio = rawAmount / (snap.total_amount || 1);
                        if (ratio < 0.0001) return null;

                        // ELB/DLB 포함 모든 항목에 이름 + 금액 + % 표기
                        const labelName = context.chart.data.labels[context.dataIndex];
                        return `${labelName}\n${okUnit}억 (${percentage})`;
                    },
                    color: '#e2e8f0',
                    font: {
                        family: 'Inter, Noto Sans KR',
                        size: 8.5,
                        weight: '600'
                    },
                    textAlign: 'center',
                    textShadowColor: 'rgba(0, 0, 0, 0.9)',
                    textShadowBlur: 3
                }
            }
        }
    });

    // 2열 커스텀 범례 생성
    generateCustomLegend("legend-product", chartProd);
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
                x: { grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#94a3b8' } },
                y: {
                    type: 'linear', position: 'left',
                    grid: { color: 'rgba(255,255,255,0.03)' },
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
                x: { grid: { color: 'rgba(255,255,255,0.03)' }, ticks: { color: '#94a3b8' } },
                y: {
                    type: 'linear', position: 'left',
                    grid: { color: 'rgba(255,255,255,0.03)' },
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
