/* ---------- ikony ---------- */
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

/* ---------- konfiguracja ---------- */
const API = "/api/telemetry";
const ACTIVE_MS = 5000;   
const DETECT_MS = 10000;  
const ACCEPTED_KEY = "acceptedDrones"; 
const MISSION_KEY = "savedMission"; 

/* ---------- stan ---------- */
let accepted = new Set();   
let selected = null;
let lastSeen = {};          
let markers  = {};          
let map;
let followSelected = false; 
let missionMode = false; 
let missionPoints = [];
let missionLine = null;
let missionPolygon = null;
let missionMarkers = []; 
let missionStatuses = {}; 
let expandedMissions = new Set();

/* ---------- persistence ---------- */
function loadAccepted() {
  try {
    const arr = JSON.parse(localStorage.getItem(ACCEPTED_KEY) || "[]");
    arr.forEach(id => accepted.add(id));
  } catch (e) { console.warn("Nie udało się odczytać localStorage", e); }
}
function saveAccepted() {
  try {
    localStorage.setItem(ACCEPTED_KEY, JSON.stringify([...accepted]));
  } catch (e) { console.warn("Nie udało się zapisać localStorage", e); }
}
function loadExpandedMissions() {
  try {
    const saved = JSON.parse(localStorage.getItem("expandedMissions") || "[]");
    expandedMissions = new Set(saved);
  } catch (e) { expandedMissions = new Set(); }
}
function saveExpandedMissions() {
  localStorage.setItem("expandedMissions", JSON.stringify([...expandedMissions]));
}

/* ---------- helpers ---------- */
const norm = id => (id || "").trim();
function statusOf(id) {
  id = norm(id);
  const t = lastSeen[id];
  if (!t) return accepted.has(id) ? "inactive" : "gone";
  const age = Date.now() - t;
  if (!accepted.has(id)) return age > DETECT_MS ? "gone" : "detected";
  return age <= ACTIVE_MS ? "active" : "inactive";
}

/* ---------- HUD / SZTUCZNY HORYZONT (NOWOŚĆ) ---------- */
function initHUD() {
  // 1. Wstrzyknięcie stylów CSS dla HUDa
  const style = document.createElement('style');
  style.innerHTML = `
    #hud-container {
      position: absolute;
      top: 10px;
      right: 10px;
      z-index: 1000;
      width: 160px;
      background: rgba(0, 0, 0, 0.6);
      border-radius: 10px;
      padding: 10px;
      display: none; /* Domyślnie ukryty, pokazuje się po wybraniu drona */
      text-align: center;
      box-shadow: 0 0 15px rgba(0,0,0,0.5);
      font-family: monospace;
      color: white;
      backdrop-filter: blur(4px);
    }
    #hud-title { font-size: 12px; margin-bottom: 5px; color: #ffa500; font-weight: bold; }
    
    /* Okrągły wskaźnik */
    #attitude-indicator {
      width: 120px;
      height: 120px;
      background: #333;
      border-radius: 50%;
      border: 3px solid #fff;
      margin: 0 auto 10px auto;
      position: relative;
      overflow: hidden;
    }
    
    /* Tło Niebo/Ziemia - znacznie większe od okna, żeby przesuwać góra/dół */
    #horizon-sky-ground {
      width: 300px;
      height: 300px;
      background: linear-gradient(to bottom, #3ebfff 50%, #8b4513 50%);
      position: absolute;
      top: -90px;
      left: -90px;
      transition: transform 0.2s linear;
    }

    /* Linia horyzontu (biała kreska) */
    #horizon-line {
      width: 100%;
      height: 1px;
      background: rgba(255,255,255,0.5);
      position: absolute;
      top: 50%;
    }

    /* Samolot (celownik) na stałe na środku */
    #hud-crosshair {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 60px;
      height: 10px;
      border-left: 20px solid #ffcc00;
      border-right: 20px solid #ffcc00;
      border-top: 0;
      border-bottom: 0;
    }
    #hud-center-dot {
       position: absolute; top: 50%; left: 50%;
       width: 4px; height: 4px; background: #ffcc00;
       transform: translate(-50%, -50%); border-radius: 50%;
    }

    /* Statystyki tekstowe */
    #hud-stats div { margin: 2px 0; font-size: 12px; }
    .val-label { color: #aaa; }
    .val-data { font-weight: bold; }
  `;
  document.head.appendChild(style);

  // 2. Utworzenie struktury HTML
  const hudHTML = `
    <div id="hud-title">BRAK DANYCH</div>
    <div id="attitude-indicator">
      <div id="horizon-sky-ground">
        <div id="horizon-line"></div>
      </div>
      <div id="hud-crosshair"></div>
      <div id="hud-center-dot"></div>
    </div>
    <div id="hud-stats">
      <div><span class="val-label">ROLL:</span> <span id="hud-roll" class="val-data">0°</span></div>
      <div><span class="val-label">PITCH:</span> <span id="hud-pitch" class="val-data">0°</span></div>
      <div><span class="val-label">YAW:</span> <span id="hud-yaw" class="val-data">0°</span></div>
    </div>
  `;

  const container = document.createElement("div");
  container.id = "hud-container";
  container.innerHTML = hudHTML;
  document.body.appendChild(container);
}

function updateHUD(droneId, data) {
  const container = document.getElementById("hud-container");
  if (!container) return;

  // Pokaż panel tylko jeśli mamy wybranego drona
  container.style.display = "block";
  document.getElementById("hud-title").textContent = droneId;

  // Pobierz wartości (domyślnie 0 jeśli brak)
  const roll = data.roll || 0;
  const pitch = data.pitch || 0;
  const yaw = data.yaw || 0;

  // Aktualizacja tekstu
  document.getElementById("hud-roll").textContent = roll.toFixed(1) + "°";
  document.getElementById("hud-pitch").textContent = pitch.toFixed(1) + "°";
  document.getElementById("hud-yaw").textContent = yaw.toFixed(1) + "°";

  // Aktualizacja grafiki (sztuczny horyzont)
  const horizon = document.getElementById("horizon-sky-ground");
  
  // LOGIKA:
  // Rotate: ujemny roll, żeby horyzont przechylał się przeciwnie do drona
  // TranslateY: pitch dodatni (nos w górę) -> horyzont w dół (widzimy więcej nieba).
  // Mnożnik 2.5 służy do skalowania (żeby mały ruch był widoczny)
  horizon.style.transform = `rotate(${-roll}deg) translateY(${pitch * 2.5}px)`;
}

/* ---------- mapa ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OSM" }).addTo(map);
  map.on('dragstart zoomstart movestart', () => { followSelected = false; });
  
  // Inicjalizacja HUDa przy starcie mapy
  initHUD();
}

document.getElementById("mission-btn").onclick = () => {
  if (missionMode) finishMission();
  else startMission();
};

/* ---------- render list ---------- */
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
    label.style.cursor = "pointer";
    label.style.fontWeight = "bold";
    label.style.flex = "1";

    label.onclick = e => {
      e.stopPropagation();
      selected = id;
      followSelected = true;
      if (markers[id]) {
        map.flyTo(markers[id].getLatLng(), Math.max(map.getZoom(), 16), { animate: true, duration: 0.6 });
        markers[id].openPopup();
        
        // Pokaż HUD dla tego drona natychmiast
        // (Dane zostaną zaktualizowane w najbliższym refresh())
        const container = document.getElementById("hud-container");
        if(container) container.style.display = "block";
      }
      refresh(); // Wymuś odświeżenie UI
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
      if (st === "active")  { addRow(a, id, "active",   "Usuń", delAccepted); shown.a++; }
      else                   { addRow(i, id, "inactive", "Usuń", delAccepted); shown.i++; }
    } else if (st === "detected") {
      addRow(d, id, "detected", "Akceptuj", addAccepted); shown.d++;
    }
  });
  if (!shown.a) a.innerHTML = "<em>Brak</em>";
  if (!shown.i) i.innerHTML = "<em>Brak</em>";
  if (!shown.d) d.innerHTML = "<em>Brak</em>";
}

function addAccepted(id) {
  accepted.add(norm(id));
  saveAccepted();
  if (!selected) selected = norm(id);
  refresh();
}
function delAccepted(id) {
  accepted.delete(norm(id));
  saveAccepted();
  if (selected === norm(id)) {
    selected = null;
    // Ukryj HUD po usunięciu
    const container = document.getElementById("hud-container");
    if(container) container.style.display = "none";
  }
  refresh();
}

/* ---------- markery ---------- */
function updateMarkers(data) {
  data.forEach(rec => {
    const id = norm(rec.drone_id);
    const pos = [rec.lat, rec.lon];
    lastSeen[id] = Date.parse(rec.timestamp.split(".")[0] + "Z");

    const st = statusOf(id);
    let icon = id === selected ? ICON.selected :
               st === "active"   ? ICON.active :
               st === "inactive" ? ICON.inactive :
                                   ICON.detected;

    // Aktualizacja HUD jeśli to wybrany dron
    if (id === selected) {
      updateHUD(id, rec);
    }

    if (!markers[id]) {
      markers[id] = L.marker(pos, { icon })
        .addTo(map)
        .bindPopup(`<b>${id}</b>`) // Uproszczony popup, bo mamy HUD
        .on("click", () => {
          selected = id;
          followSelected = true;
          map.flyTo(markers[id].getLatLng(), Math.max(map.getZoom(), 16), { animate: true, duration: 0.6 });
          updateHUD(id, rec);
          refresh();
        });
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
      // Opcjonalnie aktualizacja treści popupu, jeśli jest otwarty
      if(markers[id].isPopupOpen()){
          markers[id].setPopupContent(`
            <b>${id}</b><br>
            Bat: ${rec.battery}%<br>
            Alt: ${rec.alt}m
          `);
      }
    }
  });
}

/* ---------- fetch ---------- */
async function refresh() {
  try {
    const res = await fetch(API);
    const data = await res.json();
    const ids = [...new Set([...data.map(d => norm(d.drone_id)), ...accepted])];
    
    updateMarkers(data);
    render(ids);

    missionStatuses = {};
    data.forEach(d => {
      missionStatuses[d.drone_id] = d.mission_status || "Brak misji";
    });
  } catch (e) { console.error(e); }
}

/* ---------- init ---------- */
document.addEventListener("DOMContentLoaded", () => {
  loadAccepted();
  loadExpandedMissions();
  initMap();
  refresh();
  setInterval(refresh, 1000); // Zwiększono częstotliwość do 1s dla płynniejszego HUD
  loadMission();
  
  // Obsługa generowania tras (zostawiam bez zmian, wklejone dla kompletności)
  document.getElementById("generate-path-btn").onclick = () => {
    const acceptedDronesList = [...accepted].sort();
    if (acceptedDronesList.length === 0) {
      alert("❌ Brak zaakceptowanych dronów!");
      return;
    }
    const droneStatuses = acceptedDronesList.map(id => {
      const age = Date.now() - (lastSeen[id] || 0);
      return `${id} ${age <= 10000 ? "✅ AKTYWNY" : "⏱️ NIEAKTYWNY"}`;
    }).join("\n");
    
    alert(`✅ Drony:\n\n${droneStatuses}`);
    
    const algo = prompt("1-Lawnmower, 2-DStar, 3-VFH", "1");
    if(!algo) return;
    
    const n = parseInt(prompt("Ile dronów?", Math.min(3, acceptedDronesList.length)), 10);
    const s = parseFloat(prompt("Krok (m)?", "50"));
    
    generateFlightPathsForDrones(n, s, algo, "Algo");
  };
});

/* ---------- mission mode (bez zmian, skrócenie dla czytelności) ---------- */
function startMission() {
  missionMode = true;
  missionPoints = [];
  if (missionLine) map.removeLayer(missionLine);
  if (missionPolygon) map.removeLayer(missionPolygon);
  document.getElementById("mission-info").textContent = "Tryb misji. Klikaj mapę.";
  map.on("click", addMissionPoint);
}
function addMissionPoint(e) {
  if (!missionMode) return;
  const latlng = e.latlng;
  missionPoints.push(latlng);
  const marker = L.marker(latlng, { draggable: true }).addTo(map);
  marker.on("drag", ev => {
     const idx = missionMarkers.indexOf(marker);
     if (idx !== -1) { missionPoints[idx] = ev.target.getLatLng(); updateMissionPolygon(); }
  });
  marker.on("contextmenu", () => {
     const idx = missionMarkers.indexOf(marker);
     map.removeLayer(marker);
     missionMarkers.splice(idx, 1);
     missionPoints.splice(idx, 1);
     updateMissionPolygon();
  });
  missionMarkers.push(marker);
  updateMissionPolygon();
  document.getElementById("clear-mission-btn").disabled = true;
}
function finishMission() {
  if (missionPoints.length < 3) return alert("Min 3 punkty");
  missionMode = false;
  map.off("click", addMissionPoint);
  updateMissionPolygon();
  document.getElementById("mission-info").textContent = "Obszar zaznaczony.";
  document.getElementById("clear-mission-btn").disabled = false;
  saveMission();
}
function updateMissionPolygon() {
  if (missionPolygon) map.removeLayer(missionPolygon);
  if (missionPoints.length >= 3) {
    missionPolygon = L.polygon([...missionPoints, missionPoints[0]], { color: "#1322E6" }).addTo(map);
  }
}
document.getElementById("clear-mission-btn").onclick = () => {
  if (confirm("Usunąć misję?")) clearMission();
};
function clearMission() {
  missionPoints = [];
  missionMarkers.forEach(m => map.removeLayer(m));
  missionMarkers = [];
  if (missionPolygon) map.removeLayer(missionPolygon);
  if (window.flightLines) { window.flightLines.forEach(l => map.removeLayer(l)); window.flightLines = []; }
  localStorage.removeItem(MISSION_KEY);
  missionMode = false;
  document.getElementById("mission-info").textContent = "Usunięto.";
}
function saveMission() {
  localStorage.setItem(MISSION_KEY, JSON.stringify(missionPoints.map(p => [p.lat, p.lng])));
}

function loadMission() {
  try {
    const data = JSON.parse(localStorage.getItem(MISSION_KEY));
    if (!Array.isArray(data) || data.length < 3) return;

    missionPoints = data.map(pair => L.latLng(pair[0], pair[1]));

    // Dodaj markery
    missionMarkers = missionPoints.map((latlng, idx) => {
      const marker = L.marker(latlng, {
        draggable: true,
        icon: L.divIcon({
          className: 'mission-marker',
          html: `<div style="width: 12px; height: 12px; background: #555; border-radius: 50%; border: 2px solid #000;"></div>`,
          iconSize: [12, 12],
          iconAnchor: [6, 6]
        })
      }).addTo(map);

      marker.on("drag", function (ev) {
        missionPoints[idx] = ev.target.getLatLng();
        updateMissionPolygon();
        saveMission(); // zapisuj po każdym drag
      });

      marker.on("contextmenu", function () {
        map.removeLayer(marker);
        missionMarkers.splice(idx, 1);
        missionPoints.splice(idx, 1);
        updateMissionPolygon();
        saveMission();
      });

      return marker;
    });

    updateMissionPolygon();
    document.getElementById("clear-mission-btn").disabled = false;
    document.getElementById("mission-info").textContent = "Misja przywrócona.";
  } catch (e) {
    console.warn("Nie udało się załadować misji", e);
  }
}

/* ---------- generowanie tras ---------- */

function generateFlightPathsForDrones(numDrones = 3, stepMeters = 50, algorithm = "1", algorithmName = "Lawnmower") {
  if (!missionPolygon) {
    alert("Najpierw zaznacz obszar misji.");
    return;
  }

  // Używamy zaakceptowanych dronów (nie filtrujemy po ostatnim widzeniu)
  const activeDrones = [...accepted];
  activeDrones.sort();

  if (activeDrones.length < numDrones) {
    alert(`Liczba dostępnych (zaakceptowanych) dronów (${activeDrones.length}) jest mniejsza niż wymagana (${numDrones}). Nie wysyłam tras.`);
    return;
  }

  // 🧽 Usuń stare trasy
  if (window.flightLines) {
    window.flightLines.forEach(l => map.removeLayer(l));
  }
  window.flightLines = [];

  const coords = missionPolygon.getLatLngs()[0].map(p => [p.lng, p.lat]);
  const polygon = turf.polygon([[...coords, coords[0]]]); // zamknięty ring
  const bbox = turf.bbox(polygon);
  const stepDeg = stepMeters / 111320;

  const centerY = (bbox[1] + bbox[3]) / 2;
  const width = bbox[2] - bbox[0];

  let y = bbox[1] + stepDeg / 2;
  const linesInside = [];
  let toggle = false;

  while (y <= bbox[3]) {
    const fullLine = turf.lineString([[bbox[0] - width, y], [bbox[2] + width, y]]);
    const clipped = turf.lineIntersect(fullLine, polygon);

    if (clipped.features.length >= 2) {
      const pts = clipped.features.map(f => f.geometry.coordinates);
      pts.sort((a, b) => a[0] - b[0]); // sortuj po długości geograficznej

      const inside = toggle ? [pts[1], pts[0]] : [pts[0], pts[1]];
      linesInside.push(inside);
      toggle = !toggle;
    }

    y += stepDeg;
  }

  if (linesInside.length < 1) {
    alert("Nie udało się wygenerować trasy – upewnij się, że obszar nie jest zbyt mały.");
    return;
  }

  // 🔁 Zawrotki: dodajemy tam i z powrotem
  const flightPath = [];
  for (let i = 0; i < linesInside.length; i++) {
    flightPath.push(linesInside[i][0]);
    flightPath.push(linesInside[i][1]);
  }

  // 🔀 Rozdziel ścieżkę między drony
  const totalPoints = flightPath.length;
  const pointsPerDrone = Math.ceil(totalPoints / numDrones);
  const colors = ["red", "green", "blue", "orange", "purple", "brown"];

  // Przechowujemy ścieżki dla każdego drona
  const allDronePaths = {};

  for (let d = 0; d < numDrones; d++) {
    const startIdx = d * pointsPerDrone;
    const endIdx = Math.min(startIdx + pointsPerDrone, totalPoints);
    const path = flightPath.slice(startIdx, endIdx);

    if (path.length < 2) continue;

    // Narysuj ścieżkę na mapie
    const polyline = L.polyline(path.map(c => [c[1], c[0]]), {
      color: colors[d % colors.length],
      weight: 2
    }).addTo(map);

    window.flightLines.push(polyline);

    // Przypisz trasę do aktywnego drona
    const droneId = activeDrones[d];
    allDronePaths[droneId] = path;
  }

  const totalKm = turf.length(turf.lineString(flightPath), { units: 'kilometers' }).toFixed(2);
  const infoText = `📍 Algorytm: ${algorithmName}\n🛸 Drony (${numDrones}): ${activeDrones.slice(0, numDrones).join(", ")}\n📏 Krok: ${stepMeters}m\n📊 Długość: ${totalKm} km`;
  document.getElementById("mission-info").textContent = infoText;

  // Wysyłamy tylko, jeśli mamy trasy do wysłania
  if (Object.keys(allDronePaths).length > 0) {
    fetch("/api/mission/upload", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ drones: allDronePaths })
    })
      .then(res => res.json())
      .then(data => {
        console.log("✅ Misja wysłana:", data);
        document.getElementById("mission-info").textContent += "\n✅ Trasy wysłane do dronów!";
      })
      .catch(err => {
        console.error("❌ Błąd podczas wysyłania misji:", err);
        document.getElementById("mission-info").textContent += "\n❌ Błąd wysyłania tras!";
      });
  }
}

