/* ---------- ikony ---------- */
const iconActive = new L.Icon({           // zielony – online
  iconUrl: "/static/images/active.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
});
const iconInactive = new L.Icon({         // czerwony – offline
  iconUrl: "/static/images/non_active.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
});
const iconDetected = new L.Icon({         // szary – niezaakceptowany
  iconUrl: "/static/images/drone.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
});
const iconSelected = new L.Icon({         // niebieski – kliknięty
  iconUrl: "/static/images/marked.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41],
});

/* ---------- konfiguracja ---------- */
const apiAll = "/api/telemetry/latest";
const apiList = "/api/drones";
const ACTIVE_THRESHOLD = 5000;   // 5 sekund
const DETECTED_TIMEOUT = 10000;  // 10 sekund

/* ---------- stan aplikacji ---------- */
let acceptedSet = new Set();        // drony zaakceptowane (aktywne/nieaktywne)
let selectedId = null;              // dron wybrany przez użytkownika
let markers = {};                  // id → marker leaflet
let lastSeenMap = {};              // id → timestamp ostatniego sygnału
let map;

/* ---------- mapa ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
  }).addTo(map);
}

/* ---------- funkcja sprawdzająca status drona ---------- */
function droneStatus(id) {
  const ts = lastSeenMap[id];
  if (!ts) return "gone"; // brak sygnału, do usunięcia

  const delta = Date.now() - new Date(ts).getTime();

  if (delta > DETECTED_TIMEOUT) return "gone";      // usuń z wykrytych
  if (delta > ACTIVE_THRESHOLD) return "inactive";  // nieaktywny
  return "active";                                   // aktywny
}

/* ---------- renderowanie list ---------- */
function renderLists(allIds) {
  const elActive = document.getElementById("active-list");
  const elInactive = document.getElementById("inactive-list");
  const elDetected = document.getElementById("detected-list");

  // Usuń z acceptedSet drony, które "gone"
  acceptedSet.forEach(id => {
    if (droneStatus(id) === "gone") acceptedSet.delete(id);
  });

  /** HELPER - tworzenie elementu listy */
  const makeItem = (id, cls, onClick, btnIcon, btnTitle, btnHandler) => {
    const div = document.createElement("div");
    div.className = `item ${cls}` + (id === selectedId ? " selected" : "");
    div.textContent = id;
    div.onclick = onClick;

    if (btnIcon) {
      const btn = document.createElement("button");
      btn.className = "btn-action";
      btn.title = btnTitle;
      btn.innerHTML = btnIcon;
      btn.onclick = (e) => { e.stopPropagation(); btnHandler(); };
      div.appendChild(btn);
    }
    return div;
  };

  /* ---- AKTYWNE ---- */
  const activeIds = [...acceptedSet].filter(id => droneStatus(id) === "active");
  elActive.innerHTML = activeIds.length ? "" : "<em>Brak</em>";
  activeIds.forEach(id => {
    elActive.appendChild(
      makeItem(
        id, "active",
        () => { selectedId = id; refreshOnce(); },
        "✖", "Usuń",
        () => { acceptedSet.delete(id); refreshOnce(); }
      )
    );
  });

  /* ---- NIEAKTYWNE ---- */
  const inactiveIds = [...acceptedSet].filter(id => droneStatus(id) === "inactive");
  elInactive.innerHTML = inactiveIds.length ? "" : "<em>Brak</em>";
  inactiveIds.forEach(id => {
    elInactive.appendChild(
      makeItem(
        id, "inactive",
        () => { selectedId = id; refreshOnce(); },
        "✖", "Usuń",
        () => { acceptedSet.delete(id); refreshOnce(); }
      )
    );
  });

  /* ---- WYKRYTE ---- */
  const detected = allIds.filter(id => !acceptedSet.has(id) && droneStatus(id) !== "gone");
  elDetected.innerHTML = detected.length ? "" : "<em>Brak</em>";
  detected.forEach(id => {
    elDetected.appendChild(
      makeItem(
        id, "detected",
        () => { selectedId = id; refreshOnce(); },
        "✓", "Akceptuj",
        () => { acceptedSet.add(id); if (!selectedId) selectedId = id; refreshOnce(); }
      )
    );
  });
}

/* ---------- aktualizacja markerów ---------- */
function updateMarkers(data) {
  // aktualizuj lastSeenMap
  data.forEach(d => { lastSeenMap[d.drone_id] = d.timestamp; });

  data.forEach(rec => {
    const id = rec.drone_id;
    const pos = [rec.lat, rec.lon];
    const inSet = acceptedSet.has(id);
    const status = droneStatus(id);
    let icon;

    if (id === selectedId) icon = iconSelected;
    else if (!inSet && status !== "gone") icon = iconDetected;
    else if (inSet && status === "inactive") icon = iconInactive;
    else if (inSet && status === "active") icon = iconActive;
    else return; // status "gone" - nie pokazuj markera

    if (!markers[id]) {
      markers[id] = L.marker(pos, { icon }).addTo(map).bindPopup(id);
      markers[id].on("click", () => { selectedId = id; refreshOnce(); });
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
    }
  });
}

/* ---------- pobieranie danych i odświeżanie ---------- */
function refreshOnce() {
  Promise.all([
    fetch(apiList).then(r => r.json()),
    fetch(apiAll).then(r => r.json())
  ])
  .then(([ids, data]) => {
    updateMarkers(data);
    renderLists(ids);
  })
  .catch(console.error);
}

/* ---------- start + pętla ---------- */
initMap();
refreshOnce();
setInterval(refreshOnce, 3000);
