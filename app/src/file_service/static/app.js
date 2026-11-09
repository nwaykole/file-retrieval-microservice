// Login form + file list. Talks only to this service's JSON API (same origin, session cookie).
// All server data is written with textContent, never as HTML, so a filename can't inject markup.
"use strict";

const $ = (id) => document.getElementById(id);

function show(view) {
  $("login-view").hidden = view !== "login";
  $("files-view").hidden = view !== "files";
  if (view === "login") $("username").focus();
}

function formatSize(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

function cell(text, className) {
  const td = document.createElement("td");
  td.textContent = text;
  if (className) td.className = className;
  return td;
}

function fileRow(file) {
  const link = document.createElement("a");
  link.href = `/v1/files/${encodeURIComponent(file.file_id)}/content`;
  link.textContent = "Download";
  const action = document.createElement("td");
  action.className = "action";
  action.append(link);

  const row = document.createElement("tr");
  row.append(cell(file.filename, "name"), cell(file.content_type), cell(formatSize(file.size_bytes), "num"), action);
  return row;
}

async function loadFiles() {
  $("files-error").textContent = "";
  let response;
  try {
    response = await fetch("/v1/files?limit=200", { credentials: "same-origin" });
  } catch {
    show("login");
    $("login-error").textContent = "Could not reach the service. Try again.";
    return;
  }
  if (response.status === 401) {
    show("login");
    return;
  }
  show("files");
  if (!response.ok) {
    $("files-error").textContent = `Could not load your files (HTTP ${response.status}). Try again shortly.`;
    return;
  }
  const files = await response.json();
  $("files").tBodies[0].replaceChildren(...files.map(fileRow));
  $("files").hidden = files.length === 0;
  $("empty").hidden = files.length !== 0;
}

function loginErrorMessage(status) {
  if (status === 401) return "Wrong username or password.";
  if (status === 422) {
    return "Check your details: username 3-128 characters (letters, digits, . _ @ + -), password at least 12.";
  }
  return `Login failed (HTTP ${status}). Try again shortly.`;
}

async function login(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const data = new FormData(form);
  $("login-error").textContent = "";
  button.disabled = true;
  try {
    const response = await fetch("/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
    });
    if (response.ok) {
      form.reset();
      await loadFiles();
    } else {
      $("login-error").textContent = loginErrorMessage(response.status);
    }
  } catch {
    $("login-error").textContent = "Could not reach the service. Try again.";
  } finally {
    button.disabled = false;
  }
}

async function logout() {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  } finally {
    $("files").tBodies[0].replaceChildren();
    show("login");
  }
}

$("login-form").addEventListener("submit", login);
$("logout").addEventListener("click", logout);
loadFiles();   // already signed in? go straight to the file list
