/* -------- ikony -------- */
const blueIcon = new L.Icon.Default();              // online
const redIcon  = new L.Icon({                       // offline
  iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x-red.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});
const greenIcon = new L.Icon({                      // wybrany
  iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x-green.png",
  shadowUrl:"https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});

/* -------- konfiguracja -------- */
const apiAll  = "/api/telemetry/latest";
const apiList = "/api/drones";
const OFFLINE_MS = 5000;            // 5 s bez danych → offline

/* -------- stan aplikacji -------- */
let activeSet   = new Set();        // zaakceptowane drony
let selectedId  = null;             // aktualnie wybrany
let markers     = {};               // id → L.marker
let lastSeenMap = {};               // id → czas ISO
let map;

/* -------- mapa -------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution:"© OpenStreetMap",
  }).addTo(map);
}

/* -------- render list po prawej -------- */
function renderLists(allIds) {
  const activeDiv   = document.getElementById("active-list");
  const detectedDiv = document.getElementById("detected-list");

  // usuń stale nieistniejące z activeSet
  activeSet.forEach(id => { if (!allIds.includes(id)) activeSet.delete(id); });

  /* --- AKTYWNE --- */
  activeDiv.innerHTML = "";
  if (activeSet.size === 0) activeDiv.innerHTML = "<em>Brak</em>";
  activeSet.forEach(id => {
    const li = document.createElement("div");
    li.className = "item" +
      (id === selectedId ? " active" : "") +
      (isOffline(id) ? " offline" : "");
    li.textContent = id;
    li.onclick = () => { selectedId = id; updateMarkers(); renderLists(allIds); };
    activeDiv.appendChild(li);
  });

  /* --- WYKRYTE --- */
  const detected = allIds.filter(id => !activeSet.has(id));
  detectedDiv.innerHTML = "";
  if (detected.length === 0) detectedDiv.innerHTML = "<em>Brak</em>";
  detected.forEach(id => {
    const li = document.createElement("div");
    li.className = "item";
    li.textContent = id;

    // przycisk „Akceptuj”
    const btn = document.createElement("button");
    btn.className = "btn-acc";
    btn.textContent = "Akceptuj";
    btn.onclick = (e) => {
      e.stopPropagation();
      activeSet.add(id);
      if (!selectedId) selectedId = id;
      renderLists(allIds);
      updateMarkers();
    };
    li.appendChild(btn);
    detectedDiv.appendChild(li);
  });
}

/* -------- sprawdź offline -------- */
function isOffline(id){
  const ts = lastSeenMap[id];
  if (!ts) return true;
  return Date.now() - new Date(ts).getTime() > OFFLINE_MS;
}

/* -------- marker logic -------- */
function updateMarkers() {
  fetch(apiAll)
    .then(r => r.json())
    .then(data => {
      // zaktualizuj lastSeenMap
      data.forEach(d => { lastSeenMap[d.drone_id] = d.timestamp; });

      // odśwież markery tylko dla aktywnych
      activeSet.forEach(id => {
        const rec = data.find(d => d.drone_id === id);
        if (!rec) return;

        const pos = [rec.lat, rec.lon];
        const offline = isOffline(id);
        const icon = (id === selectedId) ? greenIcon : (offline ? redIcon : blueIcon);

        if (!markers[id]) {
          markers[id] = L.marker(pos,{icon}).addTo(map).bindPopup(id);
        } else {
          markers[id].setLatLng(pos).setIcon(icon);
        }
      });
    });
}

/* -------- główna pętla -------- */
function refresh() {
  fetch(apiList)
    .then(r => r.json())
    .then(ids => {
      renderLists(ids);
      updateMarkers();
    })
    .catch(console.error);
}

/* -------- start -------- */
initMap();
refresh();
setInterval(refresh, 3000);
