// First-run tutorial: a step-by-step spotlight tour of Atlas, run in the demo graph.
//
// How it works:
// - The server keeps `first_time_user` (atlas/state/ui.json). app.js calls
//   Tour.resume() on load while it's true; skipping or finishing sets it false.
// - Each step names the page it lives on, the element to spotlight, and either a
//   "Next" button or a condition that advances it once the person actually does
//   the thing (a job starts or finishes, the page changes, the graph switches).
// - The spotlight is a giant box-shadow on the target element, so everything else
//   dims without an extra overlay sitting on top of it. Steps without a target
//   (or whose target hasn't rendered yet) dim the whole page and center the card.
// - Views re-render by replacing innerHTML, so a MutationObserver re-applies the
//   spotlight whenever the page changes underneath us.
// - The current step is kept in localStorage so a page reload resumes the tour.
"use strict";

(function () {
  const STEP_KEY = "atlas.tourStep";
  const RESULT_KEY = "atlas.tourIngest";

  const card = document.createElement("div");
  card.id = "tour-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-live", "polite");
  card.hidden = true;

  const dim = document.createElement("div");
  dim.id = "tour-dim";
  dim.hidden = true;

  const skip = document.createElement("button");
  skip.id = "tour-skip";
  skip.textContent = "Skip tutorial";
  skip.hidden = true;

  document.body.append(dim, card, skip);

  const anyNote = /^#\/note\//;

  function ingestResult() {
    try { return JSON.parse(localStorage.getItem(RESULT_KEY)) || null; } catch { return null; }
  }

  function changedTopic() {
    const r = ingestResult();
    if (!r) return null;
    if (r.updated_topics?.length) return { ...r.updated_topics[0], how: "updated" };
    if (r.created_topics?.length) return { ...r.created_topics[0], how: "created" };
    return null;
  }

  function jobSince(seq, kind) {
    const j = state.job;
    return j && state.jobSeq > seq && j.kind === kind && j.graph === "demo" ? j : null;
  }

  // ------------------------------------------------------------------ steps

  const STEPS = [
    {
      route: "#/",
      title: "Welcome to Atlas 👋",
      body: () => `
        <p>Atlas reads articles for you, sorts what they say into topics, and keeps a summary of each topic
          up to date. Then you can ask it questions and get answers that point back to the articles.</p>
        <p>You have <strong>two knowledge graphs</strong>: a <strong>demo</strong> to practice on, and
          <strong>your own</strong>. This tour uses the demo and takes about 5 minutes.</p>`,
      buttons: [["Start the tour", "next", true]],
    },
    {
      route: "#/",
      target: "#graph-switch",
      title: "Two knowledge graphs",
      body: () => `
        <p>You're in the <strong>Demo</strong> right now. Your own knowledge graph is one click away,
          and stays completely separate.</p>
        <p>Whatever you do in Atlas applies to the graph selected here.</p>`,
      buttons: [["Next", "next", true]],
    },
    {
      route: "#/",
      target: ".stats",
      title: "What's in the demo",
      body: () => `
        <p>The demo is about <strong>how people learn and remember</strong>. Atlas has already read
          7 short articles and written a topic page for each subject.</p>
        <p>3 more articles are <strong>waiting to be read</strong>. You'll have Atlas read them in a moment.</p>`,
      buttons: [["Next", "next", true]],
    },
    {
      route: "#/health",
      target: "#setup-card",
      title: "Check your setup",
      onEnter(t) { t.seq = state.jobSeq; },
      body: (t) => t.variant === "failed" ? `
        <p><strong>Atlas can't reach its AI model yet.</strong></p>
        <p>${esc(state.job?.error || "")}</p>
        <p>Once that's fixed, click <strong>Check my setup</strong> again.</p>` : `
        <p>Atlas uses <strong>Claude Code</strong> to read and write. Let's make sure it's installed and signed in.</p>
        <p>Click <strong>Check my setup</strong>. It takes a few seconds.</p>`,
      check(t) {
        const j = jobSince(t.seq, "check");
        if (!j || j.status === "running") return;
        if (j.status === "done") return "next";
        t.seq = state.jobSeq; // let them retry
        return "failed";
      },
    },
    {
      route: "#/add",
      target: "#waiting-card",
      title: "Read the waiting articles",
      onEnter(t) { t.seq = state.jobSeq; },
      body: () => `
        <p>Sources can be added three ways (above): upload a file, give a web link, or paste text.
          The demo already has 3 articles waiting.</p>
        <p>Click <strong>Update the demo</strong> to have Atlas read them.</p>`,
      check(t) { if (jobSince(t.seq, "ingest")) return "next"; },
    },
    {
      route: "#/add",
      target: "#job-card",
      title: "Atlas is reading",
      body: (t) => t.variant === "failed" ? `
        <p><strong>That didn't finish.</strong> ${esc(state.job?.error || "")}</p>` : `
        <p>For each article, Atlas writes a summary, decides which topic it belongs to, then updates that
          topic's page. This usually takes 1 to 2 minutes.</p>
        <p>In the log, <strong>creating topic</strong> means a new topic page, and <strong>updating topic</strong>
          means an existing topic just absorbed what the new article adds.</p>`,
      buttons: (t) => t.variant === "failed"
        ? [["Try again", "retry", true], ["Skip this step", "next"]]
        : [],
      check(t) {
        const j = state.job;
        if (!j || j.kind !== "ingest") return "back";
        if (j.status === "done") {
          localStorage.setItem(RESULT_KEY, JSON.stringify(j.result || {}));
          return "next";
        }
        if (j.status === "error") return "failed";
      },
      actions: {
        retry(t) { t.variant = null; startIngest(); },
      },
    },
    {
      route: "#/browse/topics",
      allow: [anyNote],
      target: () => {
        const c = changedTopic();
        const link = c && `#items a[href="#/note/concepts/${encodeURIComponent(c.slug)}"]`;
        return link && document.querySelector(link) ? link : "#browse-card";
      },
      title: "See what changed",
      body: () => {
        const c = changedTopic();
        return c ? `
          <p><strong>${esc(c.title)}</strong> was just ${c.how} from the new articles.</p>
          <p>Click it to open the topic page.</p>` : `
          <p>These are the demo's topics. Click any one to open it.</p>`;
      },
      check() { if (/^#\/note\/concepts\//.test(location.hash)) return "next"; },
    },
    {
      route: anyNote,
      target: "#note-card",
      title: "A topic page",
      body: () => `
        <p>Each topic page gathers what every article says about one subject, starting with a plain-language
          definition.</p>
        <p>The links point back to the articles each point came from, so you can always check a claim.</p>`,
      buttons: [["Next", "next", true]],
    },
    {
      route: "#/ask",
      target: "#ask-card",
      title: "Ask a question",
      onEnter(t) { t.seq = state.jobSeq; },
      body: (t) => t.variant === "failed" ? `
        <p><strong>That question didn't go through.</strong> ${esc(state.job?.error || "")}</p>
        <p>Click <strong>Ask</strong> to try again.</p>` : `
        <p>Pick one of the suggested questions below (or type your own), then click <strong>Ask</strong>.</p>
        <p>It takes about half a minute.</p>`,
      check(t) {
        const j = jobSince(t.seq, "ask");
        if (!j || j.status === "running") return;
        if (j.status === "done") return "next";
        t.seq = state.jobSeq;
        return "failed";
      },
    },
    {
      route: "#/ask",
      target: "#answer-card",
      title: "Your answer",
      body: () => `
        <p>Answers only use what's in the knowledge graph, and link to the topics and articles they came from.</p>
        <p>Try asking something it doesn't cover, like <em>"What's the capital of France?"</em>.
          Atlas will say it doesn't know instead of guessing.</p>`,
      buttons: [["Next", "next", true]],
    },
    {
      route: "#/",
      title: "See it as a graph in Obsidian (optional)",
      onEnter(t) { api("/api/status").then((s) => { t.vault = s.vault; render(); }); },
      body: (t) => `
        <p><a href="https://obsidian.md" target="_blank" rel="noopener">Obsidian</a> is a free notes app that
          shows your knowledge graph as a web of connected notes.</p>
        <ol>
          <li>Install and open Obsidian.</li>
          <li>Choose <strong>Open folder as vault</strong> and pick the demo folder:</li>
        </ol>
        <p class="tour-path"><code>${esc(t.vault || "…")}</code>
          <button class="chip" data-tour-action="copy">Copy</button></p>
        <p class="small muted">Then click the graph icon in Obsidian's left sidebar. No Obsidian? Skip this.
          Everything is also under <strong>Browse</strong>.</p>`,
      buttons: [["Next", "next", true]],
      actions: {
        async copy(t) {
          try { await navigator.clipboard.writeText(t.vault || ""); toast("Folder path copied."); }
          catch { toast("Couldn't copy. Select the path and copy it by hand."); }
        },
      },
    },
    {
      route: "#/",
      target: '#graph-switch [data-graph="mine"]',
      title: "Now make it yours",
      body: () => `
        <p>That's the tour! Click <strong>My knowledge graph</strong> to start building your own.</p>
        <p>The demo stays here whenever you want to practice. <strong>Reset the demo</strong> on the
          Guide page puts it back as new.</p>`,
      check() { if (state.graph === "mine") return "finish"; },
    },
  ];

  // ------------------------------------------------------------------ engine

  const T = { active: false, i: 0, variant: null, seq: 0, vault: null };
  let lastTarget = null;
  let renderedKey = null;

  function step() { return STEPS[T.i]; }

  function routeMatches(s, hash) {
    const pats = [s.route, ...(s.allow || [])];
    return pats.some((p) => (p instanceof RegExp ? p.test(hash) : hash === p || (p === "#/" && hash === "")));
  }

  function homeRoute(s) {
    return s.route instanceof RegExp ? null : s.route;
  }

  function go(i) {
    T.i = Math.max(0, Math.min(i, STEPS.length - 1));
    T.variant = null;
    renderedKey = null;
    localStorage.setItem(STEP_KEY, String(T.i));
    const s = step();
    if (state.graph !== "demo") { state.graph = "demo"; localStorage.setItem("atlas.graph", "demo"); renderGraphChrome(); }
    const target = homeRoute(s);
    if (!routeMatches(s, location.hash || "#/") && !target) return go(T.i - 1); // e.g. reloaded mid-step
    s.onEnter?.(T);
    if (!routeMatches(s, location.hash || "#/") && target) {
      location.hash = target; // hashchange -> route()
    } else {
      route();
    }
    render();
    setTimeout(scrollToTarget, 350);
  }

  function targetEl() {
    const s = step();
    const sel = typeof s.target === "function" ? s.target() : s.target;
    return sel ? document.querySelector(sel) : null;
  }

  function scrollToTarget() {
    const el = targetEl();
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function render() {
    if (!T.active) return;
    const s = step();
    const key = `${T.i}:${T.variant}:${T.vault}`;
    if (key !== renderedKey) {
      renderedKey = key;
      const buttons = typeof s.buttons === "function" ? s.buttons(T) : s.buttons || [];
      card.innerHTML = `
        <div class="tour-step">Step ${T.i + 1} of ${STEPS.length}</div>
        <h3>${s.title}</h3>
        <div class="tour-body">${s.body(T)}</div>
        <div class="tour-buttons">
          ${T.i > 0 && !s.check ? `<button data-tour-action="back" class="link">Back</button>` : ""}
          ${buttons.map(([label, action, primary]) =>
            `<button data-tour-action="${action}" class="${primary ? "primary" : ""}">${label}</button>`).join("")}
        </div>`;
    }
    place();
  }

  function place() {
    const el = targetEl();
    if (el !== lastTarget) {
      lastTarget?.classList.remove("tour-target");
      lastTarget = el;
      el?.classList.add("tour-target");
    }
    dim.hidden = !!el;
    card.classList.toggle("centered", !el);
    if (!el) { card.style.top = card.style.left = ""; return; }
    const r = el.getBoundingClientRect();
    const cw = card.offsetWidth, ch = card.offsetHeight, gap = 14, pad = 12;
    let top = r.bottom + gap;
    if (top + ch > window.innerHeight - pad) top = r.top - ch - gap;          // no room below: go above
    if (top < pad) top = Math.min(window.innerHeight - ch - pad, Math.max(pad, r.top + pad)); // tall target: overlap
    let left = Math.min(Math.max(pad, r.left), window.innerWidth - cw - pad);
    card.style.top = `${Math.max(pad, top)}px`;
    card.style.left = `${Math.max(pad, left)}px`;
  }

  function tick() {
    if (!T.active) return;
    const s = step();
    const outcome = s.check?.(T);
    if (outcome === "next") return go(T.i + 1);
    if (outcome === "back") return go(T.i - 1);
    if (outcome === "finish") return finish();
    if (outcome && outcome !== T.variant) { T.variant = outcome; renderedKey = null; }
    render();
  }

  async function setFlag(value) {
    try { await api("/api/tutorial", { method: "POST", body: { first_time_user: value } }); } catch {}
  }

  function stop() {
    T.active = false;
    card.hidden = dim.hidden = skip.hidden = true;
    lastTarget?.classList.remove("tour-target");
    lastTarget = null;
    document.body.classList.remove("touring");
    localStorage.removeItem(STEP_KEY);
    localStorage.removeItem(RESULT_KEY);
  }

  async function finish() {
    stop();
    await setFlag(false);
    toast("You're all set. Add your first source to start your own knowledge graph.");
    route();
  }

  card.addEventListener("click", (e) => {
    const action = e.target.closest("[data-tour-action]")?.dataset.tourAction;
    if (!action) return;
    if (action === "next") return go(T.i + 1);
    if (action === "back") return go(T.i - 1);
    step().actions?.[action]?.(T);
    tick();
  });

  skip.addEventListener("click", async () => {
    stop();
    await setFlag(false);
    toast("Tutorial skipped. You can restart it any time from the Guide page.");
    route();
  });

  new MutationObserver(() => requestAnimationFrame(() => T.active && place()))
    .observe(document.getElementById("main"), { childList: true, subtree: true });
  window.addEventListener("resize", () => T.active && place());
  window.addEventListener("scroll", () => T.active && place(), { passive: true });
  setInterval(tick, 500);

  window.Tour = {
    start(i = 0) {
      localStorage.removeItem(RESULT_KEY);
      T.active = true;
      card.hidden = skip.hidden = false;
      document.body.classList.add("touring");
      go(i);
    },
    resume() {
      const saved = parseInt(localStorage.getItem(STEP_KEY), 10);
      T.active = true;
      card.hidden = skip.hidden = false;
      document.body.classList.add("touring");
      go(Number.isFinite(saved) ? saved : 0);
    },
    // Keeps the person on the step's page; returns true if it redirected.
    redirect() {
      if (!T.active) return false;
      const s = step();
      if (routeMatches(s, location.hash || "#/")) return false;
      const target = homeRoute(s);
      if (!target) return false;
      location.hash = target;
      return true;
    },
    // During the tour, only the final step may leave the demo.
    allowGraph(graph) {
      if (!T.active || graph === "demo" || T.i === STEPS.length - 1) return true;
      toast("Finish or skip the tutorial first. It runs in the demo.");
      return false;
    },
  };
})();
