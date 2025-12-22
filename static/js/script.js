/* ---------- ICONS ---------- */
function makeIcon(url) {
  return new L.Icon({
    iconUrl: url,
    shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41],
  });
}

const ICON = {
  active:   makeIcon("/static/images/active.png"),     
  inactive: makeIcon("/static/images/non_active.png"), 
  detected: makeIcon("/static/images/drone.png"),      
  selected: makeIcon("/static/images/marked.png"),     
};

/* ---------- KONFIGURACJA ---------- */
const API_TELEMETRY = "/api/telemetry";
const API_UPLOAD    = "/api/mission/upload";
const API_STOP      = "/api/mission/stop";

const ACTIVE_MS = 5000;   
const DETECT_MS = 10000;  
const ACCEPTED_KEY = "acceptedDrones"; 
const MISSION_KEY = "savedMission"; 

/* ---------- STAN ---------- */
let accepted = new Set();   
let selected = null;
let lastSeen = {};          
let markers  = {};          
let map;
let followSelected = false; 

// Przechowywanie linii "przyszłej trasy" (next_waypoints)
let futureLines = {}; // { drone_id: L.polyline }

// Misja (edycja)
let missionMode = false; 
let missionPoints = [];
let missionPolygon = null;
let missionMarkers = []; 

/* ---------- PERSISTENCE ---------- */
function loadAccepted() {
  try {
    const arr = JSON.parse(localStorage.getItem(ACCEPTED_KEY) || "[]");
    arr.forEach(id => accepted.add(id));
  } catch (e) { console.warn(e); }
}
function saveAccepted() {
  localStorage.setItem(ACCEPTED_KEY, JSON.stringify([...accepted]));
}

/* ---------- HELPERS ---------- */
const norm = id => (id || "").trim();

function statusOf(id) {
  id = norm(id);
  const t = lastSeen[id];
  if (!t) return accepted.has(id) ? "inactive" : "gone";
  const age = Date.now() - t;
  if (!accepted.has(id)) return age > DETECT_MS ? "gone" : "detected";
  return age <= ACTIVE_MS ? "active" : "inactive";
}

/* ---------- HUD ---------- */
function updateHUD(rec) {
  const container = document.getElementById("gauges-container");
  if (!container || !selected) return;

  const roll = rec.roll || 0;
  const pitch = rec.pitch || 0;
  const yaw = rec.yaw || 0;

  const needle = document.getElementById("compass-needle-el");
  const yawText = document.getElementById("hud-yaw");
  if (needle) needle.style.transform = `translate(-50%, -100%) rotate(${yaw}deg)`;
  if (yawText) yawText.textContent = `HDG: ${Math.round(yaw)}°`;

  const horizon = document.getElementById("horizon-gradient");
  const rpText = document.getElementById("hud-roll-pitch");
  if (horizon) {
    const yShift = pitch * 2.5; 
    horizon.style.transform = `rotate(${-roll}deg) translateY(${yShift}px)`;
  }
  if (rpText) rpText.textContent = `R:${roll.toFixed(0)}° P:${pitch.toFixed(0)}°`;
}

/* ---------- MAPA ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OSM" }).addTo(map);
  map.on('dragstart zoomstart movestart', () => { followSelected = false; });
}

/* ---------- RENDER ---------- */
function render(ids) {
  const a = document.getElementById("active-list");
  const i = document.getElementById("inactive-list");
  const d = document.getElementById("detected-list");
  a.innerHTML = i.innerHTML = d.innerHTML = "";

  const addRow = (parent, id, cls, btnTxt, btnAct, extraInfo="") => {
    const row = document.createElement("div");
    row.className = `item ${cls}${id === selected ? " selected" : ""}`;

    const label = document.createElement("div");
    label.innerHTML = `<b>${id}</b> ${extraInfo}`;
    label.style.flex = "1";
    label.onclick = e => { e.stopPropagation(); selectDrone(id); };

    row.appendChild(label);
    const b = document.createElement("button");
    b.className = "btn-action";
    b.textContent = btnTxt;
    b.onclick = e => { e.stopPropagation(); btnAct(id); };
    row.appendChild(b);
    parent.appendChild(row);
  };

  const shown = { a: 0, i: 0, d: 0 };
  ids.forEach(raw => {
    const id = norm(raw);
    const st = statusOf(id);
    
    // Pobieramy dodatkowe dane do wyświetlenia na liście (np. rola)
    let roleInfo = "";
    if (window.cachedData && window.cachedData[id]) {
        const r = window.cachedData[id].role || "None";
        if (r !== "None") roleInfo = `<small>(${r})</small>`;
    }

    if (st === "gone") return;
    if (accepted.has(id)) {
      if (st === "active")  { addRow(a, id, "active",   "❌", delAccepted, roleInfo); shown.a++; }
      else                   { addRow(i, id, "inactive", "❌", delAccepted); shown.i++; }
    } else if (st === "detected") {
      addRow(d, id, "detected", "➕", addAccepted); shown.d++;
    }
  });
  if (!shown.a) a.innerHTML = "<em>Brak</em>";
  if (!shown.i) i.innerHTML = "<em>Brak</em>";
  if (!shown.d) d.innerHTML = "<em>Brak</em>";
}

function selectDrone(id) {
  selected = id;
  followSelected = true;
  if (markers[id]) {
    map.flyTo(markers[id].getLatLng(), Math.max(map.getZoom(), 16), { animate: true, duration: 0.6 });
    markers[id].openPopup();
  }
  refresh();
}
function addAccepted(id) { accepted.add(norm(id)); saveAccepted(); if (!selected) selectDrone(norm(id)); else refresh(); }
function delAccepted(id) { accepted.delete(norm(id)); saveAccepted(); if (selected === norm(id)) selected = null; refresh(); }

/* ---------- MARKERY & WIZUALIZACJA ---------- */
function updateMarkers(data) {
  // Cache data for render()
  window.cachedData = {};
  
  data.forEach(rec => {
    const id = norm(rec.drone_id);
    window.cachedData[id] = rec;
    
    const pos = [rec.lat, rec.lon];
    lastSeen[id] = Date.parse(rec.timestamp.split(".")[0] + "Z") || Date.now();

    const st = statusOf(id);
    let icon = ICON.detected;
    if (st === "active") icon = ICON.active;
    if (st === "inactive") icon = ICON.inactive;
    if (id === selected) icon = ICON.selected;

    if (id === selected) updateHUD(rec);

    // 1. Aktualizacja Markera
    let popupContent = `<b>${id}</b><br>Bat: ${rec.battery || '?'}%<br>Alt: ${rec.alt || 0}m<br>Role: ${rec.role || '-'}`;
    
    if (!markers[id]) {
      markers[id] = L.marker(pos, { icon })
        .addTo(map)
        .bindPopup(popupContent)
        .on("click", () => selectDrone(id));
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
      if(markers[id].isPopupOpen()){
          markers[id].setPopupContent(popupContent);
      }
    }

    // 2. Wizualizacja "Next Waypoints" (Zielona linia wychodząca z drona)
    if (rec.next_waypoints && Array.isArray(rec.next_waypoints) && rec.next_waypoints.length > 0) {
        // Budujemy linię: [PozycjaDrona, Punkt1, Punkt2, ...]
        const pathLine = [pos]; 
        rec.next_waypoints.forEach(wp => {
            pathLine.push([wp.lat, wp.lon]);
        });

        // Jeśli linia już jest, aktualizujemy ją, jeśli nie - tworzymy
        if (futureLines[id]) {
            futureLines[id].setLatLngs(pathLine);
        } else {
            futureLines[id] = L.polyline(pathLine, { color: '#00ff00', weight: 3, opacity: 0.7, dashArray: '5, 5' }).addTo(map);
        }
    } else {
        // Jeśli brak punktów, usuwamy linię
        if (futureLines[id]) {
            map.removeLayer(futureLines[id]);
            delete futureLines[id];
        }
    }
  });
}

async function refresh() {
  try {
    const res = await fetch(API_TELEMETRY);
    const data = await res.json();
    const serverIds = data.map(d => norm(d.drone_id));
    const allIds = [...new Set([...serverIds, ...accepted])];
    updateMarkers(data);
    render(allIds);
  } catch (e) { console.error("API Error", e); }
}

/* ---------- MISJA UI ---------- */

function startMission() {
  missionMode = true;
  missionPoints = [];
  if (missionPolygon) map.removeLayer(missionPolygon);
  missionMarkers.forEach(m => map.removeLayer(m));
  missionMarkers = [];
  document.getElementById("mission-info").textContent = "Zaznacz obszar...";
  map.on("click", addMissionPoint);
}

function addMissionPoint(e) {
  if (!missionMode) return;
  const latlng = e.latlng;
  missionPoints.push(latlng);
  
  const marker = L.marker(latlng, { draggable: true }).addTo(map);
  marker.on("contextmenu", () => {
    map.removeLayer(marker);
    const idx = missionMarkers.indexOf(marker);
    if(idx > -1) {
       missionMarkers.splice(idx, 1);
       missionPoints.splice(idx, 1);
       updateMissionPolygon();
    }
  });
  missionMarkers.push(marker);
  updateMissionPolygon();
  document.getElementById("clear-mission-btn").disabled = true;
}

function finishMission() {
  if (missionPoints.length < 3) return alert("Min 3 punkty!");
  missionMode = false;
  map.off("click", addMissionPoint);
  updateMissionPolygon();
  document.getElementById("mission-info").textContent = "Obszar gotowy.";
  document.getElementById("clear-mission-btn").disabled = false;
  saveMission();
}

function updateMissionPolygon() {
  if (missionPolygon) map.removeLayer(missionPolygon);
  if (missionPoints.length >= 3) {
    missionPolygon = L.polygon([...missionPoints, missionPoints[0]], { color: "#1322E6" }).addTo(map);
  }
}

function saveMission() {
  localStorage.setItem(MISSION_KEY, JSON.stringify(missionPoints.map(p => [p.lat, p.lng])));
}
function loadMission() {
   const raw = localStorage.getItem(MISSION_KEY);
   if(!raw) return;
   try {
     const data = JSON.parse(raw);
     if(Array.isArray(data) && data.length >= 3) {
       missionPoints = data.map(p => L.latLng(p[0], p[1]));
       updateMissionPolygon();
       document.getElementById("clear-mission-btn").disabled = false;
       document.getElementById("mission-info").textContent = "Misja wczytana.";
     }
   } catch(e){}
}

function clearMission() {
  if (confirm("Usunąć misję i ZATRZYMAĆ drony?")) {
    fetch(API_STOP, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ drones: [] }) 
    })
    .then(r => r.json())
    .then(d => {
       alert("🛑 Wysłano STOP do wszystkich dronów.");
    });

    missionPoints = [];
    missionMarkers.forEach(m => map.removeLayer(m));
    missionMarkers = [];
    if (missionPolygon) map.removeLayer(missionPolygon);
    if (window.flightLines) { window.flightLines.forEach(l => map.removeLayer(l)); window.flightLines = []; }
    localStorage.removeItem(MISSION_KEY);
    missionMode = false;
    document.getElementById("mission-info").textContent = "";
  }
}

/* ---------- GENEROWANIE TRASY I PRZYPISYWANIE RÓL ---------- */
/* ---------- GENEROWANIE TRASY I PRZYPISYWANIE RÓL ---------- */
function handleGeneratePath() {
  if (!missionPolygon) return alert("Najpierw zaznacz obszar!");
  
  const missionType = document.getElementById("mission-type-select").value;
  const numDrones = parseInt(prompt("Liczba dronów?", "2"), 10) || 2;
  
  // Dla Leader-Follower wymuszamy min 4m odstępu (ok 0.00004 stopnia)
  // Ale użytkownik podaje w metrach
  let defaultStep = missionType === "leader-follower" ? "10" : "50"; 
  const stepMeters = parseFloat(prompt("Odstęp między liniami (m)?", defaultStep)) || 10;
  
  // 1. Obliczenia Turf (Lawnmower) - generowanie ścieżki
  const latlngs = missionPolygon.getLatLngs()[0]; 
  const coords = latlngs.map(p => [p.lng, p.lat]);
  coords.push(coords[0]); 
  
  const poly = turf.polygon([coords]);
  const bbox = turf.bbox(poly); 
  
  const stepDeg = stepMeters / 111139; 
  let x = bbox[0] + stepDeg/2;
  let lines = [];
  
  while(x < bbox[2]) {
     const line = turf.lineString([[x, bbox[1]-0.1], [x, bbox[3]+0.1]]);
     const clipped = turf.lineIntersect(line, poly);
     if(clipped.features.length >= 2) {
       const pts = clipped.features.map(f => f.geometry.coordinates);
       pts.sort((a,b) => a[1] - b[1]);
       lines.push([ pts[0], pts[1] ]);
     }
     x += stepDeg;
  }
  
  if(lines.length === 0) return alert("Błąd generowania (za mały obszar?).");
  
  // Rysowanie na mapie
  if (window.flightLines) window.flightLines.forEach(l => map.removeLayer(l));
  window.flightLines = [];
  
  let fullPath = [];
  lines.forEach((seg, i) => {
    if(i % 2 === 0) { fullPath.push(seg[0]); fullPath.push(seg[1]); }
    else            { fullPath.push(seg[1]); fullPath.push(seg[0]); }
  });
  
  // --- LOGIKA PRZYDZIAŁU ---
  const newMissionId = "MSN-" + Date.now().toString().slice(-6); 
  const payloadDrones = {};
  
  let activeIds = [...accepted];
  if (activeIds.length === 0) activeIds = ["sim_drone_1", "sim_drone_2"]; // Domyślne ID do testów
  
  // Zabezpieczenie: jeśli wybrano leader-follower a jest 1 dron
  if (missionType === "leader-follower" && numDrones < 2) {
      alert("Tryb Leader-Follower wymaga minimum 2 dronów!");
      return;
  }

  if (missionType === "leader-follower") {
      // --- LOGIKA LEADER-FOLLOWER ---
      // 1. Leader dostaje CAŁĄ trasę
      const leaderId = activeIds[0];
      
      const leafletLine = fullPath.map(pt => [pt[1], pt[0]]);
      const pl = L.polyline(leafletLine, { color: "red", weight: 4 }).addTo(map);
      window.flightLines.push(pl);

      const waypoints = fullPath.map((pt, index) => ({
          seq_id: index,
          lat: pt[1],
          lon: pt[0],
          alt: 20
      }));

      payloadDrones[leaderId] = {
          mission_id: newMissionId,
          waypoints: waypoints,
          role: "leader"
      };

      // 2. Followerzy dostają pustą trasę i rolę follower
      for(let d=1; d<numDrones; d++) {
          const followerId = activeIds[d % activeIds.length];
          payloadDrones[followerId] = {
              mission_id: newMissionId,
              waypoints: [], // Pusta lista punktów, bo podąża za liderem
              role: "follower"
          };
      }

  } else {
      // --- LOGIKA LAWNMOWER (Klasyczna) ---
      const part = Math.ceil(fullPath.length / numDrones);
      const colors = ["red", "orange", "purple", "blue"];
      
      for(let d=0; d<numDrones; d++) {
         const slice = fullPath.slice(d*part, (d+1)*part + 1);
         if(slice.length < 2) continue;
         
         const leafletLine = slice.map(pt => [pt[1], pt[0]]);
         const pl = L.polyline(leafletLine, { color: colors[d % colors.length] }).addTo(map);
         window.flightLines.push(pl);
         
         const targetId = activeIds[d % activeIds.length];
         const waypoints = slice.map((pt, index) => ({
              seq_id: index,
              lat: pt[1],
              lon: pt[0],
              alt: 20
         }));
    
         // Tutaj rola nie ma znaczenia sterującego, ale ustawiamy dla porządku
         payloadDrones[targetId] = {
             mission_id: newMissionId,
             waypoints: waypoints,
             role: "independent" 
         };
      }
  }
  
  // Wysyłka
  document.getElementById("mission-info").textContent = "Wgrywanie...";
  
  fetch(API_UPLOAD, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ drones: payloadDrones })
  })
  .then(r => r.json())
  .then(d => {
    if(d.status === "STORED") {
        alert(`✅ Misja wgrana [Tryb: ${missionType}]!\nID: ${newMissionId}`);
        document.getElementById("mission-info").textContent = "Aktywna: " + newMissionId;
    } else {
        alert("Błąd: " + JSON.stringify(d));
    }
  })
  .catch(e => { console.error(e); alert("Błąd połączenia."); });
}

/* ---------- INIT ---------- */
document.addEventListener("DOMContentLoaded", () => {
  loadAccepted();
  initMap();
  loadMission(); 
  refresh();
  setInterval(refresh, 1000); 

  document.getElementById("mission-btn").onclick = () => {
    if (missionMode) finishMission();
    else startMission();
  };
  document.getElementById("generate-path-btn").onclick = handleGeneratePath;
  document.getElementById("clear-mission-btn").onclick = clearMission;
});