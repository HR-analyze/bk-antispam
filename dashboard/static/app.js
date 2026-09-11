"use strict";

/* BK AntiSpam dashboard. Read-only view over public.messages. */

const CLASS_LABELS = {
  clean: "чистые",
  link: "ссылка",
  profanity: "мат",
  negative: "негатив",
  spam: "спам/реклама",
  adult: "порнография/интим",
  job_spam: "работа/подработка",
  fake_purchase: "фиктивная покупка",
  paid_task: "платная просьба",
  flood: "флуд/повтор",
  error: "ошибка классификации",
};

const state = {
  days: 30,
  classification: "",
  deleted: "",
  q: "",
  limit: 50,
  offset: 0,
  userId: null,
  openKey: null,
  dailyAsTable: false,
  showClean: false,
};

let config = { source: "", chat_username: "" };
let lastMessages = { items: [], total: null };
let lastCharts = { daily: { rows: [], days: 30 }, classes: [] };

const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("ru-RU");
const fmtInt = (n) => nf.format(Number(n || 0));

function classLabel(key) {
  return CLASS_LABELS[key] || key || "—";
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmtDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function fmtDayShort(iso) {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });
}

function authorName(row) {
  const name = [row.first_name, row.last_name].filter(Boolean).join(" ").trim();
  return name || (row.username ? "@" + row.username : (row.user_id ? "ID " + row.user_id : "—"));
}

function telegramLink(row) {
  if (!row.message_id) return null;
  if (config.chat_username) return `https://t.me/${config.chat_username}/${row.message_id}`;
  const raw = String(row.chat_id || "");
  if (raw.startsWith("-100")) return `https://t.me/c/${raw.slice(4)}/${row.message_id}`;
  return null;
}

/* ------------------------------------------------------------------ fetching */

let inFlight = 0;

function setBusy(busy) {
  inFlight += busy ? 1 : -1;
  document.body.classList.toggle("loading", inFlight > 0);
}

function showError(message) {
  const banner = $("error-banner");
  if (!message) { banner.hidden = true; return; }
  banner.hidden = false;
  banner.textContent = message;
}

async function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
  }
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) { /* keep the status line */ }
    throw new Error(detail);
  }
  return response.json();
}

function scopeParams() {
  return {
    days: state.days || "",
    classification: state.classification,
    deleted: state.deleted,
    q: state.q,
    user_id: state.userId ?? "",
  };
}

/* ------------------------------------------------------------------ svg helpers */

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

/** Bar with rounded corners only on the data end (r is clamped to the bar). */
function barPath(x, y, w, h, r, side) {
  const rad = Math.max(0, Math.min(r, w / 2, h));
  if (rad === 0) return `M${x} ${y}h${w}v${h}h${-w}z`;
  if (side === "top") {
    return `M${x} ${y + h}V${y + rad}a${rad} ${rad} 0 0 1 ${rad} ${-rad}h${w - 2 * rad}` +
           `a${rad} ${rad} 0 0 1 ${rad} ${rad}V${y + h}z`;
  }
  // side === "right"
  return `M${x} ${y}h${w - rad}a${rad} ${rad} 0 0 1 ${rad} ${rad}v${h - 2 * rad}` +
         `a${rad} ${rad} 0 0 1 ${-rad} ${rad}H${x}z`;
}

function niceTicks(maxValue, count = 4) {
  if (maxValue <= 0) return { max: 1, ticks: [0, 1] };
  const rawStep = maxValue / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep) || magnitude * 10;
  const max = Math.ceil(maxValue / step) * step;
  const ticks = [];
  for (let v = 0; v <= max + 1e-9; v += step) ticks.push(Math.round(v));
  return { max, ticks };
}

function makeTooltip(host) {
  const tip = document.createElement("div");
  tip.className = "tooltip";
  host.appendChild(tip);
  return {
    show(x, y, html) {
      tip.innerHTML = html;
      // Keep the bubble inside the card even at the first/last column.
      const half = Math.min(120, (host.clientWidth || 320) / 2);
      const clamped = Math.max(half, Math.min(x, (host.clientWidth || 320) - half));
      tip.style.left = `${clamped}px`;
      tip.style.top = `${Math.max(y, 24)}px`;
      tip.dataset.open = "1";
    },
    hide() { tip.dataset.open = "0"; },
  };
}

function tooltipRows(kept, removed) {
  return `<div class="t-row"><i class="swatch kept"></i>оставлено<b>${fmtInt(kept)}</b></div>` +
         `<div class="t-row"><i class="swatch removed"></i>удалено<b>${fmtInt(removed)}</b></div>`;
}

/* ------------------------------------------------------------------ daily chart */

function fillDayGaps(rows, days) {
  const byDate = new Map();
  for (const row of rows) {
    const key = String(row.date).slice(0, 10);
    byDate.set(key, { messages: Number(row.messages || 0), deleted: Number(row.deleted_messages || 0) });
  }
  const out = [];
  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);
  for (let i = days - 1; i >= 0; i--) {
    const day = new Date(today.getTime() - i * 86400000);
    const key = day.toISOString().slice(0, 10);
    const found = byDate.get(key) || { messages: 0, deleted: 0 };
    out.push({ date: key, messages: found.messages, deleted: found.deleted });
  }
  return out;
}

function renderDaily(rows, days) {
  lastCharts.daily = { rows, days };
  const host = $("daily-host");
  host.innerHTML = "";
  const data = fillDayGaps(rows, days);
  const totalAll = data.reduce((sum, d) => sum + d.messages, 0);

  renderDailyTable(data);
  if (state.dailyAsTable) { host.hidden = true; $("daily-table").hidden = false; return; }
  host.hidden = false;
  $("daily-table").hidden = true;

  if (!totalAll) {
    host.innerHTML = '<div class="empty">За выбранный период сообщений нет</div>';
    return;
  }

  const width = Math.max(320, host.clientWidth || 640);
  const padding = { top: 10, right: 8, bottom: 24, left: 40 };
  const plotH = 200;
  const height = plotH + padding.top + padding.bottom;
  const plotW = width - padding.left - padding.right;

  const { max, ticks } = niceTicks(Math.max(...data.map((d) => d.messages)));
  const yOf = (value) => padding.top + plotH - (value / max) * plotH;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    width, height, role: "img",
    "aria-label": `Сообщения по дням за ${days} дн.`,
  });

  for (const tick of ticks) {
    const y = yOf(tick);
    svg.appendChild(svgEl("line", {
      x1: padding.left, x2: width - padding.right, y1: y, y2: y,
      stroke: "var(--grid)", "stroke-width": 1, "shape-rendering": "crispEdges",
    }));
    const label = svgEl("text", {
      x: padding.left - 8, y: y + 4, "text-anchor": "end",
      fill: "var(--text-muted)", "font-size": 11,
      style: "font-variant-numeric: tabular-nums",
    });
    label.textContent = fmtInt(tick);
    svg.appendChild(label);
  }

  const step = plotW / data.length;
  const barW = Math.max(1.5, step - (step > 8 ? 3 : step * 0.2));
  const gap = step > 5 ? 2 : 0; // 2px surface gap between stacked segments

  const tip = makeTooltip(host);
  const hover = svgEl("rect", {
    x: 0, y: padding.top, width: 0, height: plotH,
    fill: "var(--text-primary)", opacity: 0.05, visibility: "hidden",
  });
  svg.appendChild(hover);

  data.forEach((d, i) => {
    const x = padding.left + i * step + (step - barW) / 2;
    const kept = d.messages - d.deleted;
    const removedH = (d.deleted / max) * plotH;
    const keptH = (kept / max) * plotH;
    const baseY = padding.top + plotH;

    if (kept > 0) {
      const h = Math.max(keptH, 1);
      svg.appendChild(svgEl("path", {
        d: barPath(x, baseY - h, barW, h, d.deleted > 0 ? 0 : 4, "top"),
        fill: "var(--kept)",
      }));
    }
    if (d.deleted > 0) {
      const h = Math.max(removedH, 1);
      const y = baseY - keptH - h - (kept > 0 ? gap : 0);
      svg.appendChild(svgEl("path", { d: barPath(x, y, barW, h, 4, "top"), fill: "var(--removed)" }));
    }

    // Column-wide hit target so a 2px bar is still hoverable.
    const hit = svgEl("rect", {
      x: padding.left + i * step, y: padding.top, width: step, height: plotH,
      fill: "transparent",
    });
    hit.addEventListener("mouseenter", () => {
      hover.setAttribute("x", padding.left + i * step);
      hover.setAttribute("width", step);
      hover.setAttribute("visibility", "visible");
      const cx = (padding.left + i * step + step / 2) * (host.clientWidth / width);
      tip.show(cx, yOf(d.messages) * (host.clientWidth / width),
        `<div class="t-title">${fmtDayShort(d.date)} — ${fmtInt(d.messages)}</div>${tooltipRows(kept, d.deleted)}`);
    });
    svg.appendChild(hit);
  });

  svg.addEventListener("mouseleave", () => {
    tip.hide();
    hover.setAttribute("visibility", "hidden");
  });

  svg.appendChild(svgEl("line", {
    x1: padding.left, x2: width - padding.right,
    y1: padding.top + plotH, y2: padding.top + plotH,
    stroke: "var(--axis)", "stroke-width": 1, "shape-rendering": "crispEdges",
  }));

  const labelCount = Math.min(width < 560 ? 3 : 6, data.length);
  const every = Math.max(1, Math.round(data.length / labelCount));
  data.forEach((d, i) => {
    if (i % every !== 0 && i !== data.length - 1) return;
    const label = svgEl("text", {
      x: padding.left + i * step + step / 2, y: height - 8,
      "text-anchor": i === data.length - 1 ? "end" : "middle",
      fill: "var(--text-muted)", "font-size": 11,
    });
    label.textContent = fmtDayShort(d.date);
    svg.appendChild(label);
  });

  host.appendChild(svg);
}

function renderDailyTable(data) {
  const rows = data.filter((d) => d.messages > 0).reverse();
  $("daily-table").innerHTML = `
    <table>
      <thead><tr><th>Дата</th><th class="num">Всего</th><th class="num">Оставлено</th><th class="num">Удалено</th></tr></thead>
      <tbody>${rows.map((d) => `
        <tr>
          <td class="mono">${escapeHtml(d.date)}</td>
          <td class="num">${fmtInt(d.messages)}</td>
          <td class="num">${fmtInt(d.messages - d.deleted)}</td>
          <td class="num">${fmtInt(d.deleted)}</td>
        </tr>`).join("") || '<tr><td colspan="4" class="empty">Нет данных</td></tr>'}
      </tbody>
    </table>`;
}

/* ------------------------------------------------------------------ classification chart */

function renderClassifications(rows) {
  lastCharts.classes = rows;
  const host = $("class-host");
  host.innerHTML = "";
  const all = rows
    .map((r) => ({
      key: r.classification,
      count: Number(r.count || 0),
      deleted: Number(r.deleted_count || 0),
    }))
    .filter((r) => r.count > 0)
    .sort((a, b) => b.count - a.count);

  // Shares always refer to every message, including the clean ones.
  const total = all.reduce((sum, d) => sum + d.count, 0);
  const clean = all.find((d) => d.key === "clean");
  const cleanShare = clean && total ? ((clean.count / total) * 100).toFixed(1).replace(".", ",") : null;
  $("clean-note").textContent = clean && !state.showClean
    ? `чистые скрыты: ${fmtInt(clean.count)} (${cleanShare}% всех сообщений)`
    : "";

  // "clean" outweighs every spam bucket, so by default it is excluded and the
  // remaining categories keep a readable scale.
  const data = state.showClean ? all : all.filter((d) => d.key !== "clean");

  if (!data.length) {
    host.innerHTML = '<div class="empty">За выбранный период таких сообщений нет</div>';
    return;
  }
  const width = Math.max(320, host.clientWidth || 480);
  const rowH = 30;
  const height = data.length * rowH + 6;
  const labelW = 164;
  const valueW = 58;
  const barMax = Math.max(60, width - labelW - valueW - 8);
  const maxCount = Math.max(...data.map((d) => d.count));

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`, width, height, role: "img",
    "aria-label": "Распределение сообщений по классификации",
  });
  const tip = makeTooltip(host);

  data.forEach((d, i) => {
    const y = i * rowH + 3;
    const barH = 14;
    const barY = y + (rowH - 6 - barH) / 2;
    const kept = d.count - d.deleted;
    const fullW = (d.count / maxCount) * barMax;
    const keptW = (kept / d.count) * fullW;
    const removedW = (d.deleted / d.count) * fullW;
    const gap = kept > 0 && d.deleted > 0 ? 2 : 0;

    const label = svgEl("text", {
      x: 0, y: barY + barH - 2, fill: "var(--text-secondary)", "font-size": 12.5,
    });
    label.textContent = classLabel(d.key);
    svg.appendChild(label);

    if (kept > 0) {
      svg.appendChild(svgEl("path", {
        d: barPath(labelW, barY, Math.max(keptW - gap, 1), barH, d.deleted > 0 ? 0 : 4, "right"),
        fill: "var(--kept)",
      }));
    }
    if (d.deleted > 0) {
      svg.appendChild(svgEl("path", {
        d: barPath(labelW + keptW, barY, Math.max(removedW, 1.5), barH, 4, "right"),
        fill: "var(--removed)",
      }));
    }

    // Direct label: every category value stays readable without the tooltip.
    const value = svgEl("text", {
      x: labelW + Math.max(fullW, 2) + 8, y: barY + barH - 2,
      fill: "var(--text-primary)", "font-size": 12.5,
      style: "font-variant-numeric: tabular-nums",
    });
    value.textContent = fmtInt(d.count);
    svg.appendChild(value);

    const hit = svgEl("rect", { x: 0, y, width, height: rowH - 4, fill: "transparent" });
    const share = total ? ((d.count / total) * 100).toFixed(1).replace(".", ",") : "0";
    hit.addEventListener("mouseenter", () => {
      const scale = host.clientWidth / width;
      tip.show((labelW + fullW / 2) * scale, (barY) * scale,
        `<div class="t-title">${escapeHtml(classLabel(d.key))} — ${fmtInt(d.count)} (${share}%)</div>` +
        tooltipRows(kept, d.deleted));
    });
    svg.appendChild(hit);
  });

  svg.addEventListener("mouseleave", () => tip.hide());
  host.appendChild(svg);
}

/* ------------------------------------------------------------------ tiles */

function renderTiles(stats) {
  const total = Number(stats.total_messages || 0);
  const deleted = Number(stats.deleted_messages || 0);
  const share = total ? ((deleted / total) * 100).toFixed(1).replace(".", ",") : "0";
  const tiles = [
    { label: "Сообщений", value: fmtInt(total), note: state.days ? `за ${state.days} дн.` : "за всё время" },
    { label: "Удалено", value: fmtInt(deleted), note: `${share}% от всех` },
    { label: "Пропущено с меткой", value: fmtInt(stats.flagged_kept), note: "классифицировано, но осталось" },
    { label: "Авторов", value: fmtInt(stats.unique_users), note: "уникальных" },
    { label: "За 24 часа", value: fmtInt(stats.messages_24h), note: `удалено ${fmtInt(stats.deleted_24h)}` },
  ];
  $("tiles").innerHTML = tiles.map((t) => `
    <div class="tile">
      <div class="label">${escapeHtml(t.label)}</div>
      <div class="value">${t.value}</div>
      <div class="note">${escapeHtml(t.note)}</div>
    </div>`).join("");

  $("sub").textContent = stats.last_message_at
    ? `последнее сообщение: ${fmtDateTime(stats.last_message_at)}`
    : "модерация комментариев";
}

/* ------------------------------------------------------------------ top users */

function renderTopUsers(rows) {
  if (!rows.length) {
    $("top-users").innerHTML = '<div class="empty">Нет данных</div>';
    return;
  }
  $("top-users").innerHTML = `
    <table>
      <thead><tr><th>Автор</th><th class="num">Всего</th><th class="num">Удалено</th><th></th></tr></thead>
      <tbody>${rows.map((row) => `
        <tr>
          <td>
            <div class="author">
              <span class="name">${escapeHtml(authorName(row))}</span>
              <span class="handle">${row.username ? "@" + escapeHtml(row.username) : "ID " + escapeHtml(row.user_id)}</span>
            </div>
          </td>
          <td class="num">${fmtInt(row.messages)}</td>
          <td class="num">${fmtInt(row.deleted_messages)}</td>
          <td class="num"><button class="btn ghost" type="button" data-user="${escapeHtml(row.user_id)}">фильтр</button></td>
        </tr>`).join("")}
      </tbody>
    </table>`;
  $("top-users").querySelectorAll("button[data-user]").forEach((button) => {
    button.addEventListener("click", () => filterByUser(Number(button.dataset.user)));
  });
}

/* ------------------------------------------------------------------ messages */

function rowKey(row) {
  return `${row.chat_id}:${row.message_id}`;
}

function renderMessages(payload) {
  lastMessages = payload;
  const body = $("messages-body");
  const items = payload.items || [];
  body.innerHTML = "";

  if (!items.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">Ничего не найдено</td></tr>';
  }

  for (const row of items) {
    const key = rowKey(row);
    const tr = document.createElement("tr");
    tr.className = "msg-row" + (state.openKey === key ? " open" : "");
    tr.tabIndex = 0;
    tr.setAttribute("role", "button");
    tr.setAttribute("aria-expanded", state.openKey === key ? "true" : "false");
    tr.innerHTML = `
      <td class="cell-time"><span class="caret">▶</span> ${escapeHtml(fmtDateTime(row.message_date || row.created_at))}</td>
      <td>
        <div class="author">
          <span class="name">${escapeHtml(authorName(row))}</span>
          <span class="handle">${row.username ? "@" + escapeHtml(row.username) : (row.user_id ? "ID " + escapeHtml(row.user_id) : "—")}</span>
        </div>
      </td>
      <td class="cell-text"><div class="clamp">${escapeHtml(row.text) || '<span style="color:var(--text-muted)">(без текста)</span>'}</div></td>
      <td><span class="chip">${escapeHtml(classLabel(row.classification || "clean"))}</span></td>
      <td>${row.deleted
        ? '<span class="status removed"><i class="dot"></i>удалено</span>'
        : '<span class="status kept"><i class="dot"></i>оставлено</span>'}</td>`;

    const toggle = () => toggleDetail(row, tr);
    tr.addEventListener("click", (event) => {
      if (event.target.closest("a, button")) return;
      toggle();
    });
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(); }
    });
    body.appendChild(tr);

    if (state.openKey === key) body.appendChild(buildDetailRow(row));
  }

  const total = payload.total;
  $("messages-count").textContent = total === null || total === undefined
    ? `${items.length} на странице`
    : `${fmtInt(total)} сообщений по фильтру`;

  const from = payload.offset + (items.length ? 1 : 0);
  const to = payload.offset + items.length;
  $("pager-info").textContent = items.length
    ? `${fmtInt(from)}–${fmtInt(to)}${total != null ? " из " + fmtInt(total) : ""}`
    : "";
  $("prev-btn").disabled = payload.offset <= 0;
  $("next-btn").disabled = total != null
    ? to >= total
    : items.length < payload.limit;
}

function buildDetailRow(row) {
  const tr = document.createElement("tr");
  tr.className = "detail";
  const td = document.createElement("td");
  td.colSpan = 5;

  const link = telegramLink(row);
  const fields = [
    ["Классификация", classLabel(row.classification || "clean")],
    ["Причина", row.delete_reason || "—"],
    ["Статус", row.deleted ? "удалено ботом" : "оставлено"],
    ["Время сообщения", fmtDateTime(row.message_date)],
    ["Записано в БД", fmtDateTime(row.created_at)],
    ["message_id", row.message_id],
    ["chat_id", row.chat_id],
    ["user_id", row.user_id ?? "—"],
    ["username", row.username ? "@" + row.username : "—"],
    ["Ответ на", row.reply_to_message_id || "—"],
    ["ID записи", row.id],
  ];

  td.innerHTML = `
    <div class="detail-inner">
      <div class="detail-text">${escapeHtml(row.text) || "(без текста)"}</div>
      <dl class="kv">
        ${fields.map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join("")}
        <div><dt>Автор в чате</dt><dd id="user-summary">загрузка…</dd></div>
      </dl>
      <div class="detail-actions">
        ${link ? `<a class="btn" href="${escapeHtml(link)}" target="_blank" rel="noopener">открыть в Telegram ↗</a>` : ""}
        ${row.user_id ? `<button class="btn" type="button" data-act="user">все сообщения автора</button>` : ""}
        <button class="btn" type="button" data-act="copy">копировать JSON</button>
      </div>
    </div>`;

  const userButton = td.querySelector('[data-act="user"]');
  if (userButton) userButton.addEventListener("click", () => filterByUser(row.user_id));

  const copyButton = td.querySelector('[data-act="copy"]');
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(row, null, 2));
      copyButton.textContent = "скопировано ✓";
      setTimeout(() => { copyButton.textContent = "копировать JSON"; }, 1500);
    } catch (_) {
      copyButton.textContent = "не удалось";
    }
  });

  tr.appendChild(td);

  if (row.user_id) {
    api("/api/user-summary", { user_id: row.user_id })
      .then((summary) => {
        const node = td.querySelector("#user-summary");
        if (!node) return;
        const first = fmtDateTime(summary.first_seen);
        node.textContent = `${fmtInt(summary.messages)} сообщ., удалено ${fmtInt(summary.deleted_messages)} · с ${first}`;
      })
      .catch(() => {
        const node = td.querySelector("#user-summary");
        if (node) node.textContent = "—";
      });
  } else {
    const node = td.querySelector("#user-summary");
    if (node) node.textContent = "—";
  }

  return tr;
}

function toggleDetail(row, tr) {
  const key = rowKey(row);
  const body = $("messages-body");
  const existing = tr.nextElementSibling;

  if (state.openKey === key) {
    state.openKey = null;
    tr.classList.remove("open");
    tr.setAttribute("aria-expanded", "false");
    if (existing && existing.classList.contains("detail")) existing.remove();
    return;
  }

  const previous = body.querySelector("tr.detail");
  if (previous) previous.remove();
  body.querySelectorAll("tr.msg-row.open").forEach((node) => {
    node.classList.remove("open");
    node.setAttribute("aria-expanded", "false");
  });

  state.openKey = key;
  tr.classList.add("open");
  tr.setAttribute("aria-expanded", "true");
  tr.after(buildDetailRow(row));
}

/* ------------------------------------------------------------------ filters */

function renderUserChip() {
  const slot = $("user-chip-slot");
  if (!state.userId) { slot.innerHTML = ""; return; }
  slot.innerHTML = `<span class="userchip">автор ID ${escapeHtml(state.userId)}<button type="button" title="убрать фильтр">×</button></span>`;
  slot.querySelector("button").addEventListener("click", () => {
    state.userId = null;
    state.offset = 0;
    renderUserChip();
    reload();
  });
}

function filterByUser(userId) {
  state.userId = userId;
  state.offset = 0;
  state.openKey = null;
  renderUserChip();
  reload();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function fillClassificationOptions() {
  try {
    const rows = await api("/api/classifications", {});
    const select = $("f-class");
    const current = select.value;
    const keys = rows.map((r) => r.classification).filter(Boolean);
    for (const key of Object.keys(CLASS_LABELS)) if (!keys.includes(key)) keys.push(key);
    select.innerHTML = '<option value="">Все</option>' +
      [...new Set(keys)].map((key) =>
        `<option value="${escapeHtml(key)}">${escapeHtml(classLabel(key))}</option>`).join("");
    select.value = current;
  } catch (_) { /* the filter simply stays at "Все" */ }
}

/* ------------------------------------------------------------------ loading */

// Filter changes can overlap; only the newest run is allowed to render.
let reloadToken = 0;

async function reload() {
  const token = ++reloadToken;
  setBusy(true);
  showError("");
  const scope = scopeParams();
  const dailyDays = state.days || 365;
  try {
    const [stats, classes, daily, topUsers, messages] = await Promise.all([
      api("/api/stats", { days: scope.days }),
      api("/api/classifications", { days: scope.days }),
      api("/api/daily", { days: dailyDays }),
      api("/api/top-users", { limit: 10, days: scope.days }),
      api("/api/messages", {
        limit: state.limit, offset: state.offset,
        classification: scope.classification, deleted: scope.deleted,
        q: scope.q, user_id: scope.user_id, days: scope.days,
      }),
    ]);
    if (token !== reloadToken) return;
    renderTiles(stats || {});
    renderClassifications(classes || []);
    renderDaily(daily || [], dailyDays);
    renderTopUsers(topUsers || []);
    renderMessages(messages || { items: [], total: 0, limit: state.limit, offset: state.offset });
  } catch (error) {
    if (token === reloadToken) showError("Ошибка загрузки: " + error.message);
  } finally {
    setBusy(false);
  }
}

/** Charts are re-drawn from cached data on resize and theme change. */
function redrawCharts() {
  renderDaily(lastCharts.daily.rows, lastCharts.daily.days);
  renderClassifications(lastCharts.classes);
}

/* ------------------------------------------------------------------ wiring */

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function initTheme() {
  const stored = localStorage.getItem("bk-theme");
  if (stored) document.documentElement.dataset.theme = stored;
  $("theme-btn").addEventListener("click", () => {
    const isDark = document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = isDark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("bk-theme", next);
    redrawCharts();
  });
}

function init() {
  initTheme();

  $("f-period").addEventListener("change", (e) => {
    state.days = e.target.value ? Number(e.target.value) : null;
    state.offset = 0; state.openKey = null; reload();
  });
  $("f-class").addEventListener("change", (e) => {
    state.classification = e.target.value; state.offset = 0; state.openKey = null; reload();
  });
  $("f-status").addEventListener("change", (e) => {
    state.deleted = e.target.value; state.offset = 0; state.openKey = null; reload();
  });
  $("f-limit").addEventListener("change", (e) => {
    state.limit = Number(e.target.value); state.offset = 0; state.openKey = null; reload();
  });
  $("f-q").addEventListener("input", debounce((e) => {
    state.q = e.target.value.trim(); state.offset = 0; state.openKey = null; reload();
  }, 350));
  $("filters").addEventListener("submit", (e) => e.preventDefault());

  $("reset-btn").addEventListener("click", () => {
    state.days = 30; state.classification = ""; state.deleted = ""; state.q = "";
    state.limit = 50; state.offset = 0; state.userId = null; state.openKey = null;
    $("f-period").value = "30"; $("f-class").value = ""; $("f-status").value = "";
    $("f-q").value = ""; $("f-limit").value = "50";
    renderUserChip();
    reload();
  });

  $("refresh-btn").addEventListener("click", reload);
  $("prev-btn").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    state.openKey = null; reload();
  });
  $("next-btn").addEventListener("click", () => {
    state.offset += state.limit;
    state.openKey = null; reload();
  });

  $("clean-btn").addEventListener("click", () => {
    state.showClean = !state.showClean;
    $("clean-btn").textContent = state.showClean ? "скрыть чистые" : "показать чистые";
    $("clean-btn").setAttribute("aria-pressed", String(state.showClean));
    renderClassifications(lastCharts.classes);
  });

  $("daily-view-btn").addEventListener("click", () => {
    state.dailyAsTable = !state.dailyAsTable;
    $("daily-view-btn").textContent = state.dailyAsTable ? "график" : "таблица";
    $("daily-view-btn").setAttribute("aria-pressed", String(state.dailyAsTable));
    renderDaily(lastCharts.daily.rows, lastCharts.daily.days);
  });

  window.addEventListener("resize", debounce(redrawCharts, 200));

  api("/api/config").then((cfg) => { config = cfg || config; }).catch(() => {});
  fillClassificationOptions();
  reload();
}

document.addEventListener("DOMContentLoaded", init);
