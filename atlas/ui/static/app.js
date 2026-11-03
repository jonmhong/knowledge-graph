// Atlas UI: a tiny hash-routed single page. No framework, no build step.
// tour.js (the first-run tutorial) builds on the globals defined here.
"use strict";

const $main = document.getElementById("main");
const GRAPH_NAMES = { mine: "My knowledge graph", demo: "Demo" };
const state = {
  graph: localStorage.getItem("atlas.graph") === "demo" ? "demo" : "mine",
  job: null,        // latest job snapshot from the server (lines accumulated here)
  jobSeq: 0,        // bumps every time this page starts a job (the tour waits on it)
  polling: false,
  lastAsk: null,    // {graph, question, html, coverage, filed_back_path}
  addMode: "files", // which "Add sources" option is open: files | link | paste
};

// ---------------------------------------------------------------- helpers

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function api(path, { method = "GET", body, raw } = {}) {
  // Every API call is scoped to the knowledge graph currently selected.
  if (path.startsWith("/api/")) path += (path.includes("?") ? "&" : "?") + "graph=" + state.graph;
  const opts = { method, headers: {} };
  if (raw !== undefined) {
    opts.body = raw;
    opts.headers["Content-Type"] = "application/octet-stream";
  } else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error("Can't reach Atlas. Is the Atlas window still open?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Something went wrong (${res.status}).`);
  return data;
}

let toastTimer;
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 4500);
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many || one + "s"}`;
}

function busy() {
  return state.job && state.job.status === "running";
}

function inDemo() {
  return state.graph === "demo";
}

// ---------------------------------------------------------------- graphs

function setGraph(graph) {
  if (graph === state.graph) return;
  if (window.Tour && !Tour.allowGraph(graph)) return;
  state.graph = graph;
  localStorage.setItem("atlas.graph", graph);
  renderGraphChrome();
  route();
}

function renderGraphChrome() {
  document.querySelectorAll("#graph-switch [data-graph]").forEach((b) => {
    const on = b.dataset.graph === state.graph;
    b.classList.toggle("selected", on);
    b.setAttribute("aria-pressed", on);
  });
  document.getElementById("demobar").hidden = !inDemo();
  document.body.classList.toggle("in-demo", inDemo());
}

document.querySelectorAll("#graph-switch [data-graph]").forEach((b) =>
  b.addEventListener("click", () => setGraph(b.dataset.graph)));
document.getElementById("demobar-switch").addEventListener("click", () => setGraph("mine"));

// ---------------------------------------------------------------- jobs

function adoptJob(snapshot) {
  state.job = { ...snapshot, lines: [...snapshot.lines] };
  state.jobSeq++;
  renderJobbar();
  if (busy()) pollJob();
}

async function pollJob() {
  if (state.polling) return;
  state.polling = true;
  try {
    while (busy()) {
      await new Promise((r) => setTimeout(r, 1000));
      let snap;
      try {
        snap = await api(`/api/job?since=${state.job.lines.length}`);
      } catch {
        continue; // server briefly unreachable; keep waiting
      }
      if (!snap) {
        // The server answered but has no job: Atlas was restarted mid-run, which
        // kills the job. Say so instead of spinning forever.
        state.job = {
          ...state.job,
          status: "error",
          error: "Atlas was restarted while this was running, so it stopped partway. Please start it again.",
        };
        renderJobbar();
        onJobFinished(state.job);
        break;
      }
      state.job = { ...snap, lines: state.job.lines.concat(snap.lines) };
      renderJobbar();
      updateLiveLog();
      if (snap.status !== "running") onJobFinished(state.job);
    }
  } finally {
    state.polling = false;
  }
}

function onJobFinished(job) {
  if (job.status === "error") {
    toast("That didn't work. Open “See progress” for details.");
  } else if (job.kind === "ingest") {
    toast(job.graph === "demo" ? "The demo is up to date." : "Your knowledge graph is up to date.");
  } else if (job.kind === "ask") {
    state.lastAsk = { ...job.result, graph: job.graph };
    toast("Your answer is ready.");
  } else if (job.kind === "check") {
    toast("Setup check finished.");
  }
  route(); // re-render whatever page is open with fresh data
}

function renderJobbar() {
  const bar = document.getElementById("jobbar");
  if (!busy()) { bar.hidden = true; return; }
  bar.hidden = false;
  const where = state.job.graph === "demo" ? " (demo)" : "";
  document.getElementById("jobbar-label").textContent = state.job.label + where + "…";
  document.getElementById("jobbar-elapsed").textContent = formatElapsed(state.job.elapsed);
}

function formatElapsed(s) {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  return m ? `${m} min ${s % 60} s` : `${s} s`;
}

function updateLiveLog() {
  const log = document.getElementById("live-log");
  if (!log || !state.job) return;
  log.textContent = state.job.lines.join("\n") || "Starting…";
  log.scrollTop = log.scrollHeight;
}

function jobPanel(kinds) {
  const job = state.job;
  if (!job || !kinds.includes(job.kind) || job.graph !== state.graph) return "";
  if (job.status === "running") {
    return `<div class="card" id="job-card">
      <div class="row"><span class="spinner"></span><strong>${esc(job.label)}…</strong>
      <span class="muted small">This can take a few minutes. You can leave this page; it keeps going.</span></div>
      <pre class="log" id="live-log" style="margin-top:1rem">${esc(job.lines.join("\n") || "Starting…")}</pre>
    </div>`;
  }
  if (job.status === "error") {
    return `<div class="notice bad"><p><strong>That didn't work.</strong></p>
      <p style="white-space:pre-wrap">${esc(job.error)}</p>
      ${job.lines.length ? `<details style="margin-top:.6rem"><summary>Show details</summary><pre class="log">${esc(job.lines.join("\n"))}</pre></details>` : ""}
    </div>`;
  }
  return "";
}

// ---------------------------------------------------------------- router

const routes = [
  [/^#?\/?$/, viewHome, "home"],
  [/^#\/add$/, viewAdd, "add"],
  [/^#\/ask$/, viewAsk, "ask"],
  [/^#\/browse(?:\/(\w+))?$/, viewBrowse, "browse"],
  [/^#\/note\/(.+)$/, viewNote, "browse"],
  [/^#\/health$/, viewHealth, "health"],
  [/^#\/guide(?:\/(.+))?$/, viewGuide, "guide"],
  [/^#\/activity$/, viewActivity, ""],
];

async function route() {
  const hash = location.hash || "#/";
  for (const [re, view, tab] of routes) {
    const m = hash.match(re);
    if (!m) continue;
    document.querySelectorAll(".tabs a").forEach((a) =>
      a.classList.toggle("active", a.dataset.tab === tab));
    try {
      await view(...m.slice(1).map((x) => (x ? decodeURIComponent(x) : x)));
    } catch (e) {
      $main.innerHTML = `<div class="notice bad"><p>${esc(e.message)}</p></div>`;
    }
    return;
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", () => {
  if (window.Tour && Tour.redirect()) return; // the tour keeps people on its current page
  route();
  $main.focus();
  window.scrollTo(0, 0);
});

// ---------------------------------------------------------------- views

async function viewHome() {
  const s = await api("/api/status");
  const waiting = s.waiting.length;
  const folder = inDemo() ? "demo" : "universe";
  const emptyMine = !inDemo() && s.sources === 0 && waiting === 0;
  $main.innerHTML = `
    <h1>${inDemo() ? "The demo knowledge graph" : "Your knowledge graph"}</h1>
    <p class="lead">${inDemo()
      ? "A practice graph about how people learn and remember. Add things, ask things, experiment. Your own graph is never affected."
      : "Add articles and PDFs. Atlas reads them, sorts them into topics, and writes an up-to-date summary for each topic. Then you can ask it questions."}</p>

    ${setupNotice(s)}

    <div class="stats">
      <a class="stat" href="#/browse/sources"><div class="stat-num">${s.sources}</div><div class="stat-label">sources read</div></a>
      <a class="stat" href="#/browse/topics"><div class="stat-num">${s.topics}</div><div class="stat-label">topics written</div></a>
      <a class="stat" href="#/add"><div class="stat-num">${waiting}</div><div class="stat-label">waiting to be read</div></a>
    </div>

    ${jobPanel(["ingest"])}

    ${emptyMine ? `
      <div class="card">
        <h2>Your knowledge graph is empty</h2>
        <p class="muted">Add a few articles you care about and Atlas will start building it.
          ${s.demo_available ? "Want to practice first? The demo is a sandbox you can't break." : ""}</p>
        <div class="row">
          <a class="button primary big" href="#/add">Add my first source</a>
          ${s.demo_available ? `<button class="big" id="go-demo">Explore the demo</button>` : ""}
        </div>
      </div>` : ""}

    ${waiting && !busy() ? `
      <div class="card">
        <h2>${plural(waiting, "new source")} ready</h2>
        <p class="muted">Atlas will read ${waiting === 1 ? "it" : "them"} and fold what's new into the topics.</p>
        <button class="primary big" id="build" ${s.problems.length ? "disabled" : ""}>Update ${inDemo() ? "the demo" : "my knowledge graph"}</button>
      </div>` : ""}

    <div class="card">
      <h2>How it works</h2>
      <ol class="steps">
        <li><div><strong><a href="#/add">Add sources</a></strong>: upload files, paste a web link, or paste an article's text.</div></li>
        <li><div><strong>Update the knowledge graph</strong>: Atlas reads each new source and updates the topics it belongs to.</div></li>
        <li><div><strong><a href="#/ask">Ask questions</a></strong> in plain English and get answers that cite the sources.</div></li>
        <li><div><strong><a href="#/browse">Browse</a></strong> everything Atlas has written, or open the <code>${folder}</code> folder in <a href="https://obsidian.md" target="_blank" rel="noopener">Obsidian</a> to see it as a graph.</div></li>
      </ol>
    </div>
    <p class="small muted">This knowledge graph's folder: <code>${esc(s.vault)}</code></p>`;
  document.getElementById("build")?.addEventListener("click", () => startIngest());
  document.getElementById("go-demo")?.addEventListener("click", () => setGraph("demo"));
}

function setupNotice(s) {
  if (s.problems.length) {
    return `<div class="notice warn"><p><strong>One thing to set up first</strong></p>
      ${s.problems.map((p) => `<p>${linkify(esc(p))}</p>`).join("")}
      <p class="small muted">Already done it? <a href="#/health">Run the setup check</a>.</p></div>`;
  }
  return "";
}

function linkify(html) {
  return html.replace(/https?:\/\/[^\s<]+[^\s<.,)]/g, (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
}

async function startIngest(limit) {
  try {
    adoptJob(await api("/api/ingest", { method: "POST", body: { limit } }));
    route();
  } catch (e) { toast(e.message); }
}

async function viewAdd() {
  const s = await api("/api/status");
  $main.innerHTML = `
    <h1>Add sources</h1>
    <p class="lead">Anything you want Atlas to learn from: articles saved as text or Markdown, PDFs, links to web pages, or text you paste in.</p>

    ${setupNotice(s)}

    <div class="card" id="add-card">
      <h2 style="margin-bottom:.2rem">1. Choose how to add a source</h2>
      <p class="muted small" style="margin-top:0">Pick one of the three ways below.</p>
      <div class="choices" role="tablist" aria-label="How to add a source">
        ${ADD_MODES.map((m) => `
          <button class="choice ${m.key === state.addMode ? "selected" : ""}" role="tab"
                  aria-selected="${m.key === state.addMode}" data-mode="${m.key}">
            <span class="choice-icon" aria-hidden="true">${m.icon}</span>
            <span class="choice-title">${m.title}</span>
            <span class="choice-desc">${m.desc}</span>
          </button>`).join("")}
      </div>

      <div class="choice-panel" ${state.addMode === "files" ? "" : "hidden"} role="tabpanel">
        <label class="dropzone" id="drop">
          <strong>Drop files here</strong>
          <span class="muted">or click to choose them from your computer (.pdf, .md, .txt)</span>
          <input type="file" id="file" multiple accept=".pdf,.md,.txt" hidden>
        </label>
      </div>

      <div class="choice-panel" ${state.addMode === "link" ? "" : "hidden"} role="tabpanel">
        <form id="urlform">
          <label class="field-label" for="url">Web address of the article</label>
          <input type="url" id="url" placeholder="https://example.com/great-article" required>
          <p class="small muted">Atlas fetches the page's text when it reads it. Pages behind a login or paywall
            usually won't work. For those, use <strong>Paste text</strong> instead.</p>
          <button class="primary" type="submit">Add link</button>
        </form>
      </div>

      <div class="choice-panel" ${state.addMode === "paste" ? "" : "hidden"} role="tabpanel">
        <form id="pasteform">
          <label class="field-label" for="paste-title">Title <span class="muted small">(optional)</span></label>
          <input type="text" id="paste-title" placeholder="e.g. Why sleep matters for memory">
          <label class="field-label" for="paste-text" style="margin-top:.9rem">Article text</label>
          <textarea id="paste-text" class="paste" placeholder="Copy the article from wherever you're reading it, then paste it here (⌘V)." required></textarea>
          <div class="row" style="margin-top:.8rem">
            <button class="primary" type="submit">Add text</button>
            <span class="small muted" id="paste-count"></span>
          </div>
        </form>
      </div>
    </div>

    ${jobPanel(["ingest"])}

    <div class="card" id="waiting-card">
      <h2>2. Waiting to be read ${s.waiting.length ? `<span class="pill">${s.waiting.length}</span>` : ""}</h2>
      ${s.waiting.length ? `
        <ul class="list">${s.waiting.map((w) => `
          <li><span class="truncate" title="${esc(w.label)}">${esc(w.label)}</span>
            <button class="link" data-remove="${esc(w.path)}" ${busy() ? "disabled" : ""}>Remove</button></li>`).join("")}
        </ul>
        <div class="row" style="margin-top:1.2rem">
          <button class="primary big" id="build" ${busy() || s.problems.length ? "disabled" : ""}>Update ${inDemo() ? "the demo" : "my knowledge graph"}</button>
          <label class="muted small row" style="gap:.4rem">Only the next <input type="number" id="limit" min="1" placeholder="all"> sources</label>
        </div>
        <p class="small muted">Each source takes about half a minute. For a big pile, do a few at a time and check the results.</p>`
      : `<p class="empty">Nothing waiting yet. Add a source above.</p>`}
    </div>`;

  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    state.addMode = b.dataset.mode;
    viewAdd().then(() => {
      const focus = { link: "url", paste: "paste-text" }[state.addMode];
      if (focus) document.getElementById(focus).focus();
    });
  }));

  const pasteText = document.getElementById("paste-text");
  pasteText.addEventListener("input", () => {
    const words = pasteText.value.trim().split(/\s+/).filter(Boolean).length;
    document.getElementById("paste-count").textContent = words ? `${words.toLocaleString()} words` : "";
  });
  document.getElementById("pasteform").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/add-text", {
        method: "POST",
        body: { title: document.getElementById("paste-title").value, text: pasteText.value },
      });
      toast("Text added.");
      viewAdd();
    } catch (err) { toast(err.message); }
  });

  const drop = document.getElementById("drop");
  const fileInput = document.getElementById("file");
  fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

  document.getElementById("urlform").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/add-url", { method: "POST", body: { url: document.getElementById("url").value } });
      toast("Link added.");
      viewAdd();
    } catch (err) { toast(err.message); }
  });

  document.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/remove-waiting", { method: "POST", body: { path: b.dataset.remove } });
      viewAdd();
    } catch (err) { toast(err.message); }
  }));

  document.getElementById("build")?.addEventListener("click", () => {
    const n = parseInt(document.getElementById("limit").value, 10);
    startIngest(n > 0 ? n : null);
  });
}

const ADD_MODES = [
  { key: "files", icon: "📄", title: "Upload files", desc: "PDFs or text files on your computer" },
  { key: "link", icon: "🔗", title: "Web link", desc: "The address of an article online" },
  { key: "paste", icon: "📋", title: "Paste text", desc: "Copy an article and paste it in" },
];

async function uploadFiles(files) {
  let ok = 0;
  for (const f of files) {
    try {
      await api(`/api/upload?name=${encodeURIComponent(f.name)}`, { method: "POST", raw: await f.arrayBuffer() });
      ok++;
    } catch (e) { toast(`${f.name}: ${e.message}`); }
  }
  if (ok) toast(`Added ${plural(ok, "file")}.`);
  viewAdd();
}

async function viewAsk() {
  const s = await api("/api/status");
  const a = state.lastAsk && state.lastAsk.graph === state.graph ? state.lastAsk : null;
  $main.innerHTML = `
    <h1>Ask ${inDemo() ? "the demo" : "your knowledge graph"}</h1>
    <p class="lead">Answers come only from the sources in this knowledge graph. If they don't cover your question, Atlas says so instead of guessing.</p>
    ${setupNotice(s)}
    ${s.sources === 0 ? `<div class="notice warn"><p>This knowledge graph is empty, so there's nothing to answer from yet. <a href="#/add">Add some sources</a> first.</p></div>` : ""}
    <div class="card" id="ask-card">
      <form id="askform">
        <textarea id="question" placeholder="e.g. What are the main arguments for and against remote work?" required></textarea>
        <label class="check small muted" style="margin-top:.8rem">
          <input type="checkbox" id="fileback" checked>
          <span>If the answer turns up a genuinely new insight, save it into the matching topic so the knowledge graph gets smarter.</span>
        </label>
        <div class="row" style="margin-top:1rem">
          <button class="primary big" type="submit" ${busy() ? "disabled" : ""}>Ask</button>
        </div>
      </form>
      ${inDemo() ? `
        <p class="small muted" style="margin:1.2rem 0 .5rem">Try one of these with the demo:</p>
        <div class="row">${DEMO_QUESTIONS.map((q) => `<button class="chip" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}
    </div>
    ${jobPanel(["ask"])}
    ${a ? `
      <div class="card" id="answer-card">
        <p class="muted small" style="margin-top:0">You asked: <strong>${esc(a.question)}</strong></p>
        ${a.coverage === "insufficient" ? `<div class="notice warn"><p>These sources don't really cover this one yet. Adding material on it would help.</p></div>` : ""}
        <div class="prose">${a.html}</div>
        ${a.filed_back_path ? `<p class="notice good small">A new insight from this answer was saved into the knowledge graph.</p>` : ""}
      </div>` : ""}`;

  if (a) document.getElementById("question").value = a.question;
  document.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => {
    const box = document.getElementById("question");
    box.value = b.dataset.q;
    box.focus();
  }));
  document.getElementById("askform").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      state.lastAsk = null;
      adoptJob(await api("/api/ask", {
        method: "POST",
        body: { question: document.getElementById("question").value, file_back: document.getElementById("fileback").checked },
      }));
      viewAsk();
    } catch (err) { toast(err.message); }
  });
}

async function viewBrowse(section = "topics") {
  const data = await api("/api/notes");
  const sections = {
    topics: { label: "Topics", items: data.topics, folder: "concepts",
      empty: "No topics yet. They appear after Atlas reads the first sources.",
      extra: (t) => `<span class="pill">${plural(t.count, "source")}</span>` },
    sources: { label: "Sources", items: data.sources, folder: "library",
      empty: "No sources read yet.",
      extra: (t) => (t.date ? `<span class="pill">${esc(t.date)}</span>` : "") },
    history: { label: "Past questions", items: data.history, folder: "output",
      empty: "No questions asked yet.", extra: () => "" },
  };
  const cur = sections[section] || sections.topics;
  $main.innerHTML = `
    <h1>Browse${inDemo() ? " the demo" : ""}</h1>
    <p class="lead"><strong>Topics</strong> are the summaries Atlas keeps up to date. <strong>Sources</strong> are its notes on each thing that was added.
      ${data.topics.length ? `There's also a <a href="#/note/index/MOC">full index</a>.` : ""}</p>
    <div class="row" style="margin-bottom:1rem">
      ${Object.entries(sections).map(([k, v]) =>
        `<a class="button ${k === section ? "primary" : ""}" href="#/browse/${k}">${v.label} <span class="small">(${v.items.length})</span></a>`).join("")}
    </div>
    <div class="card" id="browse-card">
      ${cur.items.length ? `
        <input type="text" id="filter" placeholder="Filter ${cur.label.toLowerCase()}…" style="margin-bottom:.6rem">
        <ul class="list" id="items">${cur.items.map((t) => `
          <li data-text="${esc(t.title.toLowerCase())}"><a class="truncate" href="#/note/${cur.folder}/${encodeURIComponent(t.slug)}">${esc(t.title)}</a>${cur.extra(t)}</li>`).join("")}
        </ul>` : `<p class="empty">${cur.empty}</p>`}
    </div>`;
  document.getElementById("filter")?.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll("#items li").forEach((li) => (li.hidden = !li.dataset.text.includes(q)));
  });
}

async function viewNote(path) {
  const n = await api(`/api/note?path=${encodeURIComponent(path)}`);
  const back = { concepts: "topics", library: "sources", output: "history", index: "topics" }[n.folder];
  const kind = { concepts: "Topic", library: "Source", output: "Questions log", index: "Index" }[n.folder];
  const m = n.meta || {};
  const src = m.source ? (/^https?:\/\//.test(m.source)
    ? `<a href="${esc(m.source)}" target="_blank" rel="noopener">${esc(m.source)}</a>` : esc(m.source)) : "";
  $main.innerHTML = `
    <div class="crumbs"><a href="#/browse/${back}">← Back</a> · <span class="muted">${kind}</span></div>
    <h1>${esc(n.title)}</h1>
    ${n.folder === "library" ? `<div class="meta">
      ${src ? `<span>From: ${src}</span>` : ""}
      ${m.date_ingested ? `<span>Added ${esc(m.date_ingested)}</span>` : ""}
      ${m.topics?.length ? `<span>Topic: ${m.topics.map((t) => `<a href="#/note/concepts/${encodeURIComponent(t.slug)}">${esc(t.title)}</a>`).join(", ")}</span>` : ""}
      ${m.related?.length ? `<span>Also relates to: ${m.related.map((t) => `<a href="#/note/concepts/${encodeURIComponent(t.slug)}">${esc(t.title)}</a>`).join(", ")}</span>` : ""}
    </div>` : ""}
    <div class="card prose" id="note-card">${n.html}</div>`;
}

async function viewHealth() {
  const s = await api("/api/status");
  $main.innerHTML = `
    <h1>Health check</h1>
    <p class="lead">Make sure Atlas is set up correctly, and check this knowledge graph for broken links or loose ends.</p>
    ${setupNotice(s)}
    <div class="card" id="setup-card">
      <h2>Setup</h2>
      <p class="muted">Sends one tiny test message to the AI model Atlas uses, to confirm it's installed and signed in.</p>
      <button id="check" ${busy() ? "disabled" : ""}>Check my setup</button>
      <div id="check-result" style="margin-top:1rem">${checkResult()}</div>
      ${jobPanel(["check"])}
      ${!s.git && !inDemo() ? `<p class="small muted" style="margin-bottom:0">Tip: this folder isn't using Git, so Atlas can't keep an undo history of its changes. Developers can run <code>git init</code> here to turn that on.</p>` : ""}
    </div>
    <div class="card">
      <h2>Knowledge graph</h2>
      <p class="muted">Reads through everything and reports problems. Doesn't change anything.</p>
      <button id="lint">Check ${inDemo() ? "the demo" : "my knowledge graph"}</button>
      <div id="lint-result" style="margin-top:1rem"></div>
    </div>`;

  document.getElementById("check").addEventListener("click", async () => {
    try { adoptJob(await api("/api/check-setup", { method: "POST" })); viewHealth(); }
    catch (e) { toast(e.message); }
  });
  document.getElementById("lint").addEventListener("click", async () => {
    const out = document.getElementById("lint-result");
    out.innerHTML = `<span class="spinner"></span>`;
    try {
      const r = await api("/api/lint", { method: "POST" });
      out.innerHTML = r.total === 0
        ? `<div class="notice good"><p>Everything looks healthy.</p></div>`
        : `<div class="notice warn"><p><strong>${plural(r.total, "thing")} to look at</strong></p></div>` +
          Object.entries(r.checks).filter(([, v]) => v.length).map(([k, v]) => `
            <h3>${esc(LINT_LABELS[k] || k)} (${v.length})</h3>
            <ul class="small">${v.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`).join("");
    } catch (e) { out.innerHTML = `<div class="notice bad"><p>${esc(e.message)}</p></div>`; }
  });
}

const DEMO_QUESTIONS = [
  "What's the most effective way to study for an exam a month away?",
  "Why do study methods that feel easy often work worse?",
  "How does sleep affect learning?",
  "How can I make a daily review habit stick?",
  "What's the capital of France?",
];

const LINT_LABELS = {
  missing_frontmatter: "Notes missing basic details",
  broken_wikilinks: "Links that point nowhere",
  dangling_concept_refs: "Sources filed under a topic that doesn't exist",
  orphaned_concepts: "Topics with no sources",
  overgrown_concepts: "Topics that may be getting too big (consider splitting)",
};

function checkResult() {
  const j = state.job;
  if (!j || j.kind !== "check" || j.status !== "done") return "";
  return `<div class="notice good"><p><strong>All set.</strong> Atlas can talk to its AI model.</p></div>`;
}

async function viewGuide(name = "README.md") {
  const [d, s] = await Promise.all([api(`/api/doc?name=${encodeURIComponent(name)}`), api("/api/status")]);
  $main.innerHTML = `
    ${name !== "README.md" ? `<div class="crumbs"><a href="#/guide">← Back to the guide</a></div>` : ""}
    ${name === "README.md" && s.demo_available ? `
      <div class="card">
        <h2>Demo and tutorial</h2>
        <div class="row" style="align-items:flex-start;gap:1.5rem">
          <div style="flex:1;min-width:14rem">
            <button id="restart-tour">Restart the tutorial</button>
            <p class="small muted">Puts the demo back as new and walks you through Atlas again.</p>
          </div>
          <div style="flex:1;min-width:14rem">
            <button id="reset-demo">Reset the demo</button>
            <p class="small muted">Undoes everything done in the demo. Your own knowledge graph isn't touched.</p>
          </div>
        </div>
      </div>` : ""}
    <div class="card prose">${d.html}</div>`;

  document.getElementById("reset-demo")?.addEventListener("click", async () => {
    if (!confirm("Reset the demo? Anything you added or asked in the demo will be removed. Your own knowledge graph is not affected.")) return;
    try {
      await api("/api/reset-demo", { method: "POST" });
      if (state.lastAsk?.graph === "demo") state.lastAsk = null;
      toast("The demo is back to how it started.");
    } catch (e) { toast(e.message); }
  });
  document.getElementById("restart-tour")?.addEventListener("click", async () => {
    if (!confirm("Restart the tutorial? This also resets the demo. Your own knowledge graph is not affected.")) return;
    try {
      await api("/api/restart-tutorial", { method: "POST" });
      if (state.lastAsk?.graph === "demo") state.lastAsk = null;
      Tour.start(0);
    } catch (e) { toast(e.message); }
  });
}

async function viewActivity() {
  const j = state.job;
  if (!j) {
    $main.innerHTML = `<h1>Activity</h1><p class="empty">Nothing has run yet.</p>`;
    return;
  }
  const status = { running: "In progress", done: "Finished", error: "Didn't work" }[j.status];
  $main.innerHTML = `
    <h1>${esc(j.label)}${j.graph === "demo" ? " (demo)" : ""}</h1>
    <p class="lead">${status} · ${formatElapsed(j.elapsed)}</p>
    ${j.status === "error" ? `<div class="notice bad"><p style="white-space:pre-wrap">${esc(j.error)}</p></div>` : ""}
    <pre class="log" id="live-log">${esc(j.lines.join("\n") || "Starting…")}</pre>
    ${j.status === "done" && j.kind === "ask" ? `<p><a href="#/ask">See the answer →</a></p>` : ""}`;
}

// ---------------------------------------------------------------- boot

(async function boot() {
  const [snap, status] = await Promise.all([
    api("/api/job").catch(() => null),
    api("/api/status").catch(() => null),
  ]);
  if (snap) {
    state.job = snap;
    if (snap.kind === "ask" && snap.status === "done") state.lastAsk = { ...snap.result, graph: snap.graph };
    renderJobbar();
    if (busy()) pollJob();
  }
  if (status && !status.demo_available) document.getElementById("graph-switch").hidden = true;
  if (status?.first_time_user && status.demo_available) {
    state.graph = "demo";
    localStorage.setItem("atlas.graph", "demo");
  }
  renderGraphChrome();
  if (status?.first_time_user && status.demo_available) Tour.resume();
  else route();
  setInterval(() => { if (busy()) document.getElementById("jobbar-elapsed").textContent = formatElapsed(++state.job.elapsed); }, 1000);
})();
