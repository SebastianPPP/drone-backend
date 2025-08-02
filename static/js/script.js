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
  active:   makeIcon("/static/images/active.png"),     // zielony
  inactive: makeIcon("/static/images/non_active.png"), // czerwony
  detected: makeIcon("/static/images/drone.png"),      // szary
  selected: makeIcon("/static/images/marked.png"),     // niebieski
};

/* ---------- konfiguracja ---------- */
const API = "/api/telemetry";
const ACTIVE_MS = 5000;   // <5 s → aktywny
const DETECT_MS = 10000;  // >10 s → usuwamy z wykrytych
const ACCEPTED_KEY = "acceptedDrones"; // klucz w localStorage
const MISSION_KEY = "savedMission"; // klucz dla misji w localStorage

/* ---------- stan ---------- */
let accepted = new Set();   // drony zaakceptowane – trwałe
let selected = null;
let lastSeen = {};          // id → epoch ms
let markers  = {};          // id → L.marker
let map;
let missionMode = false; // tryb misji 
let missionPoints = [];
let missionLine = null;
let missionPolygon = null;
let missionMarkers = []; // do przechowywania markerów misji
let missionStatuses = {}; // droneId => "W trakcie", "Zakończona", itp.

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

/* ---------- mapa ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OSM" }).addTo(map);
}

document.getElementById("mission-btn").onclick = () => {
  if (missionMode) {
    finishMission();
  } else {
    startMission();
  }
};


let expandedMissions = new Set();

function loadExpandedMissions() {
  try {
    const saved = JSON.parse(localStorage.getItem("expandedMissions") || "[]");
    expandedMissions = new Set(saved);
  } catch (e) { expandedMissions = new Set(); }
}

function saveExpandedMissions() {
  localStorage.setItem("expandedMissions", JSON.stringify([...expandedMissions]));
}


/* ---------- render list ---------- */
function render(ids) {
  const a = document.getElementById("active-list");
  const i = document.getElementById("inactive-list");
  const d = document.getElementById("detected-list");
  a.innerHTML = i.innerHTML = d.innerHTML = "";

  const addRow = (parent, id, cls, btnTxt, btnAct) => {
    const row = document.createElement("div");
    row.className = `item ${cls}${id === selected ? " selected" : ""}`;

    // Tworzymy klikany label (tylko on otwiera menu)
    const label = document.createElement("div");
    label.textContent = id;
    label.style.cursor = "pointer";
    label.style.fontWeight = "bold";

    // Element info o misji - ukryty lub widoczny według pamięci
    const missionInfo = document.createElement("div");
    missionInfo.className = "mission-info";
    missionInfo.style.display = expandedMissions.has(id) ? "block" : "none";

    // Zamiast statusu obok nazwy, dajemy np. mały symbol (lub go usuwamy)
    // Usuwam statusLabel - albo możesz zrobić ikonę

    missionInfo.innerHTML = `<small>Informacje o misji drona ${id}:</small><br>Cel: Monitorowanie<br>Status: ${missionStatuses[id] || "Brak misji"}`;

    // Kliknięcie w label toggluje menu i zapisuje stan
    label.onclick = e => {
      e.stopPropagation();
      if (missionInfo.style.display === "block") {
        missionInfo.style.display = "none";
        expandedMissions.delete(id);
      } else {
        missionInfo.style.display = "block";
        expandedMissions.add(id);
      }
      saveExpandedMissions();
    };

    row.appendChild(label);
    row.appendChild(missionInfo);

    const b = document.createElement("button");
    b.textContent = btnTxt;
    b.onclick = e => { 
      e.stopPropagation(); 
      btnAct(id); 
    };
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
  if (selected === norm(id)) selected = null;
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
               st === "active"   ? ICON.active   :
               st === "inactive" ? ICON.inactive :
                                   ICON.detected;
    if (!markers[id]) {
      markers[id] = L.marker(pos, { icon }).addTo(map).bindPopup(id)
        .on("click", () => { selected = id; refresh(); });
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
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
    console.log("telemetry data:", data);

    missionStatuses = {}; // reset statusów misji
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
  setInterval(refresh, 3000);
  loadMission();
  document.getElementById("generate-path-btn").onclick = () => {
    const n = parseInt(prompt("Ile dronów?", "3"), 10);
    if (isNaN(n) || n < 1) return;

    const s = parseFloat(prompt("Podaj krok (w metrach) — np. 50", "50"));
    if (isNaN(s) || s <= 0) return;

    generateFlightPathsForDrones(n, s);
  };

});


/* ---------- mission mode ---------- */
function startMission() {
  missionMode = true;
  missionPoints = [];
  if (missionLine) {
    map.removeLayer(missionLine);
    missionLine = null;
  }
  if (missionPolygon) {
    map.removeLayer(missionPolygon);
    missionPolygon = null;
  }
  document.getElementById("mission-info").textContent = "Tryb misji aktywny. Kliknij na mapę, aby dodać punkty.";
  map.on("click", addMissionPoint);
}


function addMissionPoint(e) {
  if (!missionMode) return;

  const latlng = e.latlng;
  missionPoints.push(latlng);

  const marker = L.marker(latlng, {
    draggable: true,
    icon: L.divIcon({
      className: 'mission-marker',
      html: `<div style="width: 12px; height: 12px; background: #555; border-radius: 50%; border: 2px solid #000;"></div>`,
      iconSize: [12, 12],
      iconAnchor: [6, 6]
    })
  }).addTo(map);

  // Obsługa przeciągania
  marker.on("drag", function (ev) {
    const idx = missionMarkers.indexOf(marker);
    if (idx !== -1) {
      missionPoints[idx] = ev.target.getLatLng();
      updateMissionPolygon();
    }
  });

  // Obsługa prawego kliknięcia (usuń punkt)
  marker.on("contextmenu", function () {
    const idx = missionMarkers.indexOf(marker);
    if (idx !== -1) {
      map.removeLayer(marker);
      missionMarkers.splice(idx, 1);
      missionPoints.splice(idx, 1);
      updateMissionPolygon();
    }
  });

  missionMarkers.push(marker);
  updateMissionPolygon();

  // Podczas dodawania punktów – wyłącz przycisk usuwania
  document.getElementById("clear-mission-btn").disabled = true;
}

function finishMission() {
  if (missionPoints.length < 3) {
    alert("Musisz dodać co najmniej 3 punkty do misji.");
    return;
  }

  missionMode = false;
  map.off("click", addMissionPoint);

  updateMissionPolygon();

  document.getElementById("mission-info").textContent = "Obszar zaznaczony.";
  document.getElementById("clear-mission-btn").disabled = false; // teraz można usunąć

  saveMission();
}


function updateMissionPolygon() {
  if (missionPolygon) {
    map.removeLayer(missionPolygon);
    missionPolygon = null;
  }

  if (missionPoints.length >= 3) {
    missionPolygon = L.polygon([...missionPoints, missionPoints[0]], {
      color: "#999",
      weight: 2,
      fillColor: "#aaa",
      fillOpacity: 0.3
    }).addTo(map);

    const coordList = missionPoints.map(p => `• ${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}`).join("\n");
    document.getElementById("mission-info").innerText = "Misja:\n" + coordList;
  } else {
    document.getElementById("mission-info").innerText = "Dodaj co najmniej 3 punkty do misji.";
  }
}


document.getElementById("clear-mission-btn").onclick = () => {
  if (confirm("Czy na pewno chcesz usunąć całą misję?")) {
    clearMission();
  }
};

function clearMission() {
  missionPoints = [];
  missionMarkers.forEach(m => map.removeLayer(m));
  missionMarkers = [];
  if (missionPolygon) {
    map.removeLayer(missionPolygon);
    missionPolygon = null;
  }

    // 🧽 Usuń trasy lotów
    if (window.flightLines) {
      window.flightLines.forEach(l => map.removeLayer(l));
      window.flightLines = [];
    }

  localStorage.removeItem(MISSION_KEY);
  missionMode = false;
  document.getElementById("mission-info").textContent = "Misja usunięta.";
  document.getElementById("clear-mission-btn").disabled = true;
}


function saveMission() {
  try {
    const coords = missionPoints.map(p => [p.lat, p.lng]);
    localStorage.setItem(MISSION_KEY, JSON.stringify(coords));
  } catch (e) {
    console.warn("Nie udało się zapisać misji", e);
  }
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

function generateFlightPathsForDrones(numDrones = 3, stepMeters = 50) {
  if (!missionPolygon) {
    alert("Najpierw zaznacz obszar misji.");
    return;
  }

  // Pobierz aktywne drony (w kolejności alfabetycznej)
  const activeDrones = [...accepted].filter(id => statusOf(id) === "active");
  activeDrones.sort();

  if (activeDrones.length < numDrones) {
    alert(`Liczba aktywnych dronów (${activeDrones.length}) jest mniejsza niż wymagana (${numDrones}). Nie wysyłam tras.`);
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
  document.getElementById("mission-info").textContent += `\nTrasa dla ${numDrones} dronów, łączna długość: ${totalKm} km`;

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
      })
      .catch(err => {
        console.error("❌ Błąd podczas wysyłania misji:", err);
      });
  }
}

