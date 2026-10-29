// 即時看板：每 3 秒輪詢狀態，有新的辨識結果時更新畫面。
const SVG_NS = "http://www.w3.org/2000/svg";
const snapshot = $("#snapshot");
const overlay = $("#overlay");
let lastTick = null;
let lastSession = null;
let seenAlerts = new Set();
let history = {};   // 學生 → 最近的狀態列表
let state = null;

renderLegend($("#legend"));

function svg(tag, attrs, text) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text) e.textContent = text;
  return e;
}

function drawOverlay() {
  if (!state || !state.latest || !snapshot.naturalWidth) return;
  const W = snapshot.naturalWidth, H = snapshot.naturalHeight;
  overlay.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const fs = Math.max(14, W / 70);
  const byName = Object.fromEntries(state.latest.seats.map((s) => [s.name, s]));
  const nodes = [];
  for (const seat of state.layout.seats) {
    const r = byName[seat.name];
    if (!r) continue;
    const [x1, y1, x2, y2] = seat.bbox;
    const c = getComputedStyle(document.documentElement).getPropertyValue(`--s-${r.status}`).trim();
    nodes.push(svg("rect", { x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: "none", stroke: c,
      "stroke-width": fs / 5, rx: 4 }));
    const label = `${seat.name}・${r.label}`;
    nodes.push(svg("rect", { x: x1, y: y1 - fs * 1.35, width: label.length * fs * 0.95 + 8, height: fs * 1.35, fill: c, rx: 3 }));
    nodes.push(svg("text", { x: x1 + 4, y: y1 - fs * 0.35, "font-size": fs, fill: "#000", "font-weight": 600 }, label));
  }
  for (const a of state.latest.alerts) {
    if (!a.bbox) continue;
    const [x1, y1, x2, y2] = a.bbox;
    nodes.push(svg("rect", { x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: "rgba(220,38,38,.15)",
      stroke: "#dc2626", "stroke-width": fs / 4, "stroke-dasharray": `${fs} ${fs / 2}` }));
  }
  overlay.replaceChildren(...nodes);
}
snapshot.addEventListener("load", () => { $("#stage-msg").hidden = true; drawOverlay(); });

function renderControls() {
  $("#idle-controls").hidden = state.running;
  $("#run-controls").hidden = !state.running;
  if (state.running && state.session) {
    $("#session-title").textContent = state.session.title;
    $("#report-link").href = `/report/${state.session_id}`;
    const n = state.next_tick_in;
    $("#countdown").textContent = n == null ? "第一次辨識中…" : `下次辨識：${Math.ceil(n)} 秒後`;
  }
  const m = $("#control-msg");
  m.className = state.error ? "msg err" : "msg";
  m.textContent = state.error ? `辨識錯誤：${state.error}` : "";
}

function renderAlerts() {
  const list = $("#alerts");
  const alerts = [...state.alerts].reverse();
  if (!alerts.length) { list.replaceChildren(el("li", { class: "muted" }, "目前沒有警示")); return; }
  list.replaceChildren(...alerts.map((a) => el("li", { class: `alert ${a.level} ${a.acknowledged ? "acked" : ""}` },
    el("div", {}, (a.level === "danger" ? "⚠️ " : "") + a.message),
    el("div", { class: "meta" }, fmtTime(a.ts),
      a.snapshot ? el("a", { href: `/snapshots/${a.session_id}/${a.snapshot}`, target: "_blank" }, "畫面") : null,
      a.acknowledged ? "已處理" : el("button", { onclick: () => ack(a.id) }, "已處理")))));

  const fresh = state.alerts.filter((a) => !seenAlerts.has(a.id));
  if (seenAlerts.size && fresh.some((a) => a.level === "danger" && !a.acknowledged)) beep();
  state.alerts.forEach((a) => seenAlerts.add(a.id));
}

async function ack(id) { await api(`/api/alerts/${id}/ack`, { method: "POST" }); poll(); }

function beep() {
  try {
    const ac = new AudioContext();
    [0, 0.25, 0.5].forEach((t) => {
      const o = ac.createOscillator(); const g = ac.createGain();
      o.frequency.value = 880; g.gain.value = 0.15;
      o.connect(g).connect(ac.destination); o.start(ac.currentTime + t); o.stop(ac.currentTime + t + 0.15);
    });
  } catch (_) { /* 瀏覽器尚未允許播放聲音 */ }
}

function renderCards() {
  const latest = state.latest ? Object.fromEntries(state.latest.seats.map((s) => [s.name, s])) : {};
  const summary = Object.fromEntries(state.summary.map((s) => [s.student, s]));
  $("#cards").replaceChildren(...state.layout.seats.map((seat) => {
    const r = latest[seat.name];
    const sm = summary[seat.name];
    const st = r ? r.status : null;
    return el("div", { class: "card", style: st ? { "--c": statusColor(st) } : {} },
      el("div", { class: "name" }, seat.name,
        el("span", { class: "score", title: "專注度：專心讀書次數 / 可判斷次數" },
          sm && sm.focus_score != null ? `${sm.focus_score}%` : "")),
      el("div", { class: "status" }, r ? r.label : "—"),
      el("div", { class: "reason" }, r ? r.reason : ""),
      el("div", { class: "strip", title: "最近的狀態 (左舊右新)" },
        (history[seat.name] || []).slice(-30).map((s) =>
          el("i", { style: { "--c": statusColor(s) }, title: STATUS_LABEL[s] }))));
  }));
}

async function loadHistory() {
  if (!state.session_id) { history = {}; return; }
  const r = await api(`/api/report/${state.session_id}`);
  history = {};
  for (const o of r.observations) (history[o.student] ||= []).push(o.status);
}

async function poll() {
  try {
    state = await api("/api/status");
  } catch (e) {
    $("#control-msg").className = "msg err";
    $("#control-msg").textContent = `無法連線到伺服器：${e.message}`;
    return;
  }
  if (state.session_id !== lastSession) { lastSession = state.session_id; seenAlerts = new Set(); }
  const ts = state.latest && state.latest.timestamp;
  if (ts && ts !== lastTick) {
    lastTick = ts;
    $("#tick-time").textContent = fmtTime(ts);
    snapshot.src = `/snapshots/${state.session_id}/latest.jpg?t=${ts}`;
    await loadHistory();
  } else if (!state.latest) {
    $("#stage-msg").hidden = false;
    $("#stage-msg").textContent = state.running ? "第一次辨識中，請稍候…" : "尚未開始監看";
    snapshot.removeAttribute("src");
    overlay.replaceChildren();
  }
  renderControls();
  renderAlerts();
  renderCards();
}

$("#start").addEventListener("click", async () => {
  $("#start").disabled = true;
  try {
    await api("/api/session/start", { method: "POST", body: { title: $("#title").value } });
    lastTick = null;
  } catch (e) {
    $("#control-msg").className = "msg err";
    $("#control-msg").textContent = e.message;
  } finally {
    $("#start").disabled = false;
    poll();
  }
});

$("#stop").addEventListener("click", async () => {
  if (!confirm("確定結束本堂課的監看？")) return;
  $("#stop").disabled = true;
  try {
    const r = await api("/api/session/stop", { method: "POST" });
    if (r.session_id) location.href = `/report/${r.session_id}`;
  } finally {
    $("#stop").disabled = false;
  }
});

poll();
setInterval(poll, 3000);
