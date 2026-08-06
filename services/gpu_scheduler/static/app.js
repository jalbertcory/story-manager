const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const DAY_LABELS = Object.fromEntries(DAYS.map((day) => [day, day[0].toUpperCase() + day.slice(1)]));

let latestState = null;
let editing = false;

const byId = (id) => document.getElementById(id);

function scheduleRow(day) {
  return `
    <div class="day-row" data-day="${day}">
      <input class="day-check" type="checkbox" aria-label="Enable ${DAY_LABELS[day]}" />
      <strong>${DAY_LABELS[day]}</strong>
      <input class="day-start" type="time" value="08:00" aria-label="${DAY_LABELS[day]} start" />
      <input class="day-end" type="time" value="23:00" aria-label="${DAY_LABELS[day]} end" />
    </div>`;
}

function initialiseSchedule() {
  byId("schedule").innerHTML = DAYS.map(scheduleRow).join("");
  byId("schedule").addEventListener("input", (event) => {
    editing = true;
    const row = event.target.closest(".day-row");
    if (row) row.classList.toggle("disabled", !row.querySelector(".day-check").checked);
  });
  ["enabled", "timezone", "stop-timeout"].forEach((id) => byId(id).addEventListener("input", () => { editing = true; }));
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map((item) => item.msg).join("; ") : body.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return body;
}

function formatDate(value) {
  if (!value) return "No scheduled change";
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short",
  }).format(date);
}

function hydrateForm(config) {
  if (editing) return;
  byId("enabled").checked = config.enabled;
  byId("timezone").value = config.timezone;
  byId("stop-timeout").value = config.stop_timeout_seconds;
  DAYS.forEach((day) => {
    const row = document.querySelector(`[data-day="${day}"]`);
    const window = config.schedule[day]?.[0];
    row.querySelector(".day-check").checked = Boolean(window);
    row.querySelector(".day-start").value = window?.start || "08:00";
    row.querySelector(".day-end").value = window?.end || "23:00";
    row.classList.toggle("disabled", !window);
  });
}

function render(state) {
  latestState = state;
  hydrateForm(state.config);

  const desired = state.desired_available;
  const pill = byId("status-pill");
  pill.className = `status-pill ${desired === true ? "available" : desired === false ? "unavailable" : "neutral"}`;
  pill.innerHTML = `<span></span>${desired === true ? "AI available" : desired === false ? "Gaming protected" : "Observe only"}`;

  const policyLabels = { schedule: "Weekly schedule", override: "Temporary override", disabled: "Scheduling disabled" };
  byId("policy-value").textContent = policyLabels[state.policy_source] || state.policy_source;
  byId("policy-detail").textContent = state.config.override_mode !== "automatic"
    ? `${state.config.override_mode} until ${state.config.override_until ? formatDate(state.config.override_until) : "changed"}`
    : desired === null ? "Containers will not be changed" : desired ? "Services should be running" : "Services should be stopped";

  byId("next-value").textContent = state.next_transition ? formatDate(state.next_transition).split(",")[0] : "No change";
  byId("next-detail").textContent = state.next_transition ? formatDate(state.next_transition) : "Current policy remains in effect";

  const running = state.containers.filter((container) => container.status === "running").length;
  byId("container-count").textContent = `${running} / ${state.containers.length} running`;
  byId("container-detail").textContent = state.containers.length ? "Only labeled services are managed" : "No managed containers discovered";
  byId("label-hint").textContent = state.managed_label;

  byId("containers").innerHTML = state.containers.length
    ? state.containers.map((container) => `
      <div class="container-card">
        <span class="container-dot ${container.status === "running" ? "running" : ""}"></span>
        <div class="container-name"><strong>${escapeHtml(container.name)}</strong><small>${escapeHtml(container.image)}</small></div>
        <span class="container-state">${escapeHtml(container.health || container.status)}</span>
      </div>`).join("")
    : `<div class="empty-state">Add the managed label to Ollama, OmniVoice, or WhisperX, then refresh.</div>`;

  const error = byId("error-banner");
  error.textContent = state.last_error ? `Docker connection: ${state.last_error}` : "";
  error.classList.toggle("hidden", !state.last_error);
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value ?? "";
  return element.innerHTML;
}

function collectConfig() {
  const schedule = {};
  DAYS.forEach((day) => {
    const row = document.querySelector(`[data-day="${day}"]`);
    schedule[day] = row.querySelector(".day-check").checked
      ? [{ start: row.querySelector(".day-start").value, end: row.querySelector(".day-end").value }]
      : [];
  });
  return {
    enabled: byId("enabled").checked,
    timezone: byId("timezone").value.trim(),
    schedule,
    stop_timeout_seconds: Number(byId("stop-timeout").value),
    override_mode: latestState?.config.override_mode || "automatic",
    override_until: latestState?.config.override_until || null,
  };
}

async function loadState(reconcile = false) {
  try {
    const state = await request(reconcile ? "/api/reconcile" : "/api/state", reconcile ? { method: "POST" } : {});
    render(state);
  } catch (error) {
    const banner = byId("error-banner");
    banner.textContent = error.message;
    banner.classList.remove("hidden");
  }
}

async function saveConfig() {
  const button = byId("save-button");
  const message = byId("save-message");
  button.disabled = true;
  message.textContent = "Saving…";
  try {
    const state = await request("/api/config", { method: "PUT", body: JSON.stringify(collectConfig()) });
    editing = false;
    render(state);
    message.textContent = "Schedule saved";
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
    setTimeout(() => { message.textContent = ""; }, 3500);
  }
}

async function setOverride(button) {
  const mode = button.dataset.override;
  const minutes = button.dataset.minutes ? Number(button.dataset.minutes) : null;
  button.disabled = true;
  try {
    const state = await request("/api/override", {
      method: "POST",
      body: JSON.stringify({ mode, duration_minutes: minutes }),
    });
    render(state);
  } catch (error) {
    const banner = byId("error-banner");
    banner.textContent = error.message;
    banner.classList.remove("hidden");
  } finally {
    button.disabled = false;
  }
}

initialiseSchedule();
byId("save-button").addEventListener("click", saveConfig);
byId("refresh-button").addEventListener("click", () => loadState(true));
document.querySelectorAll("[data-override]").forEach((button) => button.addEventListener("click", () => setOverride(button)));
loadState(true);
setInterval(() => loadState(false), 5000);
