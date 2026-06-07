/* Akıllı Yol Güvenliği — Web Dashboard istemcisi
 * Kamera (getUserMedia) -> JPEG kare -> WS /ws/ingest -> FrameResult -> overlay.
 * Mac dahili kamera ve iPhone (Safari) kamerası ile çalışır.
 */
const API = location.origin.replace(/\/$/, "");
const WS = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/ingest";

const els = id => document.getElementById(id);
const video = els("video"), overlay = els("overlay"), octx = overlay.getContext("2d");

let stream = null, ws = null, sending = false, facing = "environment";
let frameCount = 0, lastFpsT = performance.now();
const SEND_FPS = 7;                       // ön yüz throttle (backend QoD döngüsüne uygun)
const captureCanvas = document.createElement("canvas");

/* ── Sessiz SIM doğrulama ──────────────────────────────────────────── */
els("loginBtn").onclick = async () => {
  const device_token = els("deviceToken").value.trim();
  const phone_number = els("phoneNumber").value.trim();
  const st = els("authState");
  st.textContent = "Şebeke üzerinden doğrulanıyor…"; st.className = "auth-state";
  try {
    const r = await fetch(`${API}/camara/number-verification:verify`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_token, phone_number })
    });
    const data = await r.json();
    if (data.devicePhoneNumberVerified) {
      st.textContent = "✓ Doğrulandı — giriş yapılıyor"; st.className = "auth-state ok";
      sessionStorage.setItem("authToken", data.token || "");
      setTimeout(() => els("loginMask").style.display = "none", 500);
    } else {
      st.textContent = "✗ SIM ↔ numara eşleşmedi"; st.className = "auth-state err";
    }
  } catch (e) {
    st.textContent = "Bağlantı hatası: " + e.message; st.className = "auth-state err";
  }
};

/* ── Kamera ──────────────────────────────────────────────────────────── */
async function listCameras() {
  try {
    const devs = await navigator.mediaDevices.enumerateDevices();
    const sel = els("cameraSelect"); sel.innerHTML = "";
    devs.filter(d => d.kind === "videoinput").forEach((d, i) => {
      const o = document.createElement("option");
      o.value = d.deviceId; o.textContent = d.label || `Kamera ${i + 1}`;
      sel.appendChild(o);
    });
  } catch (e) { console.warn(e); }
}

async function startCamera() {
  const deviceId = els("cameraSelect").value;
  const constraints = {
    video: deviceId ? { deviceId: { exact: deviceId } }
                    : { facingMode: facing },
    audio: false
  };
  stream = await navigator.mediaDevices.getUserMedia(constraints);
  video.srcObject = stream;
  await video.play();
  overlay.width = video.videoWidth || 1280;
  overlay.height = video.videoHeight || 720;
  els("startBtn").disabled = true; els("stopBtn").disabled = false;
  await listCameras();
  connectWS();
  sending = true;
  pump();
}

function stopCamera() {
  sending = false;
  if (stream) stream.getTracks().forEach(t => t.stop());
  if (ws) ws.close();
  els("startBtn").disabled = false; els("stopBtn").disabled = true;
  setConn(false);
}

els("startBtn").onclick = () => startCamera().catch(e => alert("Kamera açılamadı: " + e.message));
els("stopBtn").onclick = stopCamera;
els("flipBtn").onclick = () => { facing = facing === "environment" ? "user" : "environment"; if (stream) { stopCamera(); startCamera(); } };
els("cameraSelect").onchange = () => { if (stream) { stopCamera(); startCamera(); } };

/* ── WebSocket ───────────────────────────────────────────────────────── */
function connectWS() {
  ws = new WebSocket(WS);
  ws.onopen = () => setConn(true);
  ws.onclose = () => setConn(false);
  ws.onerror = () => setConn(false);
  ws.onmessage = ev => {
    const data = JSON.parse(ev.data);
    if (data.error) { console.warn(data.error); return; }
    render(data);
  };
}
function setConn(on) {
  const p = els("connPill");
  p.className = "pill " + (on ? "live" : "off");
  els("connTxt").textContent = on ? "Canlı" : "Bağlı değil";
}

/* ── Kare gönderme döngüsü ───────────────────────────────────────────── */
function pump() {
  if (!sending) return;
  if (ws && ws.readyState === WebSocket.OPEN && video.videoWidth) {
    const w = 640, h = Math.round(640 * video.videoHeight / video.videoWidth);
    captureCanvas.width = w; captureCanvas.height = h;
    const c = captureCanvas.getContext("2d");
    c.drawImage(video, 0, 0, w, h);
    // §12-P1: yakalama anı damgası (s) — hız Δt'si ağ varış jitter'ından etkilenmesin
    ws.send(JSON.stringify({
      frame: captureCanvas.toDataURL("image/jpeg", 0.6),
      client_ts: Date.now() / 1000,
    }));
  }
  setTimeout(() => requestAnimationFrame(pump), 1000 / SEND_FPS);
}

/* ── Render ──────────────────────────────────────────────────────────── */
function render(d) {
  drawOverlay(d);
  // mod
  const crit = d.mode === "CRITICAL";
  els("modeBadge").textContent = (crit ? "● KRİTİK (QoD)" : "● NORMAL");
  els("modeBadge").className = "mode-badge" + (crit ? " crit" : "");
  els("videoWrap").className = "video-wrap" + (crit ? " critical" : "");
  // QoD HUD
  els("hudBw").textContent = d.qod.bandwidth_mbps;
  els("hudRes").textContent = crit ? "1080p" : "480p";
  els("hudFps").textContent = d.fps;
  els("qodMode").textContent = d.mode;
  els("qodReason").textContent = d.qod.last_trigger_reason || "—";
  // araç
  els("plate").textContent = d.vehicle.plate.text || "—";
  els("speed").textContent = d.vehicle.speed_kmh != null ? d.vehicle.speed_kmh + " km/h" : "—";
  els("vtype").textContent = d.vehicle.vtype || "—";
  els("vcolor").textContent = d.vehicle.color || "—";
  // Swerving göstergesi
  const swEl = els("swerving");
  if (swEl) {
    swEl.textContent = d.vehicle.swerving ? "⚠ SWERVING" : "—";
    swEl.style.color = d.vehicle.swerving ? "#ff3333" : "inherit";
  }
  // risk
  const r = d.risk;
  els("riskScore").textContent = r.score;
  const lv = els("riskLevel"); lv.textContent = r.level; lv.className = "lvl " + r.level;
  const fill = els("riskFill"); fill.style.width = r.score + "%";
  fill.style.background = r.score >= 85 ? "var(--crit)" : r.score >= 60 ? "#ff8a50" : r.score >= 30 ? "var(--warn)" : "var(--ok)";
  els("riskFactors").innerHTML = (r.factors || []).map(f => `<span class="tag">${f}</span>`).join("");
}

function drawBox(x1, y1, x2, y2, color, label, lineW = 2) {
  const sx = overlay.width / 640;
  const x = x1 * sx, y = y1 * sx, w = (x2 - x1) * sx, h = (y2 - y1) * sx;
  octx.lineWidth = lineW; octx.strokeStyle = color; octx.strokeRect(x, y, w, h);
  if (label) {
    octx.font = "13px Inter, sans-serif";
    const tw = octx.measureText(label).width;
    octx.fillStyle = color;
    octx.fillRect(x, y - 18, tw + 10, 18);
    octx.fillStyle = "#000";
    octx.fillText(label, x + 5, y - 4);
  }
}

function drawROI(x1, y1, x2, y2, color, label) {
  const sx = overlay.width / 640;
  const x = x1 * sx, y = y1 * sx, w = (x2 - x1) * sx, h = (y2 - y1) * sx;
  octx.save();
  octx.setLineDash([6, 4]);
  octx.lineWidth = 1.5; octx.strokeStyle = color; octx.strokeRect(x, y, w, h);
  octx.restore();
  if (label) {
    octx.font = "11px Inter, sans-serif";
    octx.fillStyle = color;
    octx.fillText(label, x + 4, y + 14);
  }
}

function drawOverlay(d) {
  octx.clearRect(0, 0, overlay.width, overlay.height);

  // 1. Araç tespitleri (nesne listesi)
  (d.detections || []).forEach(det => {
    const b = det.bbox;
    if (det.label === "vehicle") return; // araç ayrı çizilir
    if (det.label === "phone") {
      drawBox(b.x1, b.y1, b.x2, b.y2, "#ff4d5e", `telefon ${(det.confidence*100)|0}%`);
    } else if (det.label === "person") {
      drawBox(b.x1, b.y1, b.x2, b.y2, "#ffffff", `kişi ${(det.confidence*100)|0}%`, 1);
    } else {
      drawBox(b.x1, b.y1, b.x2, b.y2, "#2ecc71", `${det.label} ${(det.confidence*100)|0}%`, 1);
    }
  });

  // 2. Araç kutusu (yeşil / kırmızı swerving)
  const v = d.vehicle || {};
  if (v.bbox) {
    const b = v.bbox;
    const swerving = v.swerving;
    const plateText = v.plate?.text || "";
    const speed = v.speed_kmh != null ? `${v.speed_kmh} km/h` : "";
    const vtype = v.vtype || "araç";
    let label = [vtype, plateText, speed].filter(Boolean).join(" | ");
    if (swerving) label = "⚠ SWERVING — " + label;
    drawBox(b.x1, b.y1, b.x2, b.y2, swerving ? "#ff3333" : "#00e676", label, 3);
  }

  // 3. Plaka kutusu (sarı — LP dedektörden)
  if (v.plate_bbox) {
    const b = v.plate_bbox;
    const plateText = v.plate?.text || "?";
    drawBox(b.x1, b.y1, b.x2, b.y2, "#ffee00", `PLAKA: ${plateText}`, 2);
  }

  // 4. Sürücü ROI (mavi kesikli)
  if (v.driver_bbox) {
    const b = v.driver_bbox;
    const phoneLabel = d.driver?.phone_use ? " [TELEFON!]" : "";
    drawROI(b.x1, b.y1, b.x2, b.y2, "#29b6f6", `SÜRÜCÜ${phoneLabel}`);
  }

  // 5. Yolcu ROI (turuncu kesikli)
  if (v.passenger_bbox) {
    const b = v.passenger_bbox;
    const paxPhone = d.driver?.passenger_phone ? " [telefon]" : "";
    drawROI(b.x1, b.y1, b.x2, b.y2, "#ffa726", `YOLCU${paxPhone}`);
  }
}

/* ── Olaylar (periyodik) ─────────────────────────────────────────────── */
async function refreshEvents() {
  try {
    const r = await fetch(`${API}/api/events?min_score=30&limit=8`);
    const evs = await r.json();
    const box = els("events");
    box.innerHTML = evs.length ? evs.map(e => `
      <div class="event">
        <div><div class="plate">${e.plate || "—"}</div>
        <div class="meta">${e.vtype || "araç"} · ${e.speed_kmh ? e.speed_kmh + " km/h" : "—"} · ${(e.factors || "").replaceAll(",", ", ")}</div></div>
        <span class="lvl ${e.risk_level}">${e.risk_score}</span>
      </div>`).join("")
      : `<div class="meta" style="color:var(--muted)">Henüz olay yok.</div>`;
  } catch (e) { /* sessiz */ }
}

async function refreshHealth() {
  try {
    const h = await (await fetch(`${API}/api/health`)).json();
    els("aiModeTxt").textContent = "YZ: " + h.ai_mode + " (" + h.detector + ")";
    els("aiPill").className = "pill live";
    const q = await (await fetch(`${API}/api/qod/status`)).json();
    els("qodEff").textContent = Math.round((q.bandwidth_efficiency || 0) * 100) + "%";
    els("hudLat").textContent = q.latency_ms ?? "—";
  } catch (e) { /* sessiz */ }
}

setInterval(refreshEvents, 2500);
setInterval(refreshHealth, 2000);
refreshHealth();
listCameras();
