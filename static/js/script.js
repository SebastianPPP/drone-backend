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
const API = "/api/telemetry/latest";
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

/* ---------- render list ---------- */
function render(ids) {
  const a = document.getElementById("active-list");
  const i = document.getElementById("inactive-list");
  const d = document.getElementById("detected-list");
  a.innerHTML = i.innerHTML = d.innerHTML = "";

  const addRow = (parent, id, cls, btnTxt, btnAct) => {
    const row = document.createElement("div");
    row.className = `item ${cls}${id === selected ? " selected" : ""}`;
    row.textContent = id;
    row.onclick = () => { selected = id; refresh(); };
    const b = document.createElement("button");
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
  } catch (e) { console.error(e); }
}

/* ---------- init ---------- */
document.addEventListener("DOMContentLoaded", () => {
  loadAccepted();
  initMap();
  refresh();
  setInterval(refresh, 3000);
  loadMission();
  document.getElementById("generate-path-btn").onclick = () => {
    generateFlightPath(50); // domyślny krok 50 metrów
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

function generateFlightPath(stepMeters = 50) {
  if (!missionPolygon) return;

  const coords = missionPolygon.getLatLngs()[0].map(p => [p.lng, p.lat]);
  const polygon = turf.polygon([[...coords, coords[0]]]);

  const bbox = turf.bbox(polygon);
  const lines = [];
  const step = stepMeters / 111320; // approx meters to degrees
  let y = bbox[1];
  let toggle = false;

  while (y <= bbox[3]) {
    const p1 = [bbox[0], y];
    const p2 = [bbox[2], y];
    const line = turf.lineString([p1, p2]);
    const clipped = turf.lineIntersect(line, polygon);

    if (clipped.features.length >= 2) {
      const sorted = clipped.features
        .map(f => f.geometry.coordinates)
        .sort((a, b) => a[0] - b[0]);

      if (toggle) sorted.reverse();
      lines.push(...sorted);
      toggle = !toggle;
    }

    y += step;
  }

  if (lines.length < 2) return;

  if (window.flightLine) map.removeLayer(window.flightLine);
  window.flightLine = L.polyline(lines.map(c => [c[1], c[0]]), {
    color: 'blue',
    weight: 2
  }).addTo(map);

  const total = turf.length(turf.lineString(lines), { units: 'kilometers' }).toFixed(2);
  document.getElementById("mission-info").textContent += `\nDługość trasy: ${total} km`;
}
