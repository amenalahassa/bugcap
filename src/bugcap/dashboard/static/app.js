"use strict";
(function () {
  var STATUSES = ["open", "in-progress", "resolved", "closed", "wontfix"];
  var token = null;
  var current = null;
  var $ = function (id) { return document.getElementById(id); };

  function el(tag, text, cls) {
    var node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }

  function getJSON(url) {
    return fetch(url).then(function (r) {
      return r.json().then(function (body) { return { ok: r.ok, status: r.status, body: body }; });
    });
  }

  function send(method, url, payload) {
    var go = function () {
      return fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json", "X-Bugcap-Token": token },
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, status: r.status, body: body }; });
      });
    };
    if (token) return go();
    return getJSON("/api/session").then(function (s) { token = s.body.token; return go(); });
  }

  function fillStatus(select, withAny) {
    STATUSES.forEach(function (s) { select.appendChild(el("option", s)).value = s; });
  }

  function query() {
    var p = new URLSearchParams();
    if ($("f-q").value) p.set("q", $("f-q").value);
    if ($("f-status").value) p.set("status", $("f-status").value);
    if ($("f-repo").value) p.set("repo", $("f-repo").value);
    $("f-tag").value.split(",").forEach(function (t) { t = t.trim(); if (t) p.append("tag", t); });
    return p.toString();
  }

  var timer = null;
  function refreshList() {
    getJSON("/api/reports?" + query()).then(function (res) {
      var ul = $("reports");
      ul.textContent = "";
      if (!res.ok) { $("total").textContent = res.body.message || "error"; return; }
      $("total").textContent = res.body.total + " reports";
      $("empty").hidden = res.body.items.length > 0;
      res.body.items.forEach(function (r) {
        var li = el("li");
        var title = el("span", "#" + r.id + " " + r.title, "t");
        li.appendChild(title);
        li.appendChild(el("span", r.status, "badge"));
        r.tags.forEach(function (t) { li.appendChild(el("span", t, "badge")); });
        if (r.media_count) li.appendChild(el("span", r.media_count + " media", "badge"));
        li.addEventListener("click", function () { openReport(r.id); });
        ul.appendChild(li);
      });
    });
  }

  function renderNotes(report) {
    var box = $("d-notes");
    box.textContent = "";
    var byId = {};
    report.media.forEach(function (m) { byId[m.id] = m; });
    if (!report.notes_segments.length) { box.appendChild(el("span", "(no notes)", "muted")); return; }
    report.notes_segments.forEach(function (seg) {
      if (seg.text !== undefined) { box.appendChild(document.createTextNode(seg.text)); return; }
      var m = byId[seg.ref.media_id];
      if (!m) { box.appendChild(el("span", seg.ref.token, "ref-missing")); return; }
      box.appendChild(mediaNode(report, m, seg.ref.token));
    });
  }

  function mediaNode(report, m, caption) {
    var fig = el("figure");
    if (m.kind === "video") {
      var v = document.createElement("video");
      v.controls = true; v.src = m.url; fig.appendChild(v);
    } else if (m.kind === "frames") {
      (report.frames[String(m.id)] || []).forEach(function (f) {
        var img = document.createElement("img");
        img.src = f.url; img.alt = "frame " + f.frame_no; fig.appendChild(img);
      });
    } else if (m.kind === "file") {
      var a = document.createElement("a");
      a.href = m.url; a.download = ""; a.textContent = "Download " + (m.label || ("file " + m.index));
      fig.appendChild(a);
    } else {
      var i = document.createElement("img");
      i.src = m.url; i.alt = m.label || ("image " + m.index); fig.appendChild(i);
    }
    var letters = {image: "i", video: "v", animated: "g", frames: "f", file: "d"};
    var label = caption || ("@" + (letters[m.kind] || "i") + m.index);
    if (m.label) label += " (" + m.label + ")";
    fig.appendChild(el("figcaption", label + " · " + m.kind + " · " + Math.round(m.size_bytes / 1024) + " KB"));
    return fig;
  }

  function renderDetail(report) {
    current = report;
    $("d-title").textContent = "#" + report.id + " " + report.title;
    $("d-meta").textContent = [report.repo, report.created_at].filter(Boolean).join(" · ");
    $("d-status").value = report.status;
    var tags = $("d-tags");
    tags.textContent = "";
    report.tags.forEach(function (t) {
      var b = el("span", t + " ×", "badge");
      b.title = "Remove tag";
      b.addEventListener("click", function () { changeTags({ remove: [t] }); });
      tags.appendChild(b);
    });
    renderNotes(report);
    $("notes-edit").value = report.notes_raw;
    $("notes-msg").textContent = "";
    var media = $("d-media");
    media.textContent = "";
    report.media.forEach(function (m) { media.appendChild(mediaNode(report, m)); });
    var refs = Object.keys(report.synced_refs || {}).map(function (k) { return k + ": " + report.synced_refs[k]; });
    var sync = $("d-sync");
    sync.textContent = "";
    (report.links || []).forEach(function (l) {
      var a = el("a", l.label);
      a.href = l.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      sync.appendChild(a);
      sync.appendChild(document.createTextNode(" · "));
    });
    sync.appendChild(document.createTextNode(refs.join(" · ")));
  }

  function openReport(id) {
    getJSON("/api/reports/" + id).then(function (res) {
      if (!res.ok) return;
      renderDetail(res.body);
      $("list-view").hidden = true;
      $("detail-view").hidden = false;
      location.hash = "#" + id;
    });
  }

  function changeTags(payload) {
    send("POST", "/api/reports/" + current.id + "/tags", payload).then(function () { openReport(current.id); });
  }

  function init() {
    fillStatus($("d-status"));
    var f = $("f-status");
    STATUSES.forEach(function (s) { var o = el("option", s); o.value = s; f.appendChild(o); });
    ["f-q", "f-status", "f-tag", "f-repo"].forEach(function (id) {
      $(id).addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(refreshList, 150); });
    });
    $("filters").addEventListener("submit", function (e) { e.preventDefault(); refreshList(); });
    $("back").addEventListener("click", function () {
      $("detail-view").hidden = true; $("list-view").hidden = false; location.hash = ""; refreshList();
    });
    $("d-status").addEventListener("change", function () {
      send("POST", "/api/reports/" + current.id + "/status", { status: $("d-status").value });
    });
    $("tag-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var v = $("tag-input").value.trim();
      if (v) { $("tag-input").value = ""; changeTags({ add: [v] }); }
    });
    $("notes-save").addEventListener("click", function () {
      send("PUT", "/api/reports/" + current.id + "/notes", { notes: $("notes-edit").value }).then(function (res) {
        if (res.ok) { renderDetail(res.body); return; }
        var b = res.body;
        $("notes-msg").textContent = b.message + (b.valid ? " (valid: " + b.valid.join(", ") + ")" : "");
      });
    });
    refreshList();
    var id = parseInt(location.hash.slice(1), 10);
    if (id) openReport(id);
  }
  init();
})();
