/* --- konfiguracja --- */
const apiAll  = "/api/telemetry/latest";   // wszystkie dane
const apiList = "/api/drones";             // tylko nazwy
const blueIcon = new L.Icon.Default();

/* czerwony marker (Leaflet‑colour‑markers) */
const redIcon = new L.Icon({
  iconUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x-red.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

/* --- inicjalizacja mapy --- */
const map = L.map("map").setView([52.1, 19.3], 6);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

/* --- dane runtime --- */
let markers = {};
let selectedId = null;

/* --- funkcje pomocnicze --- */
function renderSidebar(ids) {
  const listDiv = document.getElementById("drone-list");
  if (ids.length === 0) {
    listDiv.innerHTML = "<em>Brak aktywnych dronów</em>";
    return;
  }
  listDiv.innerHTML = "";
  ids.forEach((id) => {
    const item = document.createElement("div");
    item.className = "drone-item" + (id === selectedId ? " active" : "");
    item.innerText = id;
    item.onclick = () => {
      selectedId = id;
      renderSidebar(ids);
      updateMarkers();          // przerysuj markery z kolorem
      if (markers[id]) map.setView(markers[id].getLatLng(), 14);
    };
    listDiv.appendChild(item);
  });
}

function updateMarkers() {
  fetch(apiAll)
    .then((r) => r.json())
    .then((data) => {
      data.forEach((d) => {
        const { drone_id, lat, lon } = d;
        if (!lat || !lon) return;

        const pos = [lat, lon];
        if (!markers[drone_id]) {
          markers[drone_id] = L.marker(pos, {
            icon: drone_id === selectedId ? redIcon : blueIcon,
          })
            .addTo(map)
            .bindPopup(`${drone_id}`);
        } else {
          markers[drone_id].setLatLng(pos);
          markers[drone_id].setIcon(
            drone_id === selectedId ? redIcon : blueIcon
          );
        }
      });
    })
    .catch((e) => console.error(e));
}

/* --- cykliczne odświeżanie listy i pozycji --- */
function refresh() {
  fetch(apiList)
    .then((r) => r.json())
    .then((ids) => {
      if (!selectedId && ids.length) selectedId = ids[0]; // wybierz 1‑szego
      renderSidebar(ids);
      updateMarkers();
    })
    .catch((e) => console.error(e));
}

refresh();
setInterval(refresh, 4000);
