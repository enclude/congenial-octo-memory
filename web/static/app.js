/* Piro Overlay Web — kreator 5 kroków (vanilla JS, bez zależności).
   Stan przepływu trzymamy w `job`; każdy krok odblokowuje następny. */
"use strict";

const $ = (id) => document.getElementById(id);

const job = {
  id: null,
  duration: 0,
  t0: null,
  hasSession: false,
  noOverlay: false,
};

let es = null; // EventSource aktywnego renderu

/* ── stopka: wersja z backendu (jedno źródło prawdy: __init__.py) ──────── */

fetch("/api/version")
  .then((r) => r.json())
  .then((data) => {
    $("app-version").textContent = "v" + data.version;
    $("repo-link").href = data.repo;
  })
  .catch(() => {}); // stopka ma statyczny link jako fallback — brak wersji nie jest krytyczny

/* ── pomocnicze ─────────────────────────────────────────────── */

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.hidden = true; }, 6000);
}

async function apiError(resp) {
  try {
    const data = await resp.json();
    return data.detail || `HTTP ${resp.status}`;
  } catch {
    return `HTTP ${resp.status}`;
  }
}

function setStep(id, state) {
  $(id).dataset.state = state;
}

function unlock(id) {
  if ($(id).dataset.state === "locked") setStep(id, "active");
}

function fmtS(v) { return `${Number(v).toFixed(1)} s`; }

/* ── krok 1: upload ─────────────────────────────────────────── */

const dropzone = $("dropzone");
const fileInput = $("file-input");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});
["dragover", "dragenter"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, () => dropzone.classList.remove("drag")));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) upload(fileInput.files[0]);
});

function upload(file) {
  // XMLHttpRequest zamiast fetch — tylko XHR raportuje postęp wysyłania.
  const xhr = new XMLHttpRequest();
  $("upload-progress").hidden = false;
  xhr.upload.addEventListener("progress", (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    $("upload-bar").style.width = pct + "%";
    $("upload-pct").textContent = pct + "%";
  });
  xhr.addEventListener("load", () => {
    if (xhr.status !== 201) {
      let msg = `HTTP ${xhr.status}`;
      try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
      toast("Upload odrzucony: " + msg);
      $("upload-progress").hidden = true;
      return;
    }
    const data = JSON.parse(xhr.responseText);
    job.id = data.id;
    job.duration = data.duration || 0;
    const info = $("file-info");
    info.textContent =
      `✓ ${file.name} — ${data.width}×${data.height}, ${fmtS(job.duration)}`;
    info.hidden = false;
    $("upload-progress").hidden = true;
    $("reset-btn").hidden = false;
    setStep("step-upload", "done");
    unlock("step-session");
    unlock("step-analyze");
    initPreviewControls();
    if (data.suggested_id != null) {
      // Ten plik (po nazwie) był już renderowany z tym ID — auto-przypisz, ale
      // pozwól łatwo poprawić (zwykłe pola, „Pobierz” nadpisze przy zmianie ID).
      $("session-id").value = data.suggested_id;
      setSession({ source: "id", id: data.suggested_id }).then((ok) => {
        if (ok) toast(`Auto-przypisano ID ${data.suggested_id} — użyte ostatnio dla tego pliku.`);
      });
    }
  });
  xhr.addEventListener("error", () => toast("Błąd sieci przy uploadzie."));
  xhr.open("POST", "/api/jobs");
  xhr.setRequestHeader("X-Filename", file.name);
  xhr.send(file);
}

/* ── krok 2: oś czasu ───────────────────────────────────────── */

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    $("pane-id").hidden = tab.dataset.tab !== "id";
    $("pane-timeline").hidden = tab.dataset.tab !== "timeline";
  }));

$("fetch-id").addEventListener("click", () =>
  setSession({ source: "id", id: Number($("session-id").value) || null }));
$("parse-timeline").addEventListener("click", () =>
  setSession({ source: "timeline", timeline: $("timeline-text").value }));

$("detect-id-btn").addEventListener("click", async () => {
  const btn = $("detect-id-btn");
  btn.disabled = true;
  btn.textContent = "🔎 Analizuję audio…";
  try {
    const resp = await fetch(`/api/jobs/${job.id}/detect-id`, { method: "POST" });
    if (!resp.ok) { toast(await apiError(resp)); return; }
    const data = await resp.json();
    const out = $("detect-id-result");
    out.hidden = false;
    if (data.id == null) {
      out.textContent = "Nie znaleziono sygnału ID w audio — wpisz ID ręcznie.";
      out.classList.add("warn");
    } else {
      $("session-id").value = data.id;
      out.classList.remove("warn");
      // Auto-pobranie sesji — jak przy suggested_id z historii pliku (upload()):
      // samo wpisanie ID w pole bez pobrania sesji zostawiało "Renderuj" zablokowane
      // (wymaga job.hasSession), co wyglądało na ukończony krok, a nie było.
      const ok = await setSession({ source: "id", id: data.id });
      out.textContent = ok
        ? `✓ Wykryto i pobrano ID ${data.id}.`
        : `✓ Wykryto ID ${data.id}, ale pobranie sesji nie powiodło się — kliknij „Pobierz”.`;
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "🔎 Wykryj z audio";
  }
});

$("no-overlay-check").addEventListener("change", () => {
  // Oś czasu (ID/tekst) zostaje widoczna i opcjonalna nawet bez nakładki — jeśli
  // podana, auto-przycięcie i tak z niej korzysta (ostatni strzał + margines),
  // tyle że render nie wypala żadnej grafiki na wideo.
  job.noOverlay = $("no-overlay-check").checked;
  $("lang-field").hidden = job.noOverlay;
  $("clock-field").hidden = job.noOverlay;
  $("trim-end-field").hidden = job.noOverlay;
  $("duration-field").hidden = !job.noOverlay;
  $("format-select").disabled = job.noOverlay;
  $("no-overlay-hint").hidden = !job.noOverlay;
  if (job.noOverlay) {
    $("format-select").value = "mp4";
    if ($("duration-input").value === "") $("duration-input").value = "75.0";
    syncTrimEndFromDuration();
  }
  refreshRenderReady();
  schedulePreview();
});

function syncTrimEndFromDuration() {
  const t0 = Number($("t0-input").value);
  const dur = Number($("duration-input").value);
  if (Number.isNaN(t0) || Number.isNaN(dur)) return;
  $("trim-end").value = (t0 + dur).toFixed(1);
}

$("duration-input").addEventListener("input", () => {
  syncTrimEndFromDuration();
  refreshRenderReady();
  schedulePreview();
});

async function setSession(body) {
  const resp = await fetch(`/api/jobs/${job.id}/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) { toast(await apiError(resp)); return false; }
  const data = await resp.json();
  job.hasSession = true;
  const meta = data.session_meta || {};
  $("shots-meta").textContent =
    [meta.nazwa_toru, meta.uczestnik, `${data.shots.length} strzałów`]
      .filter(Boolean).join(" · ");
  $("shot-list").innerHTML = data.shots.map((s) =>
    `<li><b>${s.numer}</b> ${s.czas.toFixed(2)}s` +
    (s.split != null ? ` <span>(+${s.split.toFixed(2)})</span>` : "") + "</li>"
  ).join("");
  $("shots").hidden = false;
  setStep("step-session", "done");
  refreshRenderReady();
  schedulePreview();
  return true;
}

/* ── krok 3: detekcja T0 ────────────────────────────────────── */

$("analyze-btn").addEventListener("click", async () => {
  $("analyze-btn").disabled = true;
  $("analyze-btn").textContent = "⏱ Analizuję audio…";
  try {
    const resp = await fetch(`/api/jobs/${job.id}/analyze`, { method: "POST" });
    if (!resp.ok) { toast(await apiError(resp)); return; }
    const data = await resp.json();
    const out = $("analyze-result");
    out.hidden = false;
    if (data.t0 == null) {
      out.textContent = "Nie wykryto bzyczka — ustaw T0 ręcznie w kroku 04.";
      out.classList.add("warn");
    } else {
      job.t0 = data.t0;
      $("t0-input").value = data.t0.toFixed(2);
      if (data.trim_start != null) $("trim-start").value = data.trim_start.toFixed(1);
      if (data.trim_end != null) $("trim-end").value = data.trim_end.toFixed(1);
      if (job.noOverlay && data.trim_end != null) {
        $("duration-input").value = (data.trim_end - data.t0).toFixed(1);
      }
      out.textContent =
        `✓ T0 = ${data.t0.toFixed(2)} s · przycięcie ` +
        `${fmtS(data.trim_start)} → ${fmtS(data.trim_end)}`;
      out.classList.remove("warn");
      $("scrub").value = data.t0;
      $("scrub-label").textContent = `t = ${Number(data.t0).toFixed(1)} s`;
    }
    setStep("step-analyze", "done");
    unlock("step-preview");
    refreshRenderReady();
    schedulePreview();
  } finally {
    $("analyze-btn").disabled = false;
    $("analyze-btn").textContent = "⏱ Wykryj T0 i przytnij";
  }
});

/* ── krok 4: podgląd ────────────────────────────────────────── */

let previewTimer = null;

function initPreviewControls() {
  const scrub = $("scrub");
  scrub.max = job.duration.toFixed(1);
  $("trim-end").value = job.duration.toFixed(1);
  $("trim-start").value = "0.0";
  unlock("step-preview");
  schedulePreview();
}

function schedulePreview() {
  if (!job.id) return;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(loadPreview, 300); // debounce suwaka/pól
}

function loadPreview() {
  const t = Number($("scrub").value);
  const params = new URLSearchParams({
    t: t.toFixed(2),
    lang: $("lang-select").value,
    clock: $("clock-check").checked,
    h: 480,
  });
  const t0 = Number($("t0-input").value);
  if (!Number.isNaN(t0) && $("t0-input").value !== "") params.set("t0", t0);
  $("preview-loading").hidden = false;
  const img = $("preview-img");
  img.onload = img.onerror = () => { $("preview-loading").hidden = true; };
  img.src = `/api/jobs/${job.id}/preview?` + params;
}

$("scrub").addEventListener("input", () => {
  $("scrub-label").textContent = `t = ${Number($("scrub").value).toFixed(1)} s`;
  schedulePreview();
});
["t0-input", "lang-select", "clock-check"].forEach((id) =>
  $(id).addEventListener("input", () => {
    if (id === "t0-input" && job.noOverlay) syncTrimEndFromDuration();
    refreshRenderReady();
    schedulePreview();
  }));
["trim-start", "trim-end"].forEach((id) =>
  $(id).addEventListener("input", refreshRenderReady));

/* ── krok 5: render ─────────────────────────────────────────── */

function refreshRenderReady() {
  const hasT0 = $("t0-input").value !== "";
  const sessionOk = job.noOverlay || job.hasSession;
  if (sessionOk && hasT0) unlock("step-render");
}

$("render-btn").addEventListener("click", async () => {
  const body = {
    format: job.noOverlay ? "mp4" : $("format-select").value,
    lang: $("lang-select").value,
    clock: $("clock-check").checked,
    t0: Number($("t0-input").value),
    trim_start: $("trim-start").value === "" ? null : Number($("trim-start").value),
    trim_end: $("trim-end").value === "" ? null : Number($("trim-end").value),
    no_overlay: job.noOverlay,
  };
  const resp = await fetch(`/api/jobs/${job.id}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) { toast(await apiError(resp)); return; }
  setRenderActive(true);
  $("download-btn").hidden = true;
  $("render-progress").hidden = false;
  setProgress(0);
  resetEta();
  setStatus("W kolejce…");
  watchEvents();
});

$("cancel-btn").addEventListener("click", () =>
  fetch(`/api/jobs/${job.id}/cancel`, { method: "POST" }));

// „Zatrzymaj" aktywny (widoczny + klikalny) wyłącznie w trakcie renderu (queued/rendering) —
// poza tym oknem czasowym jest i schowany, i disabled (podwójna blokada, jak w GUI `setEnabled`).
function setRenderActive(active) {
  $("render-btn").hidden = active;
  $("cancel-btn").hidden = !active;
  $("cancel-btn").disabled = !active;
}

function setProgress(p) {
  const pct = Math.round(p * 100);
  $("render-bar").style.width = pct + "%";
  $("render-pct").textContent = pct + "%";
}

// ETA liczone z tempa postępu od ostatniego punktu odniesienia (`etaBase`), nie od
// zera przy każdym evencie — jedna próbka byłaby zbyt szumiąca (progres FFmpeg nie jest
// liniowy). Punkt odniesienia resetuje się na nowy render (resetEta) i gdy postęp się
// obniży (reconnect na starszy stan) — inaczej dp byłoby ujemne.
let etaBase = null;

function resetEta() {
  etaBase = null;
  $("render-eta").textContent = "";
}

function updateEta(p) {
  const now = Date.now();
  if (etaBase == null || p < etaBase.p) { etaBase = { t: now, p }; return; }
  const dt = (now - etaBase.t) / 1000;
  const dp = p - etaBase.p;
  if (dt < 1 || dp <= 0) return; // za mało danych na sensowną estymację tempa
  const remaining = dt * (1 - p) / dp;
  $("render-eta").textContent = `ETA ~${fmtEta(remaining)}`;
}

function fmtEta(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function setStatus(text, cls) {
  const el = $("render-status");
  el.textContent = text;
  el.className = "render-status mono" + (cls ? " " + cls : "");
}

function renderFinished() {
  setRenderActive(false);
  resetEta();
  if (es) { es.close(); es = null; }
}

function watchEvents() {
  if (es) es.close();
  es = new EventSource(`/api/jobs/${job.id}/events`);
  es.addEventListener("progress", (e) => {
    const p = JSON.parse(e.data).p;
    setProgress(p);
    updateEta(p);
    setStatus("Renderuję…");
  });
  es.addEventListener("encoder", (e) => {
    const name = JSON.parse(e.data).name;
    setStatus(`Renderuję… (enkoder: ${name})`);
  });
  es.addEventListener("done", (e) => {
    setProgress(1);
    setStatus("✓ Gotowe — pobierz plik poniżej.", "ok");
    const dl = $("download-btn");
    dl.href = JSON.parse(e.data).url;
    dl.hidden = false;
    setStep("step-render", "done");
    renderFinished();
  });
  es.addEventListener("error", (e) => {
    if (e.data) setStatus("Błąd renderu: " + JSON.parse(e.data).message, "err");
    $("download-btn").hidden = true;  // błąd nie zostawia gotowego pliku do pobrania
    renderFinished();
  });
  es.addEventListener("state", (e) => {
    const data = JSON.parse(e.data);
    if (data.state === "queued" || data.state === "rendering") {
      // Reconnect / snapshot na wejście SSE — synchronizuje przyciski i postęp z realnym stanem.
      setRenderActive(true);
      setProgress(data.progress);
      updateEta(data.progress);
      if (data.state === "rendering") setStatus("Renderuję…");
      return;
    }
    if (data.state === "cancelled") { setStatus("Przerwano.", "err"); renderFinished(); }
    if (data.state === "done" && data.output_ready) {
      // Snapshot po odświeżeniu strony w trakcie/po renderze.
      setProgress(1);
      const dl = $("download-btn");
      dl.href = `/api/jobs/${job.id}/download`;
      dl.hidden = false;
      renderFinished();
    }
  });
}

/* ── reset ──────────────────────────────────────────────────── */

$("reset-btn").addEventListener("click", async () => {
  if (job.id) await fetch(`/api/jobs/${job.id}`, { method: "DELETE" });
  location.reload();
});
