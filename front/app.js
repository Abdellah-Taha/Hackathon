/* ---------- CONFIG: connect your backend here ----------
   Set API_URL to your endpoint. The page POSTs multipart/form-data:
     image, plantName, climate, stage, symptoms (comma list), notes
   and expects JSON shaped like DEMO_RESULT below.
   While API_URL is empty, the page shows demo results so you can test the flow. */
const API_URL = "";

const STATUS_STEPS = ["Examining leaf patterns & chlorosis…", "Checking spots and lesions…", "Comparing against known plant problems…", "Ranking likely causes…"];
const MAX_BYTES = 20 * 1024 * 1024;

const DEMO_RESULT = {
  plant: { name: "Monstera deliciosa", commonName: "Swiss cheese plant", family: "Araceae" },
  status: "concern",            // "healthy" | "concern" | "critical"
  certainty: 94,                // 0-100
  severity: "Early progression",
  reversibility: "High (85%+)",
  observations: [
    { title: "Marginal chlorosis", detail: "Yellowing outer edges, mostly on mature lower leaves." },
    { title: "Necrotic lesions", detail: "Irregular dark brown spots with yellow rings around them." },
    { title: "Substrate", detail: "Soil surface looks persistently wet, with moss-like crusting." },
    { title: "Stems", detail: "Main stems are firm, with no soft or collapsing tissue." }
  ],
  causes: [   // most likely first
    { name: "Overwatering and early root stress", confidence: 88, description: "Soil that stays saturated starves roots of oxygen and blocks nutrient uptake.", note: "Most likely driver of the lower leaf yellowing" },
    { name: "Fungal leaf spot (Cercospora)", confidence: 54, description: "Spores take hold where leaves stay damp and air barely moves." },
    { name: "Potassium or nitrogen deficiency", confidence: 21, description: "Nutrients may be locked out or washed out by heavy watering." }
  ],
  actions: [  // first one is shown as "Do this first"
    { title: "Pause watering and check the roots", detail: "Let the top 2–3 inches of mix dry out fully before the next watering." },
    { title: "Improve drainage and airflow", detail: "Lift the pot on risers or a saucer so it never sits in water." },
    { title: "Prune affected leaves", detail: "Cut badly spotted leaves with shears sterilized in 70% isopropyl alcohol." }
  ],
  monitor: ["Yellow halos spreading to young upper leaves within 48 hours", "Softening or blackening at the base of a leaf stalk", "New fronds unfurling green and healthy"],
  disclaimer: "A single photo can’t confirm a diagnosis. If you’re unsure, check with a local plant expert or your university extension office."
};

const STATUS = {
  healthy:  { label: "Healthy",  badge: "bg-secondary-container text-on-secondary-container border-secondary/20", dot: "bg-secondary" },
  concern:  { label: "Concern",  badge: "bg-tertiary-fixed text-tertiary-container border-tertiary/20", dot: "bg-tertiary" },
  critical: { label: "Critical", badge: "bg-error-container text-error border-error/20", dot: "bg-error" }
};

/* Returns "" if the result is usable, otherwise a message saying what is missing. */
function validateResult(r) {
  if (!r || typeof r !== "object") return "The file is not a JSON object.";
  if (!r.plant || !r.plant.name) return "Missing “plant.name”.";
  if (typeof r.certainty !== "number") return "“certainty” must be a number from 0 to 100.";
  for (const k of ["severity", "reversibility"]) if (!r[k]) return `Missing “${k}”.`;
  for (const k of ["observations", "causes", "actions", "monitor"])
    if (!Array.isArray(r[k]) || !r[k].length) return `“${k}” must be a non-empty list.`;
  if (r.causes.some(c => !c.name || typeof c.confidence !== "number")) return "Each cause needs a “name” and a numeric “confidence”.";
  if (r.actions.some(a => !a.title)) return "Each action needs a “title”.";
  return "";
}

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = { file: null, url: null, dims: "", session: "", timer: null, run: 0 };

function show(name) {
  document.querySelectorAll(".view").forEach(v => v.hidden = v.id !== "view-" + name);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------- file handling ---------- */
function fileError(msg) { const el = $("file-error"); el.textContent = msg; el.hidden = !msg; }
function toast(msg) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3500); }
function setFile(f) {
  fileError("");
  if (!f) return;
  const okType = /^image\/(png|jpe?g|heic)$/i.test(f.type) || /\.(png|jpe?g|heic)$/i.test(f.name);
  if (!okType) return fileError("That file type isn’t supported. Choose a JPG, PNG or HEIC photo.");
  if (f.size > MAX_BYTES) return fileError("That photo is over 20 MB. Choose a smaller one.");
  if (state.url) URL.revokeObjectURL(state.url);
  state.file = f; state.url = URL.createObjectURL(f); state.dims = "";
  const img = $("preview-img"), size = (f.size / 1048576).toFixed(1) + " MB";
  img.hidden = false; $("preview-fallback").hidden = true;
  $("preview-name").textContent = f.name; $("preview-meta").textContent = size; $("preview-note").textContent = "Checking photo…";
  img.onload = () => {
    state.dims = img.naturalWidth + " × " + img.naturalHeight;
    $("preview-meta").textContent = size + " • " + state.dims;
    $("preview-note").textContent = Math.min(img.naturalWidth, img.naturalHeight) >= 800 ? "Good resolution" : "Low resolution: a closer photo works better";
  };
  img.onerror = () => { img.hidden = true; $("preview-fallback").hidden = false; $("preview-note").textContent = "Preview unavailable, the photo will still be analyzed"; }; // e.g. HEIC
  img.src = state.url;
  $("preview").hidden = false;
}
function clearFile() {
  if (state.url) URL.revokeObjectURL(state.url);
  state.file = state.url = null; state.dims = ""; $("file").value = ""; $("preview").hidden = true; fileError("");
}
/* A drawn stand-in photo so the flow can be tested without a real image. */
function makeSample() {
  const c = document.createElement("canvas"); c.width = 800; c.height = 1000; const x = c.getContext("2d");
  x.fillStyle = "#e9efe0"; x.fillRect(0, 0, 800, 1000);
  x.fillStyle = "#2e7d32"; x.beginPath(); x.moveTo(400, 80); x.bezierCurveTo(780, 260, 760, 760, 400, 930); x.bezierCurveTo(40, 760, 20, 260, 400, 80); x.fill();
  x.strokeStyle = "#cfd96b"; x.lineWidth = 26; x.stroke();
  x.strokeStyle = "#1b5e20"; x.lineWidth = 6; x.beginPath(); x.moveTo(400, 100); x.lineTo(400, 920); x.stroke();
  x.fillStyle = "#6b4a2f"; [[250, 350, 22], [560, 460, 28], [330, 640, 18], [520, 700, 24]].forEach(([a, b, r]) => { x.beginPath(); x.arc(a, b, r, 0, 7); x.fill(); });
  c.toBlob(b => setFile(new File([b], "sample-leaf.jpg", { type: "image/jpeg" })), "image/jpeg", 0.9);
}

/* ---------- diagnosis flow ---------- */
async function requestDiagnosis() {
  if (!API_URL) { await new Promise(r => setTimeout(r, 5500)); return structuredClone(DEMO_RESULT); }
  const fd = new FormData(); fd.append("image", state.file);
  const res = await fetch(API_URL, { method: "POST", body: fd });
  if (!res.ok) throw new Error("The server returned an error (" + res.status + ").");
  const data = await res.json();
  const problem = validateResult(data);
  if (problem) throw new Error("The result was incomplete: " + problem);
  return data;
}
function setProgress(p) { $("bar").style.width = p + "%"; $("pct").textContent = p + "%"; }

async function startDiagnosis() {
  if (!state.file) { fileError("Add a photo of your plant first."); $("dropzone").scrollIntoView({ behavior: "smooth", block: "center" }); return; }
  const run = ++state.run;
  state.session = String(1000 + Math.floor(Math.random() * 9000));
  $("session").textContent = "#PCA-" + state.session + "-FL";
  $("res").textContent = state.dims ? "Resolution " + state.dims : "Resolution unknown";
  setProgress(0); show("analyzing");
  let p = 0, step = 0; $("status").textContent = STATUS_STEPS[0];
  state.timer = setInterval(() => {
    p = Math.min(92, p + Math.floor(Math.random() * 4) + 2); setProgress(p);
    const s = Math.min(STATUS_STEPS.length - 1, Math.floor(p / 25));
    if (s !== step) { step = s; $("status").textContent = STATUS_STEPS[s]; }
  }, 450);
  try {
    const result = await requestDiagnosis();
    if (run !== state.run) return; // cancelled
    clearInterval(state.timer); setProgress(100);
    setTimeout(() => { if (run === state.run) { renderReport(result); show("report"); } }, 350);
  } catch (err) {
    if (run !== state.run) return;
    clearInterval(state.timer); show("upload");
    fileError("We couldn’t analyze that photo. " + (err.message || "") + " Check your connection and try again.");
  }
}
function cancelDiagnosis() { state.run++; clearInterval(state.timer); show("upload"); }

/* ---------- report (layout from your design, values from the JSON) ---------- */
function renderReport(r) {
  const st = STATUS[r.status] || STATUS.concern;
  const id = r.id || state.session || String(1000 + Math.floor(Math.random() * 9000));
  const lvl = c => c >= 70 ? "High" : c >= 40 ? "Medium" : "Low";
  const thumb = state.url ? `<img alt="Your plant photo" class="w-full h-full object-cover" src="${state.url}">` : `<span class="material-symbols-outlined fill text-primary text-[32px]">eco</span>`;
  const obs = r.observations.map(({ title: t, detail: d = "" }) => `
    <li class="flex items-start gap-3"><div class="w-5 h-5 rounded-full bg-secondary-container/40 text-secondary flex items-center justify-center shrink-0 mt-0.5"><span class="material-symbols-outlined text-[14px]">check</span></div>
    <div class="text-body-md font-body-md text-on-surface"><strong class="font-label-lg text-on-surface">${esc(t)}:</strong> <span class="text-on-surface-variant">${esc(d)}</span></div></li>`).join("");
  const causes = r.causes.map(({ name: t, confidence: c, description: d = "", note }, i) => `
    <div class="bg-surface-container-lowest ${i === 0 ? "border-2 border-primary-container scale-[1.005]" : "border border-outline-variant/30 hover:border-outline-variant"} rounded-xl p-5 shadow-sm transition-colors">
      <div class="flex items-start justify-between gap-3 mb-2"><h4 class="text-headline-sm font-headline-sm font-bold text-on-surface">${i + 1}. ${esc(t)}</h4>
      <span class="shrink-0 inline-flex items-center px-2.5 py-0.5 rounded-full text-label-sm font-label-sm ${i === 0 ? "bg-primary text-on-primary font-semibold shadow-xs" : "bg-surface-container text-on-surface-variant font-medium"}">${lvl(c)}${i === 0 ? " Confidence" : ""} ${esc(c)}%</span></div>
      <p class="text-body-md font-body-md text-on-surface-variant">${esc(d)}</p>
      ${note ? `<div class="mt-3 pt-3 border-t border-outline-variant/20 flex items-center gap-2 text-label-sm font-label-sm text-primary font-semibold"><span class="material-symbols-outlined text-[16px]">priority_high</span><span>${esc(note)}</span></div>` : ""}
    </div>`).join("");
  const actions = r.actions.map(({ title: t, detail: d = "" }, i) => i === 0 ? `
    <div class="bg-surface-container-low border border-primary-container/40 rounded-xl p-4">
      <div class="flex items-center gap-2 mb-1.5"><span class="w-5 h-5 rounded-full bg-primary-container text-on-primary text-[11px] font-bold flex items-center justify-center">1</span><span class="text-label-sm font-label-sm text-primary font-bold tracking-wide uppercase">Immediate Priority</span></div>
      <p class="text-body-md font-body-md text-on-surface font-semibold">${esc(t)}</p><p class="text-body-md font-body-md text-on-surface-variant mt-0.5">${esc(d)}</p></div>` : `
    <div class="p-3.5 rounded-xl border border-outline-variant/20 bg-surface-container-lowest">
      <div class="flex items-center gap-2 mb-1"><span class="w-5 h-5 rounded-full bg-surface-container text-on-surface text-[11px] font-bold flex items-center justify-center">${i + 1}</span><span class="text-label-md font-label-md font-bold text-on-surface">${esc(t)}</span></div>
      <p class="text-body-md font-body-md text-on-surface-variant">${esc(d)}</p></div>`).join("");
  const cardHead = (icon, title) => `<div class="flex items-center gap-2.5 pb-4 mb-4 border-b border-outline-variant/20"><div class="w-8 h-8 rounded-lg bg-surface-container-low text-primary flex items-center justify-center"><span class="material-symbols-outlined fill">${icon}</span></div><h3 class="text-headline-sm font-headline-sm font-bold text-on-surface">${title}</h3></div>`;

  $("view-report").innerHTML = `
  <div class="flex flex-col sm:flex-row sm:items-center justify-between pb-6 gap-3">
    <div class="flex items-center gap-2 text-on-surface-variant">
      <button id="history" type="button" class="font-body-sm text-body-sm hover:text-primary transition-colors">Diagnostic History</button>
      <span class="material-symbols-outlined text-[16px] text-outline">chevron_right</span>
      <h1 class="text-headline-sm font-headline-sm text-on-surface font-bold tracking-tight">Diagnosis Report #${esc(id)}</h1>
    </div>
    <div class="flex items-center gap-2">
      <button id="share" type="button" class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-low hover:bg-surface-container text-on-surface rounded-xl text-label-md font-label-md border border-outline-variant/30 transition-colors"><span class="material-symbols-outlined text-[18px]">share</span><span id="share-label">Share</span></button>
      <button id="guide" type="button" class="inline-flex items-center gap-1 px-2.5 py-1.5 text-on-surface-variant hover:text-on-surface rounded-xl text-label-md font-label-md hover:bg-surface-container-low transition-colors" title="Need help reading this?"><span class="material-symbols-outlined text-[18px]">help</span><span class="hidden sm:inline">Guide</span></button>
    </div>
  </div>
  <section class="bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-5 md:p-6 mb-6 shadow-sm">
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-5">
      <div class="flex items-center gap-4 md:gap-5">
        <div class="relative w-20 h-20 md:w-24 md:h-24 rounded-xl overflow-hidden shrink-0 border border-outline-variant/40 shadow-inner bg-surface-container flex items-center justify-center">${thumb}
          <span class="absolute bottom-1 right-1 bg-surface-container-lowest/90 backdrop-blur-sm p-1 rounded-lg text-primary shadow-sm flex items-center justify-center"><span class="material-symbols-outlined text-[14px]">search</span></span></div>
        <div class="space-y-1">
          <div class="flex flex-wrap items-center gap-2.5"><h2 class="text-headline-md font-headline-md text-on-surface font-bold">${esc(r.plant.name)}</h2>
            <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-label-md font-label-md border ${st.badge}"><span class="w-1.5 h-1.5 rounded-full ${st.dot}"></span>${st.label}</span></div>
          <p class="text-body-md font-body-md text-on-surface-variant">${esc(r.plant.commonName || "")}${r.plant.family ? " • " + esc(r.plant.family) + " family" : ""}</p>
          <div class="flex items-center gap-3 pt-1 text-label-sm font-label-sm text-outline">
            <span class="inline-flex items-center gap-1"><span class="material-symbols-outlined text-[15px]">schedule</span>Diagnosed Today</span><span>•</span>
            <span class="inline-flex items-center gap-1 text-primary font-semibold"><span class="material-symbols-outlined fill text-[15px]">verified</span>${esc(r.certainty)}% match certainty</span></div>
        </div>
      </div>
      <div class="flex sm:self-auto self-start items-center gap-3 bg-surface-container-low px-4 py-3 rounded-xl border border-outline-variant/30">
        <div class="text-left"><p class="text-label-sm font-label-sm text-outline">Stage Severity</p><p class="text-label-lg font-label-lg text-tertiary font-bold">${esc(r.severity)}</p></div>
        <div class="h-8 w-px bg-outline-variant/40"></div>
        <div class="text-left"><p class="text-label-sm font-label-sm text-outline">Reversibility</p><p class="text-label-lg font-label-lg text-primary font-bold">${esc(r.reversibility)}</p></div>
      </div>
    </div>
  </section>
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
    <div class="lg:col-span-7 space-y-6">
      <section class="bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-5 md:p-6 shadow-sm">${cardHead("visibility", "What we see")}<ul class="space-y-3.5">${obs}</ul></section>
      <section class="space-y-4">
        <div class="flex items-center justify-between"><div class="flex items-center gap-2"><span class="material-symbols-outlined text-primary text-[22px]">analytics</span><h3 class="text-headline-sm font-headline-sm font-bold text-on-surface">Possible causes</h3></div><span class="text-label-sm font-label-sm text-outline">Ranked by diagnostic confidence</span></div>
        ${causes}
      </section>
    </div>
    <div class="lg:col-span-5 space-y-6">
      <section class="bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-5 md:p-6 shadow-sm">${cardHead("task_alt", "Recommended actions")}<div class="space-y-3.5">${actions}</div></section>
      <section class="bg-surface-container-lowest border border-outline-variant/30 rounded-xl p-5 md:p-6 shadow-sm">
        <div class="flex items-center justify-between pb-3 mb-3 border-b border-outline-variant/20"><div class="flex items-center gap-2"><span class="material-symbols-outlined text-tertiary">timelapse</span><h3 class="text-headline-sm font-headline-sm font-bold text-on-surface">What to monitor</h3></div><span class="text-label-sm font-label-sm text-tertiary font-semibold bg-tertiary-fixed/60 px-2 py-0.5 rounded-full">Next 48–72 hours</span></div>
        <div class="space-y-3">${r.monitor.map(m => `<label class="flex items-start gap-3 cursor-pointer group"><input type="checkbox" class="mt-0.5 rounded w-5 h-5 text-primary-container border-outline-variant focus:ring-primary-container"><span class="text-body-md font-body-md text-on-surface group-hover:text-primary transition-colors">${esc(m)}</span></label>`).join("")}</div>
      </section>
      <div class="bg-surface-container-low border border-outline-variant/40 rounded-xl p-4 flex items-start gap-3"><span class="material-symbols-outlined text-outline shrink-0 mt-0.5">info</span><p class="text-body-sm font-body-sm text-on-surface-variant">${esc(r.disclaimer || DEMO_RESULT.disclaimer)}</p></div>
      <div class="flex flex-col sm:flex-row items-center gap-3 pt-2">
        <button id="followup" type="button" class="w-full sm:flex-1 h-12 rounded-xl bg-surface-container-low hover:bg-surface-container text-primary font-label-lg text-label-lg transition-colors border border-outline-variant/30 flex items-center justify-center gap-2"><span class="material-symbols-outlined text-[18px]">chat</span><span>Ask follow-up</span></button>
        <button id="another" type="button" class="w-full sm:flex-1 h-12 rounded-xl bg-primary-container hover:bg-primary text-on-primary font-label-lg text-label-lg transition-colors shadow-sm flex items-center justify-center gap-2"><span class="material-symbols-outlined text-[18px]">add_a_photo</span><span>Diagnose another plant</span></button>
      </div>
    </div>
  </div>`;

  $("another").onclick = () => { clearFile(); show("upload"); };
  $("history").onclick = () => show("upload");
  $("guide").onclick = () => toast("Causes are ranked by confidence, and actions are in priority order.");
  $("followup").onclick = () => {   // hook: listen for this event to open your own chat or form
    if (window.dispatchEvent(new CustomEvent("plantcare:followup", { detail: r, cancelable: true }))) toast("Follow-up chat isn’t connected yet.");
  };
  $("share").onclick = async () => {
    const text = `${r.plant.name}: ${r.causes[0].name} (${r.certainty}% match). First step: ${r.actions[0].title}.`;
    try {
      if (navigator.share) await navigator.share({ title: "PlantCare AI diagnosis", text });
      else { await navigator.clipboard.writeText(text); $("share-label").textContent = "Copied"; setTimeout(() => $("share-label").textContent = "Share", 1800); }
    } catch (_) { /* share cancelled */ }
  };
}

/* ---------- load a result from a .json file ---------- */
$("json-file").addEventListener("change", async e => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    const problem = validateResult(data);
    if (problem) throw new Error(problem);
    fileError(""); renderReport(data); show("report");
  } catch (err) {
    fileError("Couldn’t load that result file. " + err.message);
  }
  e.target.value = "";
});

/* ---------- wiring ---------- */
$("file").addEventListener("change", e => setFile(e.target.files[0]));
$("remove").addEventListener("click", clearFile);
$("view-full").addEventListener("click", () => state.url && window.open(state.url, "_blank"));
$("sample").addEventListener("click", makeSample);
const dz = $("dropzone");
dz.addEventListener("click", e => { if (!e.target.closest("button,label,input")) $("file").click(); });
["dragenter", "dragover"].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.add("border-primary-container", "bg-surface-container-low"); }));
["dragleave", "drop"].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.remove("border-primary-container", "bg-surface-container-low"); }));
dz.addEventListener("drop", e => setFile(e.dataTransfer.files[0]));
$("diagnose").addEventListener("click", startDiagnosis);
$("cancel").addEventListener("click", cancelDiagnosis);
const goHome = e => { e.preventDefault(); if (!$("view-analyzing").hidden) cancelDiagnosis(); else show("upload"); };
$("brand").addEventListener("click", goHome);
$("nav-diagnose").addEventListener("click", goHome);
$("scan-btn").addEventListener("click", () => { show("upload"); $("file").click(); });
