// 框選座位：座標一律存成原始影像像素，畫面縮放時再換算。
const img = $("#frame");
const canvas = $("#canvas");
const ctx = canvas.getContext("2d");
const msg = $("#save-msg");

let seats = [];        // {name, bbox:[x1,y1,x2,y2]}
let ignores = [];      // [x1,y1,x2,y2]
let mode = "seat";
let drag = null;       // {x, y, x2, y2} 拖曳中的框 (影像座標)
let selected = null;   // {kind:"seat"|"ignore", i}
let focusAfterRender = null;

function scale() { return img.naturalWidth ? canvas.width / img.naturalWidth : 1; }

function toImage(ev) {
  const r = canvas.getBoundingClientRect();
  const s = img.naturalWidth / r.width;
  return [(ev.clientX - r.left) * s, (ev.clientY - r.top) * s];
}

function norm(b) {
  return [Math.min(b[0], b[2]), Math.min(b[1], b[3]), Math.max(b[0], b[2]), Math.max(b[1], b[3])].map(Math.round);
}

function draw() {
  const r = canvas.getBoundingClientRect();
  canvas.width = r.width * devicePixelRatio;
  canvas.height = r.height * devicePixelRatio;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const s = scale();
  const fs = Math.max(12, 14 * devicePixelRatio);
  ctx.font = `600 ${fs}px system-ui, "Noto Sans TC", sans-serif`;
  ctx.lineWidth = 2 * devicePixelRatio;

  ignores.forEach((b, i) => {
    const sel = selected && selected.kind === "ignore" && selected.i === i;
    ctx.fillStyle = "rgba(120,120,120,.35)";
    ctx.fillRect(b[0] * s, b[1] * s, (b[2] - b[0]) * s, (b[3] - b[1]) * s);
    ctx.strokeStyle = sel ? "#fff" : "#aaa";
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(b[0] * s, b[1] * s, (b[2] - b[0]) * s, (b[3] - b[1]) * s);
    ctx.setLineDash([]);
    ctx.fillStyle = "#fff";
    ctx.fillText("忽略區", b[0] * s + 4, b[1] * s + fs + 2);
  });

  seats.forEach((seat, i) => {
    const b = seat.bbox;
    const sel = selected && selected.kind === "seat" && selected.i === i;
    ctx.strokeStyle = sel ? "#ffeb3b" : "#22d3ee";
    ctx.fillStyle = sel ? "rgba(255,235,59,.15)" : "rgba(34,211,238,.10)";
    ctx.fillRect(b[0] * s, b[1] * s, (b[2] - b[0]) * s, (b[3] - b[1]) * s);
    ctx.strokeRect(b[0] * s, b[1] * s, (b[2] - b[0]) * s, (b[3] - b[1]) * s);
    const label = `${i + 1}. ${seat.name || "(未命名)"}`;
    const w = ctx.measureText(label).width + 8;
    ctx.fillStyle = sel ? "#ffeb3b" : "#22d3ee";
    ctx.fillRect(b[0] * s, b[1] * s - fs - 6, w, fs + 6);
    ctx.fillStyle = "#000";
    ctx.fillText(label, b[0] * s + 4, b[1] * s - 5);
  });

  if (drag) {
    const b = norm([drag.x, drag.y, drag.x2, drag.y2]);
    ctx.strokeStyle = mode === "seat" ? "#22d3ee" : "#ccc";
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(b[0] * s, b[1] * s, (b[2] - b[0]) * s, (b[3] - b[1]) * s);
    ctx.setLineDash([]);
  }
}

function renderLists() {
  $("#seat-count").textContent = seats.length;
  $("#ignore-count").textContent = ignores.length;
  let toFocus = null;
  $("#seat-list").replaceChildren(...seats.map((seat, i) => {
    const input = el("input", {
      value: seat.name, placeholder: "學生姓名",
      oninput: (e) => { seat.name = e.target.value; draw(); },
      onfocus: () => { selected = { kind: "seat", i }; draw(); markSelected(); },
      onkeydown: (e) => { if (e.key === "Enter") e.target.blur(); },
    });
    if (focusAfterRender === i) toFocus = input;
    return el("li", { "data-i": i },
      el("span", { class: "idx" }, `${i + 1}`), input,
      el("button", { title: "刪除", onclick: () => removeAt("seat", i) }, "✕"));
  }));
  $("#ignore-list").replaceChildren(...ignores.map((_, i) =>
    el("li", {}, el("span", { class: "idx" }, `${i + 1}`), el("span", { class: "grow" }, "忽略區"),
      el("button", { title: "刪除", onclick: () => removeAt("ignore", i) }, "✕"))));
  focusAfterRender = null;
  if (toFocus) toFocus.focus();
  markSelected();
}

function markSelected() {
  document.querySelectorAll("#seat-list li").forEach((li) =>
    li.classList.toggle("sel", !!selected && selected.kind === "seat" && +li.dataset.i === selected.i));
}

function removeAt(kind, i) {
  if (kind === "seat") seats.splice(i, 1); else ignores.splice(i, 1);
  selected = null;
  renderLists();
  draw();
}

function hit(x, y) {
  for (let i = seats.length - 1; i >= 0; i--) {
    const b = seats[i].bbox;
    if (x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3]) return { kind: "seat", i };
  }
  for (let i = ignores.length - 1; i >= 0; i--) {
    const b = ignores[i];
    if (x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3]) return { kind: "ignore", i };
  }
  return null;
}

canvas.addEventListener("pointerdown", (ev) => {
  if (!img.naturalWidth) return;
  const [x, y] = toImage(ev);
  drag = { x, y, x2: x, y2: y };
  canvas.setPointerCapture(ev.pointerId);
});
canvas.addEventListener("pointermove", (ev) => {
  if (!drag) return;
  [drag.x2, drag.y2] = toImage(ev);
  draw();
});
canvas.addEventListener("pointerup", () => {
  if (!drag) return;
  const b = norm([drag.x, drag.y, drag.x2, drag.y2]);
  const tiny = b[2] - b[0] < 12 || b[3] - b[1] < 12;
  if (tiny) {
    // 視為點擊：選取既有的框
    selected = hit(drag.x, drag.y);
    if (selected && selected.kind === "seat") focusAfterRender = selected.i;
  } else if (mode === "seat") {
    seats.push({ name: "", bbox: b });
    selected = { kind: "seat", i: seats.length - 1 };
    focusAfterRender = selected.i;
  } else {
    ignores.push(b);
    selected = { kind: "ignore", i: ignores.length - 1 };
  }
  drag = null;
  renderLists();
  draw();
});

document.addEventListener("keydown", (ev) => {
  if ((ev.key === "Delete" || ev.key === "Backspace") && selected && document.activeElement.tagName !== "INPUT") {
    removeAt(selected.kind, selected.i);
  }
});

document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  mode = b.dataset.mode;
  document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
}));

function loadFrame() {
  $("#stage-msg").hidden = false;
  $("#stage-msg").textContent = "載入畫面中…";
  img.src = `/api/frame.jpg?t=${Date.now()}`;
}
img.addEventListener("load", () => { $("#stage-msg").hidden = true; draw(); });
img.addEventListener("error", () => { $("#stage-msg").textContent = "無法取得監視器畫面，請確認 config.yaml 中的 camera.source"; });
$("#reload").addEventListener("click", loadFrame);
window.addEventListener("resize", draw);

$("#clear").addEventListener("click", () => {
  if (!confirm("確定清除所有座位與忽略區？")) return;
  seats = []; ignores = []; selected = null;
  renderLists(); draw();
});

$("#save").addEventListener("click", async () => {
  msg.className = "msg";
  try {
    const r = await api("/api/layout", {
      method: "POST",
      body: {
        seats: seats.map((s) => ({ name: s.name.trim(), bbox: s.bbox })),
        ignore_zones: ignores,
        frame_size: img.naturalWidth ? [img.naturalWidth, img.naturalHeight] : null,
      },
    });
    msg.className = "msg ok";
    msg.textContent = `已儲存 ${r.seats} 個座位，可以到「即時看板」開始監看。`;
  } catch (e) {
    msg.className = "msg err";
    msg.textContent = e.message;
  }
});

(async () => {
  const layout = await api("/api/layout");
  seats = layout.seats.map((s) => ({ name: s.name, bbox: s.bbox.map(Math.round) }));
  ignores = layout.ignore_zones;
  renderLists();
  loadFrame();
})();
