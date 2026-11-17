/* global apigClientFactory, apiGateway, APP_CONFIG */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const cfg = window.APP_CONFIG;

  // ---------------------------------------------------------------- SDK setup
  if (typeof apigClientFactory === "undefined") {
    showStatus($("search-status"), "API SDK not found. Unzip the generated SDK into the sdk/ folder.", "error");
    return;
  }

  // The generated SDK deep copies the request body with obj.constructor(), which throws for
  // File/Blob objects ("Failed to construct 'File'"). Pass binary bodies through untouched.
  const originalCopy = apiGateway.core.utils.copy;
  apiGateway.core.utils.copy = function (obj) {
    if (obj instanceof Blob || obj instanceof ArrayBuffer || ArrayBuffer.isView(obj)) return obj;
    return originalCopy(obj);
  };

  const apigClient = apigClientFactory.newClient({ apiKey: cfg.apiKey });

  // ---------------------------------------------------------------- helpers
  function showStatus(el, msg, kind) {
    el.textContent = msg;
    el.className = "status " + (kind || "");
  }

  function describeError(err) {
    const res = err && err.response;
    if (!res) return "Network error (check CORS settings and that the API is deployed).";
    const msg = (res.data && (res.data.message || res.data.Message)) || "";
    if (res.status === 403) return "Forbidden (403): check the API key in config.js and the usage plan. " + msg;
    if (res.status === 413) return "File too large for API Gateway (10 MB max).";
    if (res.status === 429) return "Too many requests, slow down and retry.";
    return `Request failed (${res.status}). ${msg}`;
  }

  // Header values must be printable ASCII; commas separate labels.
  function parseLabels(text) {
    const seen = new Set();
    return (text || "")
      .split(",")
      .map((l) => l.replace(/[^\x20-\x7E]/g, "").replace(/\s+/g, " ").trim().slice(0, cfg.maxLabelLength))
      .filter((l) => {
        const k = l.toLowerCase();
        if (!l || seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .slice(0, cfg.maxLabels);
  }

  // Safe, unique S3 key: avoids overwriting files with the same name and odd URL characters.
  function makeObjectKey(file) {
    const ext = file.type === "image/png" ? ".png" : ".jpg";
    const base = file.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 60) || "photo";
    return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}_${base}${ext}`;
  }

  // ---------------------------------------------------------------- search
  function renderResults(results) {
    const grid = $("results");
    grid.innerHTML = "";
    results.forEach((photo) => {
      const fig = document.createElement("figure");
      const img = document.createElement("img");
      img.src = photo.url;
      img.loading = "lazy";
      img.alt = (photo.labels || []).join(", ");
      img.onerror = () => fig.classList.add("broken");
      const cap = document.createElement("figcaption");
      (photo.labels || []).slice(0, 12).forEach((label) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = label;
        chip.onclick = () => runSearch(label);
        cap.appendChild(chip);
      });
      fig.append(img, cap);
      grid.appendChild(fig);
    });
  }

  let searchSeq = 0;
  async function runSearch(query) {
    const q = (query || "").trim();
    const status = $("search-status");
    $("search-input").value = q;
    if (!q) {
      showStatus(status, "Type something to search for.", "error");
      return;
    }
    const seq = ++searchSeq; // ignore responses from older searches
    showStatus(status, "Searching…", "busy");
    $("search-btn").disabled = true;
    try {
      const res = await apigClient.searchGet({ q: q }, {}, {});
      if (seq !== searchSeq) return;
      const data = typeof res.data === "string" ? JSON.parse(res.data) : res.data;
      const results = (data && data.results) || [];
      renderResults(results);
      showStatus(status, results.length ? `${results.length} photo(s) found for "${q}".` : `No photos found for "${q}".`, results.length ? "ok" : "");
    } catch (err) {
      if (seq !== searchSeq) return;
      console.error(err);
      renderResults([]);
      showStatus(status, describeError(err), "error");
    } finally {
      $("search-btn").disabled = false;
    }
  }

  $("search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    runSearch($("search-input").value);
  });

  // ---------------------------------------------------------------- upload
  $("labels-input").addEventListener("input", () => {
    const chips = $("label-chips");
    chips.innerHTML = "";
    parseLabels($("labels-input").value).forEach((l) => {
      const span = document.createElement("span");
      span.className = "chip static";
      span.textContent = l;
      chips.appendChild(span);
    });
  });

  $("file-input").addEventListener("change", () => {
    const file = $("file-input").files[0];
    const preview = $("preview");
    if (file && cfg.allowedTypes.includes(file.type)) {
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
    } else {
      preview.hidden = true;
    }
  });

  $("upload-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = $("upload-status");
    const file = $("file-input").files[0];

    if (!file) return showStatus(status, "Choose a photo first.", "error");
    if (!cfg.allowedTypes.includes(file.type)) return showStatus(status, "Only JPEG and PNG images are supported.", "error");
    if (file.size === 0) return showStatus(status, "That file is empty.", "error");
    if (file.size > cfg.maxUploadBytes) return showStatus(status, "File is larger than 10 MB.", "error");

    const labels = parseLabels($("labels-input").value);
    const key = makeObjectKey(file);
    // The generated SDK marks every declared header as required, so the labels header is always
    // passed; an empty value means "no custom labels" and LF1 ignores it.
    const params = {
      object: key,
      "Content-Type": file.type,
      "x-amz-meta-customLabels": labels.join(", "), // e.g. "Sam, Sally"
    };
    // The SDK drops any body with no enumerable keys (Object.keys(file) is [] for a File),
    // which would upload an empty object. Give the File one own property so it is kept.
    file.__binaryBody = true;

    $("upload-btn").disabled = true;
    showStatus(status, "Uploading…", "busy");
    try {
      // headers go in params (declared in Method Request) and additionalParams (fallback),
      // so they are sent even if the SDK was generated before the headers were declared
      const headers = Object.assign({}, params);
      delete headers.object;
      await apigClient.photosObjectPut(params, file, { headers: headers });
      showStatus(status, `Uploaded ${file.name}${labels.length ? " with labels: " + labels.join(", ") : ""}. It will be searchable in a few seconds.`, "ok");
      $("upload-form").reset();
      $("label-chips").innerHTML = "";
      $("preview").hidden = true;
      if (labels.length) setTimeout(() => runSearch(labels[0]), 5000); // show it once indexed
    } catch (err) {
      console.error(err);
      showStatus(status, describeError(err), "error");
    } finally {
      $("upload-btn").disabled = false;
    }
  });

  // ---------------------------------------------------------------- optional: voice search
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) {
    const btn = $("voice-btn");
    btn.hidden = false;
    btn.addEventListener("click", () => {
      const rec = new SR();
      rec.lang = "en-US";
      rec.interimResults = false;
      showStatus($("search-status"), "Listening…", "busy");
      rec.onresult = (ev) => runSearch(ev.results[0][0].transcript);
      rec.onerror = (ev) => showStatus($("search-status"), "Voice input failed: " + ev.error, "error");
      rec.start();
    });
  }
})();
