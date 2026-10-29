// 課後報表
renderLegend($("#legend"));

const PROBLEMS = ["phone", "sleeping", "distracted", "active", "absent"];

(async () => {
  const r = await api(`/api/report/${window.SESSION_ID}`);

  $("#summary tbody").replaceChildren(...r.summary.map((s) => {
    const worst = PROBLEMS.filter((p) => s.counts[p])
      .sort((a, b) => s.counts[b] - s.counts[a])
      .slice(0, 2)
      .map((p) => `${STATUS_LABEL[p]} ${s.counts[p]} 次`);
    return el("tr", {},
      el("td", {}, s.student),
      el("td", {}, s.focus_score == null ? "—" : `${s.focus_score}%`),
      el("td", {}, el("div", { class: "bar" },
        window.STATUSES.filter((st) => s.ratios[st.value]).map((st) =>
          el("i", { style: { "--c": statusColor(st.value), width: `${s.ratios[st.value] * 100}%` },
            title: `${st.label} ${Math.round(s.ratios[st.value] * 100)}%` })))),
      el("td", {}, worst.join("、") || "—"));
  }));

  // 時間軸：每列一位學生，每格一次辨識
  const times = [...new Set(r.observations.map((o) => o.ts))].sort((a, b) => a - b);
  const idx = Object.fromEntries(times.map((t, i) => [t, i]));
  const rows = {};
  for (const o of r.observations) (rows[o.student] ||= Array(times.length).fill(null))[idx[o.ts]] = o;
  const names = r.session.layout.seats.map((s) => s.name);
  const tl = $("#timeline");
  if (!times.length) {
    tl.replaceChildren(el("p", { class: "muted" }, "沒有辨識紀錄"));
  } else {
    tl.replaceChildren(
      ...names.map((n) => el("div", { class: "tl-row" },
        el("div", { class: "tl-name", title: n }, n),
        el("div", { class: "tl-cells" }, (rows[n] || []).map((o) => o
          ? el("i", { style: { "--c": statusColor(o.status) }, title: `${fmtTime(o.ts)} ${STATUS_LABEL[o.status]}：${o.reason}` })
          : el("i", { style: { "--c": "transparent" } }))))),
      el("div", { class: "tl-row" }, el("div", { class: "tl-name" }),
        el("div", { class: "tl-axis" }, `${fmtTime(times[0])} → ${fmtTime(times[times.length - 1])}`)));
  }

  const alerts = $("#alerts");
  if (!r.alerts.length) alerts.replaceChildren(el("li", { class: "muted" }, "本堂課沒有警示"));
  else alerts.replaceChildren(...r.alerts.map((a) => el("li", { class: `alert ${a.level}` },
    el("div", {}, (a.level === "danger" ? "⚠️ " : "") + a.message),
    el("div", { class: "meta" }, fmtTime(a.ts),
      a.snapshot ? el("a", { href: `/snapshots/${a.session_id}/${a.snapshot}`, target: "_blank" }, "畫面") : null))));
})();
