/* ---------- ikony ---------- */
const iconActive   = new L.Icon({
  iconUrl: "/static/images/active.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});
const iconInactive = new L.Icon({
  iconUrl: "/static/images/non_active.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});
const iconDetected = new L.Icon({
  iconUrl: "/static/images/drone.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});
const iconSelected = new L.Icon({
  iconUrl: "/static/images/marked.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});

/* ---------- konfiguracja ---------- */
const apiAll  = "/api/telemetry/latest";
const apiList = "/api/drones";
const OFFLINE_MS = 5000;
const DETECTED_TIMEOUT_MS = 10000;

/* ---------- stan aplikacji ---------- */
let acceptedSet = new Set();
let selectedId  = null;
let markers     = {};
let lastSeenMap = {};
let map;

/* ---------- mapa ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution:"© OpenStreetMap",
  }).addTo(map);
}

function statusOf(id) {
  const ts = lastSeenMap[id];
  if (!ts) return "gone";
  const age = Date.now() - new Date(ts).getTime();
  if (!acceptedSet.has(id)) {
    if (age > DETECTED_TIMEOUT_MS) return "gone";
    return "detected";
  }
  if (age <= OFFLINE_MS) return "active";
  return "inactive";
}

/* ---------- render list ---------- */
function renderLists(allIds) {
  const elActive   = document.getElementById("active-list");
  const elInactive = document.getElementById("inactive-list");
  const elDetected = document.getElementById("detected-list");

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
      btn.onclick = (e)=>{ e.stopPropagation(); btnHandler(); };
      div.appendChild(btn);
    }
    return div;
  };

  const activeIds = [...acceptedSet].filter(id => statusOf(id) === "active");
  elActive.innerHTML = activeIds.length ? "" : "<em>Brak</em>";
  activeIds.forEach(id => {
    elActive.appendChild(
      makeItem(
        id,"active",
        ()=>{ selectedId=id; refreshOnce(); },
        "✖","Usuń",
        ()=>{ acceptedSet.delete(id); refreshOnce(); }
      )
    );
  });

  const inactiveIds = [...acceptedSet].filter(id => statusOf(id) === "inactive");
  elInactive.innerHTML = inactiveIds.length ? "" : "<em>Brak</em>";
  inactiveIds.forEach(id => {
    elInactive.appendChild(
      makeItem(
        id,"inactive",
        ()=>{ selectedId=id; refreshOnce(); },
        "✖","Usuń",
        ()=>{ acceptedSet.delete(id); refreshOnce(); }
      )
    );
  });

  const detected = allIds.filter(id => !acceptedSet.has(id) && statusOf(id) === "detected");
  elDetected.innerHTML = detected.length ? "" : "<em>Brak</em>";
  detected.forEach(id => {
    elDetected.appendChild(
      makeItem(
        id,"detected",
        ()=>{ selectedId=id; refreshOnce(); },
        "✓","Akceptuj",
        ()=>{ acceptedSet.add(id); if (!selectedId) selectedId=id; refreshOnce(); }
      )
    );
  });
}

/* ---------- markery ---------- */
function updateMarkers(data) {
  data.forEach(d => { lastSeenMap[d.drone_id] = d.timestamp; });

  data.forEach(rec => {
    const id   = rec.drone_id;
    const pos  = [rec.lat, rec.lon];
    const st   = statusOf(id);

    let icon;
    if (id === selectedId)        icon = iconSelected;
    else if (st === "active")     icon = iconActive;
    else if (st === "inactive")   icon = iconInactive;
    else if (st === "detected")   icon = iconDetected;

    if (!markers[id]) {
      markers[id] = L.marker(pos,{icon}).addTo(map).bindPopup(id);
      markers[id].on("click", ()=>{ selectedId=id; refreshOnce(); });
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
    }
  });

  Object.keys(markers).forEach(id => {
    if (!acceptedSet.has(id) && statusOf(id) === "gone") {
      map.removeLayer(markers[id]);
      delete markers[id];
      delete lastSeenMap[id];
    }
  });
}

/* ---------- zapytania ---------- */
function refreshOnce(){
  Promise.all([
    fetch(apiList).then(r => r.json()),
    fetch(apiAll).then(r => r.json())
  ])
  .then(([ids, data]) => {
    const allIds = [...new Set([...ids, ...acceptedSet])];
    updateMarkers(data);
    renderLists(allIds);
  })
  .catch(console.error);
}

/* ---------- start + pętla ---------- */
initMap();
refreshOnce();
setInterval(refreshOnce, 3000);
