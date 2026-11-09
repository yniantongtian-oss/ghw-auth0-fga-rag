const questionEl = document.querySelector("#question");
const askButton = document.querySelector("#ask");
const statusEl = document.querySelector("#status");
const answerCard = document.querySelector("#answer-card");
const answerEl = document.querySelector("#answer");
const citationsEl = document.querySelector("#citations");
const traceCard = document.querySelector("#trace-card");
const traceEl = document.querySelector("#trace");
const identityEl = document.querySelector("#identity");
const switcherEl = document.querySelector("#switcher");
const libraryEl = document.querySelector("#library");
const libraryCount = document.querySelector("#library-count");
const backendNote = document.querySelector("#backend-note");
const auth0Slot = document.querySelector("#auth0-slot");
const switcherCard = document.querySelector("#switcher-card");

const DEPT = {
  hr: "HR",
  engineering: "Engineering",
  finance: "Finance",
  executive: "Executive",
  unassigned: "Unassigned",
};

let config = { devSwitcher: false, auth0: false, backend: "" };
let currentId = "";

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

async function readJson(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (_err) {
    return { detail: text };
  }
}

function setStatus(text) {
  statusEl.textContent = text || "";
}

function renderIdentity(me) {
  clearNode(identityEl);
  if (!me) {
    identityEl.appendChild(el("p", "muted", "Choose a demo employee, or sign in with Auth0. Nobody is signed in yet, so the index stays closed."));
    return;
  }
  const user = me.user;
  const name = el("h2", "identity-name", user.name);
  const title = el("p", null, user.title);
  const chips = el("div", "chips");
  chips.appendChild(el("span", "chip", DEPT[user.department] || user.department));
  chips.appendChild(el("span", "chip", user.role));
  identityEl.append(name, title, chips);
  if (me.email) identityEl.appendChild(el("p", "fine", me.email));
}

function renderLibrary(me) {
  clearNode(libraryEl);
  if (!me) {
    libraryCount.textContent = "Sign in to see the documents list-objects returns for you.";
    return;
  }
  const docs = me.visible_documents || [];
  libraryCount.textContent = `${docs.length} of ${me.indexed_document_count} indexed documents.`;
  for (const doc of docs) {
    const item = el("li");
    item.appendChild(el("strong", null, doc.title));
    item.appendChild(el("span", null, doc.id));
    libraryEl.appendChild(item);
  }
  if (!docs.length) {
    libraryEl.appendChild(el("li", null, "No documents. FGA returned an empty list."));
  }
}

function renderSwitcher(users) {
  clearNode(switcherEl);
  if (!config.devSwitcher) {
    switcherCard.hidden = true;
    return;
  }
  switcherCard.hidden = false;
  for (const user of users) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-pressed", user.id === currentId ? "true" : "false");
    button.appendChild(el("span", "who", user.name));
    const dept = DEPT[user.department] || user.department;
    button.appendChild(el("span", "meta", `${user.title} · ${dept} · ${user.role}`));
    button.addEventListener("click", () => switchUser(user.id));
    switcherEl.appendChild(button);
  }
}

async function switchUser(userId) {
  setStatus("Switching identity…");
  const response = await fetch("/auth/dev/switch", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });
  if (!response.ok) {
    setStatus("Could not switch user.");
    return;
  }
  answerCard.hidden = true;
  traceCard.hidden = true;
  clearNode(answerEl);
  await refresh();
  setStatus(`Now answering as ${userId}. Previous answers were cleared.`);
}

async function refresh() {
  const meResponse = await fetch("/api/me");
  if (meResponse.status === 401) {
    currentId = "";
    renderIdentity(null);
    renderLibrary(null);
    renderSwitcher(config.devSwitcher ? await loadUsers() : []);
    return;
  }
  const me = await readJson(meResponse);
  currentId = me.user.id;
  renderIdentity(me);
  renderLibrary(me);
  if (config.devSwitcher) renderSwitcher(await loadUsers());
}

async function loadUsers() {
  const response = await fetch("/api/dev/users");
  if (!response.ok) return [];
  const body = await readJson(response);
  return body.users || [];
}

function renderAnswer(payload) {
  answerCard.hidden = false;
  traceCard.hidden = false;
  clearNode(answerEl);
  clearNode(citationsEl);
  clearNode(traceEl);
  answerEl.textContent = payload.answer || "";
  for (const citation of payload.citations || []) {
    const block = el("div", "cite");
    block.appendChild(el("h3", null, citation.title));
    block.appendChild(el("p", null, citation.excerpt));
    citationsEl.appendChild(block);
  }
  const trace = payload.trace || [];
  if (!trace.length) {
    traceEl.appendChild(el("p", "fine", "No indexed passages matched this question."));
    return;
  }
  for (const item of trace) {
    const quoted = item.allowed && item.quoted;
    const row = el("div", quoted ? "row allow" : item.allowed ? "row skip" : "row deny");
    const stamp = quoted ? "QUOTED" : item.allowed ? "NOT QUOTED" : "WITHHELD";
    row.appendChild(el("div", "stamp-word", stamp));
    const body = el("div");
    const label = item.allowed && item.title ? item.title : item.doc_id;
    body.appendChild(el("div", "doc", label));
    if (!item.allowed) {
      const bar = el("div", "redaction");
      bar.setAttribute("role", "img");
      bar.setAttribute("aria-label", "Passage withheld");
      body.appendChild(bar);
    } else {
      const note = item.quoted ? item.doc_id : `${item.doc_id} · left out of the answer`;
      body.appendChild(el("div", "fine", note));
    }
    row.appendChild(body);
    row.appendChild(el("div", "score", Number(item.score).toFixed(2)));
    traceEl.appendChild(row);
  }
}

async function ask(text) {
  const question = (text ?? questionEl.value).trim();
  if (!question) {
    setStatus("Write a question first.");
    return;
  }
  if (!currentId) {
    setStatus("Sign in or pick a demo employee first.");
    return;
  }
  questionEl.value = question;
  askButton.disabled = true;
  setStatus("Searching the index, then checking FGA…");
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const payload = await readJson(response);
    if (!response.ok) {
      setStatus(payload.detail || "The request failed.");
      return;
    }
    renderAnswer(payload);
    const withheld = payload.withheld_count || 0;
    const mode = payload.llm_used ? "Optional model" : "Offline extractor";
    setStatus(`${mode}. ${withheld} candidate document${withheld === 1 ? "" : "s"} withheld.`);
  } catch (_err) {
    setStatus("The desk could not be reached.");
  } finally {
    askButton.disabled = false;
  }
}

document.querySelector("#ask").addEventListener("click", () => ask());
questionEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ask();
  }
});
document.querySelector("#prompts").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  ask(button.dataset.q || "");
});

async function boot() {
  config = await readJson(await fetch("/api/config"));
  backendNote.textContent = `Authorization: ${config.backend}. ${config.llm ? "An optional model is configured." : "Answers are extracted offline."}`;
  clearNode(auth0Slot);
  if (config.auth0) {
    const link = el("a", "linkish", "Sign in with Auth0");
    link.href = "/login";
    auth0Slot.appendChild(link);
    auth0Slot.appendChild(document.createTextNode(" · "));
    const out = el("a", "linkish", "Sign out");
    out.href = "/logout";
    auth0Slot.appendChild(out);
  } else {
    auth0Slot.textContent = "Auth0 credentials are not set. The dev switcher is the login.";
  }
  await refresh();
}

boot();
