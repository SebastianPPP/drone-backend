/* ---------- ikony ---------- */
const iconActive   = new L.Icon({           // zielony – online
  iconUrl: "/static/images/active.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});
const iconInactive = new L.Icon({           // czerwony – offline
  iconUrl: "/static/images/non_active.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});
const iconDetected = new L.Icon({           // szary – niezaakceptowany
  iconUrl: "/static/images/drone.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});
const iconSelected = new L.Icon({           // niebieski – kliknięty
  iconUrl: "/static/images/marked.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
});

/* ---------- konfiguracja ---------- */
const apiAll  = "/api/telemetry/latest";
const apiList = "/api/drones";
const OFFLINE_MS = 5000;            // 5 s bez danych → nieaktywne

/* ---------- stan aplikacji ---------- */
let acceptedSet = new Set();        // drony “monitorowane” (aktywny/nieaktywny)
let selectedId  = null;             // kliknięty na liście lub mapie
let markers     = {};               // id → L.marker
let lastSeenMap = {};               // id → timestamp
let map;

/* ---------- mapa ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution:"© OpenStreetMap",
  }).addTo(map);
}

/* ---------- kategorie ---------- */
function isInactive(id){
  const ts = lastSeenMap[id];
  if (!ts) return true;
  return Date.now() - new Date(ts).getTime() > OFFLINE_MS;
}

/* ---------- render list ---------- */
function renderLists(allIds) {
  const elActive   = document.getElementById("active-list");
  const elInactive = document.getElementById("inactive-list");
  const elDetected = document.getElementById("detected-list");

  // wyrzuć z acceptedSet drony, których już nie ma
  acceptedSet.forEach(id => { if (!allIds.includes(id)) acceptedSet.delete(id); });

  /** HELPER twórz wiersz listy */
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

  /* ---- AKTYWNE ---- */
  const activeIds = [...acceptedSet].filter(id => !isInactive(id));
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

  /* ---- NIEAKTYWNE ---- */
  const inactiveIds = [...acceptedSet].filter(isInactive);
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

  /* ---- WYKRYTE ---- */
  const detected = allIds.filter(id => !acceptedSet.has(id));
  elDetected.innerHTML = detected.length ? "" : "<em>Brak</em>";
  detected.forEach(id => {
    elDetected.appendChild(
      makeItem(
        id,"detected",
        ()=>{ selectedId=id; refreshOnce(); },
        "✓","Akceptuj",
        ()=>{ acceptedSet.add(id); if(!selectedId)selectedId=id; refreshOnce(); }
      )
    );
  });
}

/* ---------- markery ---------- */
function updateMarkers(data) {
  // aktualizuj lastSeen
  data.forEach(d => { lastSeenMap[d.drone_id] = d.timestamp; });

  // przejdź po WSZYSTKICH znanych dronach
  data.forEach(rec => {
    const id   = rec.drone_id;
    const pos  = [rec.lat, rec.lon];
    const inSet = acceptedSet.has(id);
    const inactive = isInactive(id);
    let icon;

    if (id === selectedId)            icon = iconSelected;
    else if (!inSet)                  icon = iconDetected;
    else if (inactive)                icon = iconInactive;
    else                              icon = iconActive;

    if (!markers[id]) {
      markers[id] = L.marker(pos,{icon}).addTo(map).bindPopup(id);
      markers[id].on("click", ()=>{ selectedId=id; refreshOnce(); });
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
    }
  });
}

/* ---------- zapytania ---------- */
function refreshOnce(){
  Promise.all([fetch(apiList).then(r=>r.json()), fetch(apiAll).then(r=>r.json())])
    .then(([ids,data])=>{
      renderLists(ids);
      updateMarkers(data);
    })
    .catch(console.error);
}

/* ---------- start + pętla ---------- */
initMap();
refreshOnce();
setInterval(refreshOnce, 3000);
