/* ---------- CONFIG: connect your backend here ----------
   Set API_URL to your endpoint. The page POSTs multipart/form-data:
     image, plantName, climate, stage, symptoms (comma list), notes
   and expects JSON shaped like DEMO_RESULT below.
   While API_URL is empty, the page shows demo results so you can test the flow. */
const API_URL = "";

const SYMPTOMS = ["Yellow halo", "Crispy edges", "Brown spots", "Drooping stem", "White powdery residue"];
const STATUS_STEPS = ["Checking leaf color and patterns", "Looking for spots and lesions", "Comparing against known plant problems", "Ranking likely causes"];
const MAX_BYTES = 20 * 1024 * 1024;

const DEMO_RESULT = {
  plant: "Monstera deliciosa", commonName: "Swiss cheese plant", family: "Araceae",
  status: "Concern", certainty: 94, severity: "Early progression", reversibility: "High (85%+)",
  observations: [
    ["Marginal chlorosis", "Yellowing outer edges, mostly on mature lower leaves."],
    ["Necrotic lesions", "Irregular dark brown spots with yellow rings around them."],
    ["Substrate", "Soil surface looks persistently wet, with moss-like crusting."],
    ["Stems", "Main stems are firm, with no soft or collapsing tissue."]
  ],
  causes: [
    ["Overwatering and early root stress", 88, "Soil that stays saturated starves roots of oxygen and blocks nutrient uptake.", "Most likely driver of the lower leaf yellowing"],
    ["Fungal leaf spot (Cercospora)", 54, "Spores take hold where leaves stay damp and air barely moves.", ""],
    ["Potassium or nitrogen deficiency", 21, "Nutrients may be locked out or washed out by heavy watering.", ""]
  ],
  actions: [
    ["Pause watering and check the roots", "Let the top 2–3 inches of mix dry out fully before the next watering."],
    ["Improve drainage and airflow", "Lift the pot on risers or a saucer so it never sits in water."],
    ["Prune affected leaves", "Cut badly spotted leaves with shears sterilized in 70% isopropyl alcohol."]
  ],
  monitor: ["Yellow halos spreading to young upper leaves within 48 hours", "Softening or blackening at the base of a leaf stalk", "New fronds unfurling green and healthy"],
  disclaimer: "A single photo can’t confirm a diagnosis. If you’re unsure, check with a local plant expert or your university extension office."
};

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = { file: null, url: null, chips: new Set(), timer: null, run: 0 };

function show(name) {
  document.querySelectorAll(".view").forEach(v => v.hidden = v.id !== "view-" + name);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------- symptom chips ---------- */
function chipClass(on) {
  return "px-3 py-1.5 rounded-full text-label-sm border transition-colors flex items-center gap-1 " +
    (on ? "bg-primary text-on-primary border-primary" : "bg-white text-on-surface-variant border-outline-variant hover:border-primary hover:text-primary");
}
function drawChips() {
  $("chips").innerHTML = SYMPTOMS.map(s => {
    const on = state.chips.has(s);
    return `<button type="button" aria-pressed="${on}" data-s="${esc(s)}" class="${chipClass(on)}">${esc(s)}${on ? '<span class="ms text-[14px]">check</span>' : ""}</button>`;
  }).join("");
}
$("chips").addEventListener("click", e => {
  const b = e.target.closest("button[data-s]"); if (!b) return;
  const s = b.dataset.s; state.chips.has(s) ? state.chips.delete(s) : state.chips.add(s);
  drawChips();
});

/* ---------- file handling ---------- */
function fileError(msg) { const el = $("file-error"); el.textContent = msg; el.hidden = !msg; }
function setFile(f) {
  fileError("");
  if (!f) return;
  const okType = /^image\/(png|jpe?g|heic)$/i.test(f.type) || /\.(png|jpe?g|heic)$/i.test(f.name);
  if (!okType) return fileError("That file type isn’t supported. Choose a JPG, PNG or HEIC photo.");
  if (f.size > MAX_BYTES) return fileError("That photo is over 20 MB. Choose a smaller one.");
  if (state.url) URL.revokeObjectURL(state.url);
  state.file = f; state.url = URL.createObjectURL(f);
  const img = $("preview-img"); img.hidden = false; $("preview-fallback").hidden = true; img.src = state.url;
  img.onerror = () => { img.hidden = true; $("preview-fallback").hidden = false; }; // e.g. HEIC in browsers without support
  $("preview-name").textContent = f.name;
  $("preview-meta").textContent = (f.size / 1048576).toFixed(1) + " MB";
  $("preview").hidden = false;
}
function clearFile() {
  if (state.url) URL.revokeObjectURL(state.url);
  state.file = state.url = null; $("file").value = ""; $("preview").hidden = true; fileError("");
}
$("file").addEventListener("change", e => setFile(e.target.files[0]));
$("remove").addEventListener("click", clearFile);
const dz = $("dropzone");
["dragenter", "dragover"].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.add("border-primary-container", "bg-surface-container-low"); }));
["dragleave", "drop"].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.remove("border-primary-container", "bg-surface-container-low"); }));
dz.addEventListener("drop", e => setFile(e.dataTransfer.files[0]));

/* ---------- diagnosis flow ---------- */
async function requestDiagnosis() {
  if (!API_URL) { await new Promise(r => setTimeout(r, 5500)); return structuredClone(DEMO_RESULT); }
  const fd = new FormData();
  fd.append("image", state.file);
  fd.append("plantName", $("plant-name").value.trim());
  fd.append("climate", $("climate").value);
  fd.append("stage", $("stage").value);
  fd.append("symptoms", [...state.chips].join(", "));
  fd.append("notes", $("notes").value.trim());
  const res = await fetch(API_URL, { method: "POST", body: fd });
  if (!res.ok) throw new Error("The server returned an error (" + res.status + ").");
  return res.json();
}

function setProgress(p) {
  $("bar").style.width = p + "%"; $("pct").textContent = p + "%"; $("bar-wrap").setAttribute("aria-valuenow", p);
}

async function startDiagnosis() {
  if (!state.file) { fileError("Add a photo of your plant first."); $("dropzone").scrollIntoView({ behavior: "smooth", block: "center" }); return; }
  const run = ++state.run;
  $("scan-img").src = state.url; $("scan-img").hidden = false; $("scan-icon").hidden = true;
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

/* ---------- report ---------- */
function renderReport(r) {
  const name = $("plant-name").value.trim() || r.plant;
  const thumb = state.url ? `<img src="${state.url}" alt="Your plant photo" class="w-full h-full object-cover">` : `<span class="ms fill text-primary text-[36px]">eco</span>`;
  const causes = r.causes.map(([t, c, d, note], i) => `
    <div class="${i === 0 ? "border-2 border-primary-container" : "border border-outline-variant/30"} bg-white rounded-xl p-5 shadow-sm">
      <div class="flex items-start justify-between gap-3 mb-2">
        <h4 class="text-headline-sm font-bold">${i + 1}. ${esc(t)}</h4>
        <span class="shrink-0 px-2.5 py-0.5 rounded-full text-label-sm ${i === 0 ? "bg-primary text-on-primary" : "bg-surface-container text-on-surface-variant"}">${c >= 70 ? "High" : c >= 40 ? "Medium" : "Low"} ${c}%</span>
      </div>
      <p class="text-body-md text-on-surface-variant">${esc(d)}</p>
      ${note ? `<p class="mt-3 pt-3 border-t border-outline-variant/20 text-label-sm text-primary flex items-center gap-2"><span class="ms text-[16px]">priority_high</span>${esc(note)}</p>` : ""}
    </div>`).join("");
  const actions = r.actions.map(([t, d], i) => i === 0 ? `
    <div class="bg-surface-container-low border border-primary-container/40 rounded-xl p-4">
      <div class="flex items-center gap-2 mb-1.5"><span class="w-5 h-5 rounded-full bg-primary-container text-on-primary text-[11px] font-bold flex items-center justify-center">1</span><span class="text-label-sm text-primary font-bold">Do this first</span></div>
      <p class="text-body-md font-semibold">${esc(t)}</p><p class="text-body-md text-on-surface-variant mt-0.5">${esc(d)}</p>
    </div>` : `
    <div class="p-3.5 rounded-xl border border-outline-variant/20 bg-white">
      <div class="flex items-center gap-2 mb-1"><span class="w-5 h-5 rounded-full bg-surface-container text-[11px] font-bold flex items-center justify-center">${i + 1}</span><span class="text-label-md font-bold">${esc(t)}</span></div>
      <p class="text-body-md text-on-surface-variant">${esc(d)}</p>
    </div>`).join("");

  $("view-report").innerHTML = `
  <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-6">
    <h1 class="text-headline-sm font-bold">Diagnosis report</h1>
    <button id="share" type="button" class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-low hover:bg-surface-container rounded-xl text-label-md border border-outline-variant/30 self-start"><span class="ms text-[18px]">share</span><span id="share-label">Share</span></button>
  </div>
  <section class="card p-5 md:p-6 mb-6 flex flex-col md:flex-row md:items-center justify-between gap-5">
    <div class="flex items-center gap-4">
      <div class="w-24 h-24 rounded-xl overflow-hidden shrink-0 border border-outline-variant/40 bg-surface-container flex items-center justify-center">${thumb}</div>
      <div class="space-y-1">
        <div class="flex flex-wrap items-center gap-2.5"><h2 class="text-headline-md font-bold">${esc(name)}</h2>
          <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-label-md bg-tertiary-fixed text-tertiary-container border border-tertiary/20"><span class="w-1.5 h-1.5 rounded-full bg-tertiary"></span>${esc(r.status)}</span></div>
        <p class="text-body-md text-on-surface-variant">${esc(r.commonName)} • ${esc(r.family)} family</p>
        <p class="text-label-sm text-primary font-semibold flex items-center gap-1"><span class="ms fill text-[15px]">verified</span>${esc(r.certainty)}% match certainty</p>
      </div>
    </div>
    <div class="flex items-center gap-4 bg-surface-container-low px-4 py-3 rounded-xl border border-outline-variant/30 self-start md:self-auto">
      <div><p class="text-label-sm text-outline">Severity</p><p class="text-label-lg text-tertiary font-bold">${esc(r.severity)}</p></div>
      <div class="h-8 w-px bg-outline-variant/40"></div>
      <div><p class="text-label-sm text-outline">Reversibility</p><p class="text-label-lg text-primary font-bold">${esc(r.reversibility)}</p></div>
    </div>
  </section>
  <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
    <div class="lg:col-span-7 space-y-6">
      <section class="card p-5 md:p-6">
        <h3 class="text-headline-sm font-bold pb-4 mb-4 border-b border-outline-variant/20 flex items-center gap-2"><span class="ms fill text-primary">visibility</span>What we see</h3>
        <ul class="space-y-3.5">${r.observations.map(([t, d]) => `<li class="flex items-start gap-3"><span class="w-5 h-5 rounded-full bg-secondary-container/40 text-secondary flex items-center justify-center shrink-0 mt-0.5"><span class="ms text-[14px]">check</span></span><p class="text-body-md"><strong>${esc(t)}:</strong> <span class="text-on-surface-variant">${esc(d)}</span></p></li>`).join("")}</ul>
      </section>
      <section class="space-y-4">
        <div class="flex items-center justify-between"><h3 class="text-headline-sm font-bold">Possible causes</h3><span class="text-label-sm text-outline">Most likely first</span></div>
        ${causes}
      </section>
    </div>
    <div class="lg:col-span-5 space-y-6">
      <section class="card p-5 md:p-6">
        <h3 class="text-headline-sm font-bold pb-4 mb-4 border-b border-outline-variant/20 flex items-center gap-2"><span class="ms fill text-primary">task_alt</span>Recommended actions</h3>
        <div class="space-y-3.5">${actions}</div>
      </section>
      <section class="card p-5 md:p-6">
        <div class="flex items-center justify-between pb-3 mb-3 border-b border-outline-variant/20"><h3 class="text-headline-sm font-bold">What to watch</h3><span class="text-label-sm text-tertiary font-semibold bg-tertiary-fixed/60 px-2 py-0.5 rounded-full">Next 48–72 hours</span></div>
        <div class="space-y-3">${r.monitor.map(m => `<label class="flex items-start gap-3 cursor-pointer"><input type="checkbox" class="mt-0.5 rounded w-5 h-5 text-primary-container border-outline-variant focus:ring-primary-container"><span class="text-body-md">${esc(m)}</span></label>`).join("")}</div>
      </section>
      <div class="bg-surface-container-low border border-outline-variant/40 rounded-xl p-4 flex items-start gap-3"><span class="ms text-outline text-[20px] shrink-0">info</span><p class="text-body-sm text-on-surface-variant">${esc(r.disclaimer)}</p></div>
      <div class="flex flex-col sm:flex-row gap-3">
        <button id="followup" type="button" class="w-full sm:flex-1 h-12 rounded-xl bg-surface-container-low hover:bg-surface-container text-primary text-label-lg border border-outline-variant/30 flex items-center justify-center gap-2"><span class="ms text-[18px]">edit_note</span>Add details</button>
        <button id="another" type="button" class="w-full sm:flex-1 h-12 rounded-xl bg-primary-container hover:bg-primary text-on-primary text-label-lg shadow-sm flex items-center justify-center gap-2"><span class="ms text-[18px]">add_a_photo</span>Diagnose another plant</button>
      </div>
    </div>
  </div>`;

  $("another").onclick = () => { clearFile(); $("plant-name").value = $("notes").value = ""; state.chips.clear(); drawChips(); show("upload"); };
  $("followup").onclick = () => { show("upload"); setTimeout(() => $("notes").focus(), 300); };
  $("share").onclick = async () => {
    const text = `${name}: ${r.causes[0][0]} (${r.certainty}% match). First step: ${r.actions[0][0]}.`;
    try {
      if (navigator.share) await navigator.share({ title: "PlantCare AI diagnosis", text });
      else { await navigator.clipboard.writeText(text); $("share-label").textContent = "Copied"; setTimeout(() => $("share-label").textContent = "Share", 1800); }
    } catch (_) { /* share cancelled */ }
  };
}

/* ---------- wiring ---------- */
$("diagnose").addEventListener("click", startDiagnosis);
$("cancel").addEventListener("click", cancelDiagnosis);
const goHome = e => { e.preventDefault(); if (!$("view-analyzing").hidden) cancelDiagnosis(); else show("upload"); };
$("brand").addEventListener("click", goHome);
$("nav-diagnose").addEventListener("click", goHome);
$("scan-btn").addEventListener("click", () => { show("upload"); $("file").click(); });
drawChips();
