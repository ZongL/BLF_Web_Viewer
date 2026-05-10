/**
 * BLF Parser - Frontend Logic
 *
 * Handles file upload, signal selection, and ECharts chart rendering.
 */

// State
let blfFile = null;
let dbcFiles = [];
let sessionId = null;
let signalList = [];
let selectedSignals = new Set();
let charts = []; // kept for compatibility
let sortColumn = null;
let sortAsc = true;
let lastSignalData = null; // cached for refreshChart

// ── File Handling ──

function handleDrop(event, type) {
    event.preventDefault();
    event.currentTarget.classList.remove("drop-zone-active");
    const files = Array.from(event.dataTransfer.files);
    if (type === "blf") {
        const f = files.find(f => f.name.toLowerCase().endsWith(".blf"));
        if (f) setBlfFile(f);
    } else {
        const dbcs = files.filter(f => f.name.toLowerCase().endsWith(".dbc"));
        if (dbcs.length) setDbcFiles(dbcs);
    }
}

function handleFileSelect(event, type) {
    const files = Array.from(event.target.files);
    if (type === "blf" && files[0]) setBlfFile(files[0]);
    else if (type === "dbc" && files.length) setDbcFiles(files);
}

function setBlfFile(file) {
    blfFile = file;
    const el = document.getElementById("blf-filename");
    el.textContent = file.name;
    el.classList.remove("hidden");
    document.getElementById("blf-zone").classList.add("drop-zone-ready");
    updateAnalyzeBtn();
}

function setDbcFiles(files) {
    dbcFiles = files;
    const el = document.getElementById("dbc-filenames");
    el.textContent = files.map(f => f.name).join(", ");
    el.classList.remove("hidden");
    document.getElementById("dbc-zone").classList.add("drop-zone-ready");
    updateAnalyzeBtn();
}

function updateAnalyzeBtn() {
    document.getElementById("analyze-btn").disabled = !(blfFile && dbcFiles.length);
}

// ── Upload & Parse ──

async function analyzeFiles() {
    const btn = document.getElementById("analyze-btn");
    const progress = document.getElementById("progress");
    const errorEl = document.getElementById("upload-error");
    const progressBar = document.getElementById("progress-bar");
    const progressPct = document.getElementById("progress-pct");
    const progressText = document.getElementById("progress-text");
    const progressDetail = document.getElementById("progress-detail");

    btn.disabled = true;
    progress.classList.remove("hidden");
    errorEl.classList.add("hidden");

    // Reset progress bar
    progressBar.style.width = "0%";
    progressPct.textContent = "0%";
    progressText.textContent = "Uploading files...";
    progressDetail.textContent = "";

    const formData = new FormData();
    formData.append("blf_file", blfFile);
    for (const dbc of dbcFiles) {
        formData.append("dbc_files", dbc);
    }

    try {
        // Step 1: Upload files (returns session_id immediately)
        const resp = await fetch("/api/upload", { method: "POST", body: formData });
        const data = await resp.json();

        if (!resp.ok) {
            throw new Error(data.error || "Upload failed");
        }

        const sid = data.session_id;
        progressText.textContent = "Parsing BLF file...";
        progressBar.style.width = "5%";
        progressPct.textContent = "5%";

        // Step 2: Poll progress
        const result = await pollProgress(sid, progressBar, progressPct, progressText, progressDetail);

        sessionId = result.session_id;
        signalList = result.signals;
        showSignalSelector(result);
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove("hidden");
        btn.disabled = false;
    } finally {
        progress.classList.add("hidden");
    }
}

const PHASE_LABELS = {
    uploading: "Uploading files...",
    loading_dbc: "Loading DBC definitions...",
    parsing: "Parsing CAN messages...",
    finalizing: "Building signal data...",
};

async function pollProgress(sessionId, barEl, pctEl, textEl, detailEl) {
    return new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
            try {
                const resp = await fetch(`/api/progress/${sessionId}`);
                const info = await resp.json();

                if (!resp.ok) {
                    clearInterval(interval);
                    reject(new Error(info.error || "Progress check failed"));
                    return;
                }

                // Update UI based on phase
                const label = PHASE_LABELS[info.phase] || info.phase;
                textEl.textContent = label;

                if (info.phase === "parsing" && info.total > 0) {
                    // Progress is 5%-90% during parsing
                    const rawPct = Math.min(info.current / info.total, 1);
                    const pct = Math.round(5 + rawPct * 85);
                    barEl.style.width = pct + "%";
                    pctEl.textContent = pct + "%";
                    const currentK = (info.current / 1000).toFixed(0);
                    detailEl.textContent = `${currentK}k messages processed`;
                } else if (info.phase === "loading_dbc") {
                    barEl.style.width = "3%";
                    pctEl.textContent = "3%";
                    detailEl.textContent = "";
                } else if (info.phase === "finalizing") {
                    barEl.style.width = "92%";
                    pctEl.textContent = "92%";
                    detailEl.textContent = "Normalizing and computing statistics...";
                }

                if (info.done) {
                    clearInterval(interval);
                    barEl.style.width = "100%";
                    pctEl.textContent = "100%";
                    textEl.textContent = "Done!";
                    detailEl.textContent = "";

                    if (info.error) {
                        reject(new Error(info.error));
                    } else {
                        // Brief pause to show 100%
                        setTimeout(() => resolve(info.result), 300);
                    }
                }
            } catch (err) {
                clearInterval(interval);
                reject(err);
            }
        }, 300);
    });
}

// ── Signal Selector ──

function showSignalSelector(data) {
    document.getElementById("phase-upload").classList.add("hidden");
    document.getElementById("phase-signals").classList.remove("hidden");

    // Summary
    document.getElementById("summary-msgs").textContent = data.summary.msg_count.toLocaleString();
    const dur = data.summary.duration;
    document.getElementById("summary-duration").textContent =
        dur >= 60 ? `${(dur / 60).toFixed(1)}m` : `${dur.toFixed(1)}s`;
    document.getElementById("summary-channels").textContent = data.summary.channels.length;

    // Undecoded IDs
    if (data.undecoded_ids.length > 0) {
        const warning = document.getElementById("undecoded-warning");
        warning.classList.remove("hidden");
        const ids = data.undecoded_ids.map(u => `${u.arbitration_id} (${u.count}x)`).join(", ");
        document.getElementById("undecoded-list").textContent = ids;
    }

    selectedSignals.clear();
    renderSignalTable(signalList);
}

function renderSignalTable(signals) {
    const tbody = document.getElementById("signal-tbody");
    tbody.innerHTML = "";

    for (const sig of signals) {
        const tr = document.createElement("tr");
        if (selectedSignals.has(sig.key)) tr.classList.add("selected");

        tr.innerHTML = `
            <td class="px-4 py-2"><input type="checkbox" data-key="${sig.key}" ${selectedSignals.has(sig.key) ? "checked" : ""} onchange="toggleSignal('${sig.key}', this.checked, this.closest('tr'))"></td>
            <td class="px-4 py-2 text-gray-600 font-mono text-xs">${esc(sig.message_name)}</td>
            <td class="px-4 py-2 text-gray-800">${esc(sig.signal_name)}</td>
            <td class="px-4 py-2 text-gray-500">${sig.channel ?? "-"}</td>
            <td class="px-4 py-2 text-gray-500">${esc(sig.unit)}</td>
            <td class="px-4 py-2 text-gray-700 text-right">${sig.samples.toLocaleString()}</td>
            <td class="px-4 py-2 text-gray-500 text-right">${sig.min}</td>
            <td class="px-4 py-2 text-gray-500 text-right">${sig.max}</td>
        `;
        tbody.appendChild(tr);
    }
}

function toggleSignal(key, checked, tr) {
    if (checked) {
        selectedSignals.add(key);
        tr.classList.add("selected");
    } else {
        selectedSignals.delete(key);
        tr.classList.remove("selected");
    }
    updateSelectedCount();
}

function selectAll(checked) {
    const search = document.getElementById("signal-search").value.toLowerCase();
    const filtered = signalList.filter(s =>
        !search || s.message_name.toLowerCase().includes(search) || s.signal_name.toLowerCase().includes(search)
    );

    for (const sig of filtered) {
        if (checked) selectedSignals.add(sig.key);
        else selectedSignals.delete(sig.key);
    }

    document.getElementById("check-all").checked = checked;
    document.querySelectorAll("#signal-tbody input[type=checkbox]").forEach(cb => {
        cb.checked = checked;
        cb.closest("tr").classList.toggle("selected", checked);
    });
    updateSelectedCount();
}

function updateSelectedCount() {
    const count = selectedSignals.size;
    document.getElementById("selected-count").textContent = `${count} signal${count !== 1 ? "s" : ""} selected`;
    document.getElementById("chart-btn").disabled = count === 0;
}

function filterSignals() {
    const search = document.getElementById("signal-search").value.toLowerCase();
    const filtered = signalList.filter(s =>
        s.message_name.toLowerCase().includes(search) || s.signal_name.toLowerCase().includes(search)
    );
    renderSignalTable(filtered);
}

function sortTable(column) {
    if (sortColumn === column) {
        sortAsc = !sortAsc;
    } else {
        sortColumn = column;
        sortAsc = true;
    }

    signalList.sort((a, b) => {
        let va = a[column], vb = b[column];
        if (typeof va === "string") {
            return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        return sortAsc ? va - vb : vb - va;
    });

    filterSignals();
}

// ── Chart ──

const COLORS = [
    "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#f97316", "#6366f1", "#14b8a6",
    "#e11d48", "#84cc16", "#0ea5e9", "#a855f7", "#64748b",
];

let mainChart = null;

async function showChart() {
    const loading = document.getElementById("signal-loading");
    loading.classList.remove("hidden");
    document.getElementById("chart-btn").disabled = true;

    const maxPoints = parseInt(document.getElementById("max-points").value);

    try {
        const resp = await fetch("/api/signals", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: sessionId,
                signals: Array.from(selectedSignals),
                max_points: maxPoints,
            }),
        });
        const data = await resp.json();

        if (!resp.ok) throw new Error(data.error || "Failed to load signals");

        lastSignalData = data.signals;

        document.getElementById("phase-signals").classList.add("hidden");
        document.getElementById("phase-chart").classList.remove("hidden");

        renderCharts(data.signals);
    } catch (err) {
        alert("Error: " + err.message);
        document.getElementById("chart-btn").disabled = false;
    } finally {
        loading.classList.add("hidden");
    }
}

function renderCharts(signalData) {
    const wrapper = document.getElementById("charts-wrapper");
    wrapper.innerHTML = "";

    if (mainChart) mainChart.dispose();

    const keys = Object.keys(signalData);
    const n = keys.length;

    // Calculate container height: each panel ~120px + 40px for bottom slider
    const panelHeight = 120;
    const sliderSpace = 45;
    const totalHeight = n * panelHeight + sliderSpace;
    wrapper.style.height = totalHeight + "px";

    mainChart = echarts.init(wrapper);

    const grids = [];
    const xAxes = [];
    const yAxes = [];
    const series = [];
    const graphicElements = [];
    const axisPointerLinks = [];

    // Gap between panels
    const gap = 8;
    const leftMargin = 50;
    const rightMargin = 20;

    keys.forEach((key, idx) => {
        const sig = signalData[key];
        const color = COLORS[idx % COLORS.length];
        const label = sig.unit ? `${key} [${sig.unit}]` : key;
        const isLast = idx === n - 1;

        // Each grid is a horizontal strip
        const topPx = idx * panelHeight;
        const heightPx = panelHeight - gap;

        grids.push({
            left: leftMargin,
            right: rightMargin,
            top: topPx,
            height: heightPx,
        });

        xAxes.push({
            type: "value",
            gridIndex: idx,
            // Only show axis label and name on the last panel
            axisLabel: { show: isLast, color: "#6b7280", fontSize: 10 },
            axisLine: { lineStyle: { color: "#e5e7eb" } },
            axisTick: { show: isLast },
            splitLine: { lineStyle: { color: "#f3f4f6" } },
            name: isLast ? "Time (s)" : "",
            nameTextStyle: { color: "#9ca3af", fontSize: 10 },
            nameGap: 22,
        });

        yAxes.push({
            type: "value",
            gridIndex: idx,
            axisLine: { show: true, lineStyle: { color: color } },
            axisLabel: { color: "#6b7280", fontSize: 9, margin: 4 },
            splitLine: { lineStyle: { color: "#f3f4f6" } },
            splitNumber: 3,
        });

        // Signal name label at top-right of each panel
        graphicElements.push({
            type: "text",
            right: rightMargin + 8,
            top: topPx + 4,
            style: {
                text: label,
                fill: color,
                fontSize: 11,
                fontWeight: "bold",
                textAlign: "right",
            },
            z: 100,
        });

        series.push({
            type: "line",
            xAxisIndex: idx,
            yAxisIndex: idx,
            showSymbol: false,
            sampling: "lttb",
            large: true,
            lineStyle: { color: color, width: 1.2 },
            itemStyle: { color: color },
            data: sig.timestamps.map((t, i) => [t, sig.values[i]]),
        });
    });

    // Link all x-axes for synchronized crosshair
    axisPointerLinks.push({ xAxisIndex: keys.map((_, i) => i) });

    const option = {
        animation: false,
        tooltip: {
            trigger: "axis",
            axisPointer: {
                type: "line",
                lineStyle: { color: "#d1d5db", type: "dashed" },
                link: axisPointerLinks,
            },
            backgroundColor: "#fff",
            borderColor: "#e5e7eb",
            textStyle: { color: "#374151", fontSize: 11 },
        },
        axisPointer: {
            link: axisPointerLinks,
        },
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        graphic: graphicElements,
        // Single shared dataZoom controlling all x-axes
        dataZoom: [
            {
                type: "slider",
                xAxisIndex: keys.map((_, i) => i),
                bottom: 5,
                height: 22,
                borderColor: "#e5e7eb",
                backgroundColor: "#f9fafb",
                fillerColor: "rgba(59,130,246,0.12)",
                handleStyle: { color: "#3b82f6" },
                textStyle: { color: "#6b7280", fontSize: 10 },
            },
            {
                type: "inside",
                xAxisIndex: keys.map((_, i) => i),
            },
        ],
        series: series,
    };

    mainChart.setOption(option);

    window.addEventListener("resize", () => mainChart && mainChart.resize());
}

function resetZoom() {
    if (mainChart) {
        mainChart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
    }
}

async function refreshChart() {
    await showChart();
}

// ── Navigation ──

function backToUpload() {
    document.getElementById("phase-signals").classList.add("hidden");
    document.getElementById("phase-upload").classList.remove("hidden");
    document.getElementById("analyze-btn").disabled = false;
}

function backToSignals() {
    document.getElementById("phase-chart").classList.add("hidden");
    document.getElementById("phase-signals").classList.remove("hidden");
    document.getElementById("chart-btn").disabled = selectedSignals.size === 0;
    if (mainChart) { mainChart.dispose(); mainChart = null; }
}

// ── Utilities ──

function esc(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
