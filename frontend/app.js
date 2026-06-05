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
    ws.send(JSON.stringify({ frame: captureCanvas.toDataURL("image/jpeg", 0.6) }));
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
  // risk
  const r = d.risk;
  els("riskScore").textContent = r.score;
  const lv = els("riskLevel"); lv.textContent = r.level; lv.className = "lvl " + r.level;
  const fill = els("riskFill"); fill.style.width = r.score + "%";
  fill.style.background = r.score >= 85 ? "var(--crit)" : r.score >= 60 ? "#ff8a50" : r.score >= 30 ? "var(--warn)" : "var(--ok)";
  els("riskFactors").innerHTML = (r.factors || []).map(f => `<span class="tag">${f}</span>`).join("");
}

function drawOverlay(d) {
  octx.clearRect(0, 0, overlay.width, overlay.height);
  const sx = overlay.width / 640, sy = sx; // ingest 640 genişliğinde gönderildi
  (d.detections || []).forEach(det => {
    const b = det.bbox;
    const x = b.x1 * sx, y = b.y1 * sy, w = (b.x2 - b.x1) * sx, h = (b.y2 - b.y1) * sy;
    const color = det.label === "vehicle" ? "#2f7bff" : det.label === "phone" ? "#ff4d5e" : "#2ecc71";
    octx.lineWidth = 3; octx.strokeStyle = color; octx.strokeRect(x, y, w, h);
    octx.fillStyle = color; octx.font = "14px Inter, sans-serif";
    const txt = `${det.label} ${(det.confidence * 100) | 0}%`;
    octx.fillRect(x, y - 18, octx.measureText(txt).width + 10, 18);
    octx.fillStyle = "#fff"; octx.fillText(txt, x + 5, y - 4);
  });
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
