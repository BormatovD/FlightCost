"use strict";

const telegram = window.Telegram?.WebApp;
const initData = telegram?.initData;
const ui = {
  dashboard: document.getElementById("dashboard"),
  refresh: document.getElementById("refresh"),
  load: document.getElementById("load-state"),
  action: document.getElementById("action-state"),
  ticketAction: document.getElementById("ticket-action-state"),
  form: document.getElementById("airport-form"),
  controls: document.getElementById("airport-controls"),
  run: document.getElementById("run"),
  asOf: document.getElementById("as-of"),
  journalist: document.getElementById("journalist-toggle"),
};

const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const dateFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const shortDateFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
});
const number = value => Number.isFinite(value) ? numberFormat.format(value) : "—";
const list = value => Array.isArray(value) ? value : [];
let busy = false;
let agentActive = false;
let accessExpired = false;
let statusSnapshot;
let airportEdit;
let ticketEdit;
let airportPreview;
let ticketPreview;

function date(value, format = dateFormat) {
  if (typeof value !== "string" || !value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : format.format(parsed);
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = text;
  return element;
}

function showNotice(element, text, error = false) {
  element.textContent = text;
  element.classList.toggle("is-error", error);
  element.hidden = !text;
}

function renderMetrics(id, items, groupClass = "stat") {
  const metrics = document.getElementById(id);
  const groups = items.map(([label, value, className]) => {
    const group = node("div", null, groupClass);
    group.append(node("dt", label), node("dd", value, className));
    return group;
  });
  metrics.replaceChildren(...groups);
}

function renderRows(id, entries, rowValues, empty) {
  const rows = document.getElementById(id);
  const children = entries.map(entry => {
    const [title, metadata, detail, actions] = rowValues(entry);
    const row = node("li", null, "row");
    const content = node("div");
    content.append(node("div", title, "row-main"));
    if (metadata) content.append(node("div", metadata, "row-meta"));
    if (detail) content.append(node("p", detail, "row-detail"));
    row.append(content);
    if (actions?.length) {
      const controls = node("div", null, "actions");
      controls.append(...actions);
      row.classList.add("queue-entry");
      row.append(controls);
    }
    return row;
  });
  if (!children.length) children.push(node("li", empty, "row dim"));
  rows.replaceChildren(...children);
}

function displaySummary(id, label, count) {
  document.getElementById(id).textContent =
    Number.isFinite(count) ? label + " · " + number(count) : label;
}

function renderCharges(updates) {
  const recent = list(updates.recent);
  const airport = updates.airport_recent ?? recent.filter(row => row.kind === "airport");
  const navigation = updates.enroute_recent ?? recent.filter(row => row.kind === "enroute");
  const legacyTerminal = row => row.label?.endsWith(" · терминальные");
  const enroute = list(navigation).filter(row => !legacyTerminal(row));
  const terminal = updates.terminal_recent ?? [
    ...recent.filter(row => row.kind === "terminal"), ...list(navigation).filter(legacyTerminal),
  ];
  const common = recent.filter(row => !["airport", "enroute", "terminal"].includes(row.kind));
  const rowValues = row => [
    row.label || "Обновление",
    date(row.at),
    Array.isArray(row.details) ? row.details.join("\n") : row.details,
  ];
  renderMetrics("airport-metric", [["Правила аэропортовых сборов за 30 дней", number(updates.airport_rules)]]);
  renderMetrics("enroute-metric", [["Маршрутные ставки за 30 дней", number(updates.enroute_rates)]]);
  renderMetrics("terminal-metric", [["Терминальные ставки за 30 дней", number(updates.terminal_rates)]]);
  renderRows("airport-updates", list(airport), rowValues, "Свежих изменений в списке нет.");
  renderRows("enroute-updates", enroute, rowValues, "Свежих изменений в списке нет.");
  renderRows("terminal-updates", list(terminal), rowValues, "Свежих изменений в списке нет.");
  document.getElementById("common-updates").hidden = !common.length;
  renderRows("recent-updates", common, rowValues, "");
}

function renderAirports(agent, airports, budget) {
  agentActive = agent.active === true;
  const agentFacts = [
    ["Статус", agentActive ? "Работает" : agent.active === false ? "Ожидает запуска" : "—",
      agentActive ? "is-active" : undefined],
  ];
  if (agent.model) agentFacts.push(["Модель", agent.model]);
  if (date(agent.last_finished)) agentFacts.push(["Последнее завершение", date(agent.last_finished)]);
  if (date(agent.next)) agentFacts.push(["Следующий запуск", date(agent.next)]);
  if (Number.isFinite(budget.spent) && Number.isFinite(budget.limit)) {
    agentFacts.push(["Бюджет", number(budget.spent) + " / " + number(budget.limit)]);
  }
  renderMetrics("agent", agentFacts, "fact");

  const queue = list(airports.queued);
  const drafts = list(airports.drafts);
  displaySummary("queue-heading", "Очередь аэропортов", airports.total_queued ?? queue.length);
  displaySummary("drafts-heading", "Черновики на проверку", airports.waiting_review ?? drafts.length);
  const deferred = list(airports.deferred).map(row => typeof row === "string" ? { icao: row } : row);
  document.getElementById("deferred-section").hidden = !deferred.length;
  displaySummary("deferred-heading", "Исключённые аэропорты", airports.total_deferred ?? deferred.length);
  const queueCodes = new Set(queue.map(row => row.icao));
  const extra = list(airports.manual).filter(row => !queueCodes.has(row.icao));
  document.getElementById("extra-airport-priority").hidden = !extra.length;
  displaySummary("extra-airport-priority-heading", "Другие ручные приоритеты", extra.length);
  const queueRow = row => [
    [row.icao, row.city].filter(Boolean).join(" · "),
    [row.region, row.origin === "manual" ? "Ручной приоритет" : ""].filter(Boolean).join(" · "),
    null,
    row.origin === "manual"
      ? [queueButton("airports", row.icao, "prioritize"), queueButton("airports", row.icao, "remove")]
      : [queueButton("airports", row.icao, "prioritize"), queueButton("airports", row.icao, "defer")],
  ];
  renderRows("airport-queue", queue, queueRow, "Очередь пуста.");
  renderRows("extra-priority-airports", extra, queueRow, "");
  renderRows("airport-deferred", deferred, row => [
    [row.icao, row.city].filter(Boolean).join(" · "),
    row.region,
    null,
    [queueButton("airports", row.icao, "restore")],
  ], "Исключённых аэропортов нет.");
  renderRows("airport-drafts", drafts, row => [
    row.icao,
    [date(row.updated_at), Number.isFinite(row.rules) ? "Правил: " + number(row.rules) : ""]
      .filter(Boolean).join(" · "),
  ], "Черновиков в списке нет.");
}

function renderTickets(tickets) {
  const metrics = [
    ["В плане", tickets.total],
    ["Проверено", tickets.checked],
    ["С ценами", tickets.with_prices],
    ["Наблюдений", tickets.observations],
    ["Без покрытия", tickets.unsupported],
  ];
  renderMetrics("ticket-metrics", metrics.map(([label, value]) => [label, number(value)]));
  renderRows("recent-routes", list(tickets.recent), row => [
    row.route,
    [date(row.at), Number.isFinite(row.observations) ? "Наблюдений: " + number(row.observations) : ""]
      .filter(Boolean).join(" · "),
  ], "Свежих проверок в списке нет.");
  const prioritized = new Set(list(tickets.prioritized));
  const deferred = list(tickets.deferred);
  const editable = Array.isArray(tickets.deferred) && Array.isArray(tickets.prioritized);
  document.getElementById("deferred-tickets-section").hidden = !deferred.length;
  displaySummary("deferred-tickets-heading", "Отложенные маршруты", deferred.length);
  const planned = list(tickets.planned);
  const plannedCodes = new Set(planned.map(row => row.route));
  const extra = [...prioritized].filter(route => !plannedCodes.has(route));
  document.getElementById("extra-ticket-priority").hidden = !extra.length;
  displaySummary("extra-ticket-priority-heading", "Другие приоритетные маршруты", extra.length);
  renderRows("extra-priority-routes", extra, route => [
    route, null, null, [queueButton("tickets", route, "normal")],
  ], "");
  renderRows("planned-routes", planned, row => {
    const priority = row.priority === true || prioritized.has(row.route);
    const controls = editable ? [
      queueButton("tickets", row.route, priority ? "normal" : "prioritize"),
      queueButton("tickets", row.route, "defer"),
    ] : [];
    const metadata = [row.region, priority ? "Приоритетный" : "", row.ready === false ? "Ждёт повторной проверки" : ""];
    return [row.route, metadata.filter(Boolean).join(" · "), null, controls];
  }, "Запланированных маршрутов в списке нет.");
  renderRows("deferred-routes", deferred, route => [
    route, null, null, [queueButton("tickets", route, "restore")],
  ], "Отложенных маршрутов нет.");
}

const overviewRows = [...document.querySelectorAll(".overview-row")];
const overviewUnits = { airports: "правил", enroute: "ставок", terminal: "ставок", tickets: "наблюдений" };

function overviewCell(row, field, primary, secondary) {
  const cell = row.querySelector('[data-field="' + field + '"]');
  cell.replaceChildren(node("div", primary || "—", "overview-primary overview-" + field));
  if (secondary) cell.append(node("div", secondary, "overview-secondary"));
}

function renderOverview(status) {
  for (const row of overviewRows) {
    const key = row.dataset.work;
    const work = status.work?.[key];
    const total = work?.total ?? (key === "tickets" ? status.tickets?.observations : null);
    overviewCell(row, "total", number(total), Number.isFinite(total) ? overviewUnits[key] : "");
    const last = work?.last;
    const lastAt = date(last?.at, shortDateFormat);
    const lastLabel = [
      last?.kind === "collection" ? "Собрано" : "",
      last?.label,
      Number.isFinite(last?.count) ? number(last.count) : "",
    ].filter(Boolean).join(" · ");
    overviewCell(row, "last", lastAt, lastLabel);

    const airport = list(status.airports?.queued)[0];
    const route = list(status.tickets?.planned)[0];
    const next = key === "airports" ? airport?.icao : key === "tickets" ? route?.route : null;
    const when = key === "tickets" && route?.due_at && route.due_at > (work?.next_at || "")
      ? route.due_at : work?.next_at;
    const nextAt = date(when, shortDateFormat);
    overviewCell(row, "next", next || nextAt, next ? nextAt : "");
    if (key === "enroute" || key === "terminal") {
      const schedule = date(work?.next_at);
      document.getElementById(key + "-schedule").textContent = schedule
        ? "Следующая проверка источников · " + schedule
        : "Время следующей проверки источников неизвестно.";
    }
  }
}

for (const row of overviewRows) {
  const button = row.querySelector(".overview-toggle");
  const detail = document.getElementById(button.getAttribute("aria-controls"));
  row.addEventListener("click", event => {
    if (!button.contains(event.target)) button.focus();
    detail.hidden = !detail.hidden;
    button.setAttribute("aria-expanded", String(!detail.hidden));
  });
}

function renderJournalist(state) {
  const available = typeof state?.paused === "boolean";
  document.getElementById("journalist-panel").hidden = !available;
  if (!available) return;
  ui.journalist.textContent = state.paused ? "Возобновить подготовку" : "Приостановить подготовку";
  document.getElementById("journalist-status").textContent = state.paused
    ? "Подготовка на паузе. Присланные статьи можно согласовывать."
    : "Подготовка включена. Бюджет журналиста — до 30 USD в месяц.";
}

function renderStatus(status) {
  const sameSnapshot = statusSnapshot && status.as_of === statusSnapshot.as_of;
  statusSnapshot = status;
  if (!sameSnapshot) {
    airportPreview = list(status.airports?.queued);
    ticketPreview = list(status.tickets?.planned);
    airportEdit = undefined;
    ticketEdit = undefined;
  }
  if (airportEdit) updateAirportQueue(airportEdit);
  if (ticketEdit) updateTicketQueue(ticketEdit);
  renderOverview(status);
  renderCharges(status.updates || {});
  renderAirports(status.agent || {}, status.airports || {}, status.budget || {});
  renderTickets(status.tickets || {});
  renderJournalist(status.journalist);
  const asOf = date(status.as_of);
  ui.asOf.textContent = asOf ? "Данные на " + asOf : "";
  ui.asOf.hidden = !asOf;
  ui.dashboard.hidden = false;
}

const actionsByQueue = {
  airports: {
    prioritize: ["В начало", "в начале очереди"],
    remove: ["Снять приоритет", "без ручного приоритета"],
    defer: ["Исключить", "исключён из автоматической очереди"],
    restore: ["Вернуть в очередь", "возвращён в автоматическую очередь"],
  },
  tickets: {
    prioritize: ["Сделать приоритетным", "получил приоритет"],
    normal: ["Снять приоритет", "без ручного приоритета"],
    defer: ["Отложить", "отложен"],
    restore: ["Вернуть в очередь", "возвращён в очередь"],
  },
};

function queueButton(queue, code, action) {
  const [label, success] = actionsByQueue[queue][action];
  const button = node("button", label);
  button.type = "button";
  button.disabled = busy || accessExpired;
  button.dataset.queueAction = action;
  button.dataset.queueCode = code;
  button.setAttribute("aria-label", label + " · " + code);
  button.addEventListener("click", async () => {
    const section = button.closest(".detail-row");
    const airport = queue === "airports";
    const body = airport ? { icao: code, action } : { route: code, action };
    await runAction(queue + "/edit", body, "Обновляем очередь…",
      result => result.changed === false ? code + " · очередь уже обновлена." : code + " · " + success + ".",
      airport ? applyAirportEdit : applyTicketEdit, airport ? ui.action : ui.ticketAction);
    if (accessExpired || document.activeElement !== document.body) return;
    const replacement = [...section.querySelectorAll("[data-queue-code]")]
      .find(element => element.dataset.queueCode === code && element.offsetWidth);
    (replacement || section.previousElementSibling.querySelector("button")).focus();
  });
  return button;
}

function updateAirportQueue(result) {
  const airports = statusSnapshot.airports;
  const cached = new Map([...airportPreview, ...list(airports.deferred)].map(row => [row.icao, row]));
  const manual = result.manual.map(row => ({
    ...cached.get(row.icao), ...row, city: row.city || cached.get(row.icao)?.city, origin: "manual",
  }));
  const manualCodes = new Set(manual.map(row => row.icao));
  const deferredCodes = new Set(result.deferred);
  const automatic = airportPreview.filter(row => row.origin !== "manual"
    && !manualCodes.has(row.icao) && !deferredCodes.has(row.icao));
  airports.queued = [...manual, ...automatic].slice(0, 20);
  airports.manual = manual;
  airports.deferred = result.deferred.map(icao => cached.get(icao) || { icao });
  airports.total_deferred = airports.deferred.length;
}

function applyAirportEdit(result) {
  if (!Array.isArray(result.manual) || !Array.isArray(result.deferred) || !statusSnapshot) return;
  airportEdit = result;
  updateAirportQueue(result);
  renderOverview(statusSnapshot);
  renderAirports(statusSnapshot.agent || {}, statusSnapshot.airports, statusSnapshot.budget || {});
}

function updateTicketQueue(result) {
  const tickets = statusSnapshot.tickets;
  const deferred = new Set(result.deferred);
  const priorities = new Map(result.prioritized.map((route, index) => [route, index]));
  const planned = ticketPreview.filter(row => !deferred.has(row.route))
    .map(row => ({ ...row, priority: priorities.has(row.route) }));
  const priorityReady = row => row.priority && row.ready !== false;
  const first = planned.filter(priorityReady).sort((a, b) => priorities.get(a.route) - priorities.get(b.route));
  tickets.planned = [...first, ...planned.filter(row => !priorityReady(row))];
  tickets.deferred = result.deferred;
  tickets.prioritized = result.prioritized;
}

function applyTicketEdit(result) {
  if (!Array.isArray(result.prioritized) || !Array.isArray(result.deferred) || !statusSnapshot) return;
  ticketEdit = result;
  updateTicketQueue(result);
  renderOverview(statusSnapshot);
  renderTickets(statusSnapshot.tickets);
}

async function request(path, body) {
  const headers = { Accept: "application/json", Authorization: "tma " + initData };
  const options = { headers, cache: "no-store", credentials: "omit", redirect: "error" };
  if (body !== undefined) {
    options.method = "POST";
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch("/bot-admin/api/" + path, options);
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    const error = new Error("Request failed");
    error.status = response.status;
    error.publicMessage = typeof failure?.error === "string" ? failure.error : "";
    throw error;
  }
  return response.status === 204 ? {} : response.json();
}

function authFailed(error) {
  if (error.status !== 401 && error.status !== 403) return false;
  accessExpired = true;
  ui.dashboard.hidden = true;
  ui.refresh.hidden = true;
  ui.asOf.hidden = true;
  showNotice(ui.load, "Доступ не подтверждён. Закройте панель и снова откройте её из бота FlightCost.", true);
  return true;
}

function setBusy(value) {
  busy = value;
  ui.refresh.disabled = busy || accessExpired;
  ui.controls.disabled = busy || accessExpired;
  ui.run.disabled = busy || agentActive || accessExpired;
  ui.journalist.disabled = busy || accessExpired;
  for (const button of ui.dashboard.querySelectorAll("[data-queue-action]")) {
    button.disabled = busy || accessExpired;
  }
  ui.dashboard.setAttribute("aria-busy", String(busy));
}

async function refreshStatus() {
  showNotice(ui.load, ui.dashboard.hidden ? "Загружаем данные…" : "");
  try {
    const status = await request("status");
    if (!status || typeof status !== "object" || !status.updates || !status.airports || !status.tickets) {
      throw new Error("Invalid status response");
    }
    renderStatus(status);
    showNotice(ui.load, "");
  } catch (error) {
    if (authFailed(error)) return;
    const text = ui.dashboard.hidden
      ? "Не удалось загрузить данные. Нажмите «Обновить», чтобы повторить."
      : "Не удалось обновить данные. Ниже показано предыдущее состояние.";
    showNotice(ui.load, text, true);
  }
}

async function refresh() {
  if (busy || accessExpired) return;
  setBusy(true);
  try {
    await refreshStatus();
  } finally {
    setBusy(false);
  }
}

async function runAction(path, body, pending, success, onSuccess, notice = ui.action) {
  if (busy || accessExpired || ui.dashboard.hidden) return;
  setBusy(true);
  showNotice(notice, pending);
  try {
    const result = await request(path, body);
    if (onSuccess) onSuccess(result);
    showNotice(notice, success(result));
    if (!onSuccess) await refreshStatus();
  } catch (error) {
    if (authFailed(error)) return;
    const conflict = path === "airports" ? "Аэропорт уже в очереди."
      : path === "run" ? "Агент уже запущен." : "Очередь изменилась. Проверьте её перед повтором.";
    const failure = path === "run"
      ? "Не удалось подтвердить запуск. Проверьте статус агента перед повтором."
      : "Не удалось обновить очередь. Проверьте её перед повтором.";
    showNotice(notice, error.publicMessage || (error.status === 409 ? conflict : failure), true);
    await refreshStatus();
  } finally {
    setBusy(false);
  }
}

if (initData) {
  telegram.ready();
  telegram.expand();
  ui.refresh.hidden = false;
  ui.refresh.addEventListener("click", refresh);
  ui.journalist.addEventListener("click", () => {
    if (!statusSnapshot?.journalist) return;
    runAction("journalist", {paused: !statusSnapshot.journalist.paused}, "Сохраняем…",
      result => result.paused ? "Новые задания приостановлены." : "Подготовка возобновлена.",
      result => {
        statusSnapshot.journalist = result;
        renderJournalist(result);
      }, document.getElementById("journalist-notice"));
  });
  ui.form.addEventListener("submit", event => {
    event.preventDefault();
    const icao = ui.form.elements.icao.value.trim().toUpperCase();
    const city = ui.form.elements.city.value.trim();
    if (!/^[A-Z]{4}$/.test(icao)) return;
    runAction("airports", { icao, city }, "Добавляем аэропорт…",
      result => result.already_queued ? icao + " уже в очереди." : icao + " добавлен в очередь.",
      result => {
        applyAirportEdit(result);
        ui.form.reset();
      });
  });
  ui.run.addEventListener("click", () => {
    if (agentActive) return;
    runAction("run", {}, "Отправляем запрос на запуск…",
      () => "Запрос на запуск принят.");
  });
  refresh();
} else {
  showNotice(ui.load, "Откройте эту панель из бота FlightCost в Telegram.", true);
}
