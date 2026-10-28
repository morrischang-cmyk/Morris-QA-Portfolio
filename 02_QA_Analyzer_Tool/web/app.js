const $ = (id) => document.getElementById(id);

const state = {
  months: [],
  currentMonth: "",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "請求失敗。");
  return payload;
}

function availableYears() {
  return [...new Set(state.months.map((value) => value.slice(0, 4)))].sort().reverse();
}

function renderPerformanceYearOptions() {
  const select = $("performanceYearSelect");
  select.replaceChildren();
  for (const year of availableYears()) {
    const option = document.createElement("option");
    option.value = year;
    option.textContent = `${year} 年`;
    select.append(option);
  }
  const preferred = state.months.includes(state.currentMonth)
    ? state.currentMonth.slice(0, 4)
    : state.months.at(-1)?.slice(0, 4);
  if (preferred) select.value = preferred;
  renderPerformanceMonthOptions();
}

function renderPerformanceMonthOptions() {
  const year = $("performanceYearSelect").value;
  const select = $("performanceMonthSelect");
  const choices = state.months.filter((value) => value.startsWith(year));
  select.replaceChildren();
  for (const value of choices) {
    const option = document.createElement("option");
    option.value = value.slice(4, 6);
    option.textContent = `${Number(value.slice(4, 6))} 月`;
    select.append(option);
  }
  const preferred = state.currentMonth.startsWith(year)
    ? state.currentMonth.slice(4, 6)
    : choices.at(-1)?.slice(4, 6);
  if (preferred) select.value = preferred;
}

function formatLocalDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function setPerformanceStatus(message = "", pending = false) {
  const box = $("performanceStatus");
  box.textContent = message;
  box.classList.toggle("hidden", !message);
  box.classList.toggle("pending", pending);
}

function setPerformanceBusy(busy) {
  const button = $("performanceButton");
  button.disabled = busy;
  button.textContent = busy ? "整合 Jira 與表單中…" : "產生月份報告";
}

function renderMemberChart(rows) {
  const chart = $("memberChart");
  chart.replaceChildren();
  const visible = rows.filter((row) => row.workload > 0);
  const max = Math.max(1, ...visible.map((row) => Math.max(row.tasks, row.bugs, row.log_days)));
  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "這個區間沒有工作量資料";
    chart.append(empty);
    return;
  }

  for (const row of visible) {
    const item = document.createElement("div");
    item.className = "member-bar-row";
    const name = document.createElement("span");
    name.className = "member-bar-name";
    name.textContent = row.name;
    const bars = document.createElement("div");
    bars.className = "member-bars";
    for (const [kind, value] of [["task", row.tasks], ["bug", row.bugs], ["log", row.log_days]]) {
      const track = document.createElement("div");
      track.className = "member-track";
      const fill = document.createElement("div");
      fill.className = `member-fill ${kind}`;
      fill.style.width = `${(value / max) * 100}%`;
      track.append(fill);
      bars.append(track);
    }
    const total = document.createElement("span");
    total.className = "member-bar-total";
    total.textContent = row.workload;
    item.append(name, bars, total);
    chart.append(item);
  }
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function renderTrendChart(rows) {
  const host = $("trendChart");
  host.replaceChildren();
  const width = 680;
  const height = 310;
  const padding = { left: 38, right: 18, top: 24, bottom: 38 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const max = Math.max(1, ...rows.flatMap((row) => [row.tasks, row.bugs, row.log_days]));
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none" });

  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + (plotHeight * index) / 4;
    svg.append(svgElement("line", { x1: padding.left, x2: width - padding.right, y1: y, y2: y, class: "trend-grid" }));
    const label = svgElement("text", { x: 5, y: y + 4, class: "trend-axis-label" });
    label.textContent = Math.round(max * (1 - index / 4));
    svg.append(label);
  }

  const point = (row, index, key) => {
    const x = padding.left + (plotWidth * index) / Math.max(1, rows.length - 1);
    const y = padding.top + plotHeight - (row[key] / max) * plotHeight;
    return [x, y];
  };
  const linePoints = (key) => rows.map((row, index) => point(row, index, key).join(",")).join(" ");
  svg.append(svgElement("polyline", { points: linePoints("tasks"), class: "trend-task-line" }));
  svg.append(svgElement("polyline", { points: linePoints("bugs"), class: "trend-bug-line" }));
  svg.append(svgElement("polyline", { points: linePoints("log_days"), class: "trend-log-line" }));

  rows.forEach((row, index) => {
    if (row.tasks > 0) {
      const [x, y] = point(row, index, "tasks");
      svg.append(svgElement("circle", { cx: x, cy: y, r: 3.5, class: "trend-dot-task" }));
    }
    if (row.bugs > 0) {
      const [x, y] = point(row, index, "bugs");
      svg.append(svgElement("circle", { cx: x, cy: y, r: 3.5, class: "trend-dot-bug" }));
    }
    if (row.log_days > 0) {
      const [x, y] = point(row, index, "log_days");
      svg.append(svgElement("circle", { cx: x, cy: y, r: 3.5, class: "trend-dot-log" }));
    }
  });

  const labelIndexes = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
  for (const index of labelIndexes) {
    if (!rows[index]) continue;
    const x = padding.left + (plotWidth * index) / Math.max(1, rows.length - 1);
    const label = svgElement("text", { x, y: height - 12, "text-anchor": index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle", class: "trend-axis-label" });
    label.textContent = rows[index].date.slice(5);
    svg.append(label);
  }
  host.append(svg);
}

function renderPerformanceTable(rows) {
  const body = $("performanceBody");
  body.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const value of [row.name, row.bugs, row.manual, row.automation, row.tasks, row.log_days.toFixed(2), row.workload]) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    body.append(tr);
  }
}

function renderDonut(hostId, segments, centerLabel) {
  const host = $(hostId);
  host.replaceChildren();
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  let cursor = 0;
  const stops = segments.map((segment) => {
    const start = cursor;
    cursor += total ? (segment.value / total) * 100 : 0;
    return `${segment.color} ${start}% ${cursor}%`;
  });

  const chart = document.createElement("div");
  chart.className = "donut-chart";
  chart.style.background = total ? `conic-gradient(${stops.join(", ")})` : "#35465f";
  const hole = document.createElement("div");
  hole.className = "donut-hole";
  const totalElement = document.createElement("strong");
  totalElement.textContent = total;
  const labelElement = document.createElement("span");
  labelElement.textContent = centerLabel;
  hole.append(totalElement, labelElement);
  chart.append(hole);

  const legend = document.createElement("div");
  legend.className = "donut-legend";
  for (const segment of segments) {
    const row = document.createElement("div");
    row.className = "donut-legend-row";
    const swatch = document.createElement("span");
    swatch.className = "donut-swatch";
    swatch.style.background = segment.color;
    const label = document.createElement("span");
    label.className = "donut-label";
    label.textContent = segment.label;
    const value = document.createElement("span");
    value.className = "donut-value";
    const percent = total ? Math.round((segment.value / total) * 100) : 0;
    value.textContent = `${segment.value} · ${percent}%`;
    row.append(swatch, label, value);
    legend.append(row);
  }
  host.append(chart, legend);
}

function renderBugTaskRatio(data) {
  const overallRatio = data.task_total ? data.bug_total / data.task_total : 0;
  $("departmentBugTaskRatio").textContent = overallRatio.toFixed(2);
  const rows = [...data.members]
    .map((row) => ({ ...row, ratio: row.tasks ? row.bugs / row.tasks : null }))
    .sort((a, b) => (b.ratio ?? -1) - (a.ratio ?? -1));
  const maxRatio = Math.max(1, ...rows.filter((row) => row.ratio !== null).map((row) => row.ratio));
  const chart = $("bugTaskRatioChart");
  chart.replaceChildren();
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "ratio-row";
    const name = document.createElement("span");
    name.className = "ratio-name";
    name.textContent = row.name;
    const track = document.createElement("div");
    track.className = "ratio-track";
    const fill = document.createElement("div");
    fill.className = "ratio-fill";
    fill.style.width = row.ratio === null ? "0" : `${(row.ratio / maxRatio) * 100}%`;
    track.append(fill);
    const value = document.createElement("span");
    value.className = "ratio-value";
    value.textContent = row.ratio === null ? "—" : row.ratio.toFixed(2);
    item.append(name, track, value);
    chart.append(item);
  }
}

function renderReportVisuals(data) {
  renderDonut("workTypeDonut", [
    { label: "手動任務", value: data.manual_total, color: "#4f86ff" },
    { label: "自動化任務", value: data.automation_total, color: "#a45af0" },
  ], "總任務數");

  const ranked = [...data.members].sort((a, b) => b.workload - a.workload || a.name.localeCompare(b.name));
  const memberSegments = ranked.map((row, index) => ({
    label: row.name,
    value: row.workload,
    color: `hsl(${(215 + index * 47) % 360} 72% 62%)`,
  }));
  renderDonut("memberShareDonut", memberSegments, "工作量");
  renderBugTaskRatio(data);

  const peaks = data.daily
    .filter((row) => row.tasks > 0)
    .sort((a, b) => b.tasks - a.tasks || a.date.localeCompare(b.date))
    .slice(0, 6)
    .map((row) => ({ date: row.date.slice(5), count: row.tasks }));
  const list = $("reportPeakList");
  list.replaceChildren();
  if (!peaks.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "這個月份沒有發測資料";
    list.append(empty);
  } else {
    const max = Math.max(...peaks.map((row) => row.count));
    for (const row of peaks) {
      const item = document.createElement("div");
      item.className = "peak-row";
      item.innerHTML = `<span class="peak-date">${row.date}</span><div class="peak-track"><div class="peak-bar" style="width:${Math.max(8, (row.count / max) * 100)}%"></div></div><span class="peak-count">${row.count}</span>`;
      list.append(item);
    }
  }
}

function renderPerformanceSources(data) {
  const container = $("performanceSourcePills");
  container.replaceChildren();
  const jira = document.createElement("span");
  jira.className = "source-pill jira";
  jira.textContent = "Jira 即時資料";
  container.append(jira);
  for (const source of data.task_source_sheets) {
    const pill = document.createElement("span");
    pill.className = `source-pill${source.startsWith("進行中") ? " live" : ""}`;
    pill.textContent = source;
    container.append(pill);
  }
}

function renderPerformance(data) {
  const [year, month] = data.start_date.split("-");
  $("performanceTitle").textContent = `${year} 年 ${Number(month)} 月 QA 部門報告`;
  $("performanceBugTotal").textContent = data.bug_total;
  $("performanceTaskTotal").textContent = data.task_total;
  $("performanceManualTotal").textContent = data.manual_total;
  $("performanceAutomationTotal").textContent = data.automation_total;
  const workdays = data.daily.filter((row) => {
    const weekday = new Date(`${row.date}T00:00:00Z`).getUTCDay();
    return weekday >= 1 && weekday <= 5;
  }).length;
  $("performanceAvgPerDay").textContent = (data.task_total / Math.max(1, workdays)).toFixed(2);
  $("performanceWorkdays").textContent = `${workdays} 個工作日`;
  $("performanceLogDays").textContent = data.worklog_total_days.toFixed(2);
  $("performanceActive").textContent = data.active_members;
  renderPerformanceSources(data);
  renderReportVisuals(data);
  renderMemberChart(data.members);
  renderTrendChart(data.daily);
  renderPerformanceTable(data.members);
  $("performanceResults").classList.remove("hidden");
}

async function analyzePerformance() {
  const year = Number($("performanceYearSelect").value);
  const month = Number($("performanceMonthSelect").value);
  if (!year || !month) {
    setPerformanceStatus("請選擇績效統計年份與月份。");
    return false;
  }
  const today = new Date();
  const startDate = `${year}-${String(month).padStart(2, "0")}-01`;
  const selectedIsCurrentMonth = year === today.getFullYear() && month === today.getMonth() + 1;
  const endDate = selectedIsCurrentMonth
    ? formatLocalDate(today)
    : formatLocalDate(new Date(year, month, 0));
  setPerformanceBusy(true);
  setPerformanceStatus("正在查詢 Jira BUG、Worklog 並整合 Google Sheets 任務…", true);
  try {
    const data = await api("/api/performance", {
      method: "POST",
      body: JSON.stringify({ start_date: startDate, end_date: endDate }),
    });
    renderPerformance(data);
    setPerformanceStatus("");
    return true;
  } catch (error) {
    setPerformanceStatus(error.message);
    return false;
  } finally {
    setPerformanceBusy(false);
  }
}

async function savePdf() {
  const button = $("savePdfButton");
  const year = $("performanceYearSelect").value;
  const month = $("performanceMonthSelect").value;
  button.disabled = true;
  button.textContent = "正在產生 PDF…";
  try {
    const response = await fetch(`/api/export-pdf?year=${encodeURIComponent(year)}&month=${encodeURIComponent(month)}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "PDF 產生失敗。");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `QA_部門報告_${year}${String(month).padStart(2, "0")}.pdf`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    setPerformanceStatus(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "儲存 PDF";
  }
}

async function init() {
  setPerformanceBusy(true);
  setPerformanceStatus("正在讀取可用月份…", true);
  try {
    const config = await api("/api/months");
    state.months = config.months;
    state.currentMonth = config.current_month;
    renderPerformanceYearOptions();
    setPerformanceStatus("");
    const params = new URLSearchParams(window.location.search);
    if (params.get("pdf_capture") === "1") {
      document.body.classList.add("pdf-capture");
      const year = params.get("year");
      const month = String(Number(params.get("month"))).padStart(2, "0");
      if ([...$("performanceYearSelect").options].some((option) => option.value === year)) {
        $("performanceYearSelect").value = year;
        renderPerformanceMonthOptions();
      }
      if ([...$("performanceMonthSelect").options].some((option) => option.value === month)) {
        $("performanceMonthSelect").value = month;
      }
      const complete = await analyzePerformance();
      document.documentElement.dataset.pdfReady = complete ? "true" : "error";
    }
  } catch (error) {
    setPerformanceStatus(error.message);
  } finally {
    setPerformanceBusy(false);
  }
}

$("performanceButton").addEventListener("click", analyzePerformance);
$("performanceYearSelect").addEventListener("change", renderPerformanceMonthOptions);
$("savePdfButton").addEventListener("click", savePdf);
init();
