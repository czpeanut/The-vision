// 共用小工具
const STATUS_LABEL = Object.fromEntries(window.STATUSES.map((s) => [s.value, s.label]));
const statusColor = (s) => `var(--s-${s})`;

function $(sel) { return document.querySelector(sel); }

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style" && typeof v === "object") {
      // 自訂屬性 (--c) 必須用 setProperty 設定
      for (const [sk, sv] of Object.entries(v)) e.style.setProperty(sk, sv);
    }
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) e.append(c);
  return e;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("zh-TW", { hour12: false });
}

function renderLegend(target) {
  target.replaceChildren(...window.STATUSES.map((s) =>
    el("span", { style: { "--c": statusColor(s.value) } }, s.label)));
}
