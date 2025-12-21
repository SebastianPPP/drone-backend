/* ---------- ICONS (Placeholdery - podmień URL jeśli masz lokalne) ---------- */
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
// Używamy darmowych ikon z GitHub jako przykład
const ICON = {
  active:   makeIcon("https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png"),     
  inactive: makeIcon("https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png"), 
  detected: makeIcon("https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-grey.png"),      
  selected: makeIcon("https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png"),     
};

/* ---------- KONFIGURACJA ---------- */
const API = "/api/telemetry";
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
let missionMode = false; 
let missionPoints = [];
let missionPolygon = null;
let missionMarkers = []; 

/* ---------- PERSISTENCE ---------- */
function loadAccepted() {
  try {
    const arr = JSON.parse(localStorage.getItem(ACCEPTED_KEY) || "[]");
    arr.forEach(id => accepted.add(id));
  } catch (e) { console.warn("Load error", e); }
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

/* ---------- HUD / ZEGARY (LOGIKA) ---------- */
function updateHUD(rec) {
  const container = document.getElementById("gauges-container");
  if (!container) return; // Jeśli HTML się nie załadował

  // Jeśli nie ma zaznaczonego drona, ukryj lub zresetuj (opcjonalne)
  if (!selected) return;

  const roll = rec.roll || 0;
  const pitch = rec.pitch || 0;
  const yaw = rec.yaw || 0;

  // --- 1. KOMPAS ---
  const needle = document.getElementById("compass-needle-el");
  const yawText = document.getElementById("hud-yaw");
  
  if (needle) {
    // translate(-50%, -100%) trzyma igłę w punkcie zaczepienia
    needle.style.transform = `translate(-50%, -100%) rotate(${yaw}deg)`;
  }
  if (yawText) yawText.textContent = `HDG: ${Math.round(yaw)}°`;

  // --- 2. SZTUCZNY HORYZONT ---
  const horizon = document.getElementById("horizon-gradient");
  const rpText = document.getElementById("hud-roll-pitch");

  if (horizon) {
    // NAPRAWA LOGIKI:
    // Pitch + (nos w górę) -> chcemy widzieć więcej nieba (gradient w dół).
    // CSS translateY(+) przesuwa w dół.
    // Mnożnik 2.5 określa czułość.
    const yShift = pitch * 2.5; 
    
    // Roll: obracamy tło przeciwnie do drona
    horizon.style.transform = `rotate(${-roll}deg) translateY(${yShift}px)`;
  }
  if (rpText) rpText.textContent = `R:${roll.toFixed(0)}° P:${pitch.toFixed(0)}°`;
}

/* ---------- MAPA ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OSM" }).addTo(map);
  
  map.on('dragstart zoomstart movestart', () => { 
    followSelected = false; 
  });
}

/* ---------- RENDEROWANIE LISTY ---------- */
function render(ids) {
  const a = document.getElementById("active-list");
  const i = document.getElementById("inactive-list");
  const d = document.getElementById("detected-list");
  a.innerHTML = i.innerHTML = d.innerHTML = "";

  const addRow = (parent, id, cls, btnTxt, btnAct) => {
    const row = document.createElement("div");
    row.className = `item ${cls}${id === selected ? " selected" : ""}`;

    const label = document.createElement("div");
    label.textContent = id;
    label.style.flex = "1";
    
    // Kliknięcie w drona na liście
    label.onclick = e => {
      e.stopPropagation();
      selectDrone(id);
    };

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
    if (st === "gone") return;

    if (accepted.has(id)) {
      if (st === "active")  { addRow(a, id, "active",   "❌", delAccepted); shown.a++; }
      else                  { addRow(i, id, "inactive", "❌", delAccepted); shown.i++; }
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

function addAccepted(id) {
  accepted.add(norm(id));
  saveAccepted();
  if (!selected) selectDrone(norm(id));
  else refresh();
}

function delAccepted(id) {
  accepted.delete(norm(id));
  saveAccepted();
  if (selected === norm(id)) {
    selected = null;
    // Można tu ukryć HUD jeśli chcesz
  }
  refresh();
}

/* ---------- MARKERY ---------- */
function updateMarkers(data) {
  data.forEach(rec => {
    const id = norm(rec.drone_id);
    const pos = [rec.lat, rec.lon];
    lastSeen[id] = Date.parse(rec.timestamp.split(".")[0] + "Z") || Date.now();

    const st = statusOf(id);
    let icon = ICON.detected;
    if (st === "active") icon = ICON.active;
    if (st === "inactive") icon = ICON.inactive;
    if (id === selected) icon = ICON.selected;

    // *** AKTUALIZACJA HUD ***
    if (id === selected) {
      updateHUD(rec);
    }

    if (!markers[id]) {
      markers[id] = L.marker(pos, { icon })
        .addTo(map)
        .bindPopup(`<b>${id}</b>`)
        .on("click", () => selectDrone(id));
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
      if(markers[id].isPopupOpen()){
          markers[id].setPopupContent(`
            <b>${id}</b><br>
            Bat: ${rec.battery || '?'}%<br>
            Alt: ${rec.alt || 0}m
          `);
      }
    }
  });
}

/* ---------- FETCH ---------- */
async function refresh() {
  try {
    const res = await fetch(API);
    const data = await res.json();
    
    // Lista wszystkich ID
    const serverIds = data.map(d => norm(d.drone_id));
    const allIds = [...new Set([...serverIds, ...accepted])];
    
    updateMarkers(data);
    render(allIds);

  } catch (e) { console.error("API Error", e); }
}

/* ---------- MISJA (Skrócona) ---------- */
function startMission() {
  missionMode = true;
  missionPoints = [];
  if (missionPolygon) map.removeLayer(missionPolygon);
  missionMarkers.forEach(m => map.removeLayer(m));
  missionMarkers = [];
  
  document.getElementById("mission-info").textContent = "Klikaj na mapie...";
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

function finishMission() { // Wywoływane ponownym kliknięciem przycisku
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
  missionPoints = [];
  missionMarkers.forEach(m => map.removeLayer(m));
  missionMarkers = [];
  if (missionPolygon) map.removeLayer(missionPolygon);
  if (window.flightLines) { window.flightLines.forEach(l => map.removeLayer(l)); window.flightLines = []; }
  localStorage.removeItem(MISSION_KEY);
  missionMode = false;
  document.getElementById("mission-info").textContent = "";
}

/* ---------- GENEROWANIE TRASY (Lawnmower) ---------- */
function handleGeneratePath() {
  if (!missionPolygon) return alert("Najpierw zaznacz obszar!");
  
  const numDrones = parseInt(prompt("Liczba dronów?", "1"), 10) || 1;
  const stepMeters = parseFloat(prompt("Odstęp (m)?", "50")) || 50;
  
  // Konwersja do GeoJSON
  const latlngs = missionPolygon.getLatLngs()[0]; 
  const coords = latlngs.map(p => [p.lng, p.lat]);
  coords.push(coords[0]); // Zamknięcie
  
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
  
  if(lines.length === 0) return alert("Brak trasy. Obszar zbyt mały?");
  
  // Rysowanie
  if (window.flightLines) window.flightLines.forEach(l => map.removeLayer(l));
  window.flightLines = [];
  
  let fullPath = [];
  lines.forEach((seg, i) => {
    if(i % 2 === 0) { fullPath.push(seg[0]); fullPath.push(seg[1]); }
    else            { fullPath.push(seg[1]); fullPath.push(seg[0]); }
  });
  
  // Podział na drony
  const part = Math.ceil(fullPath.length / numDrones);
  const colors = ["red", "orange", "purple"];
  const payload = {};
  const activeIds = [...accepted].slice(0, numDrones);
  
  for(let d=0; d<numDrones; d++) {
     const slice = fullPath.slice(d*part, (d+1)*part + 1);
     if(slice.length < 2) continue;
     
     const leafletLine = slice.map(pt => [pt[1], pt[0]]);
     const pl = L.polyline(leafletLine, { color: colors[d % colors.length] }).addTo(map);
     window.flightLines.push(pl);
     
     if(activeIds[d]) {
       payload[activeIds[d]] = leafletLine;
     }
  }
  
  fetch("/api/mission/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ drones: payload })
  })
  .then(r => r.json())
  .then(d => alert("Wysłano: " + JSON.stringify(d)))
  .catch(e => console.error(e));
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
  document.getElementById("clear-mission-btn").onclick = () => {
    if (confirm("Usunąć misję?")) clearMission();
  };
});