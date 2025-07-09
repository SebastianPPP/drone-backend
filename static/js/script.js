const apiBase = "/api/telemetry/latest";

const map = L.map("map").setView([52.1, 19.3], 6);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

fetch(apiBase)
  .then(res => res.json())
  .then(data => {
    const status = document.getElementById("status");
    if (data.length === 0) {
      status.innerText = "Brak aktywnych dronów.";
      return;
    }
    status.innerText = "Aktywne drony:";
    data.forEach(drone => {
      const marker = L.marker([drone.lat, drone.lon])
        .addTo(map)
        .bindPopup(`<b>Dron:</b> ${drone.drone_id}<br><b>Temp:</b> ${drone.temperature ?? "?"}°C`);
    });
  })
  .catch(err => {
    document.getElementById("status").innerText = "Błąd połączenia z serwerem.";
    console.error(err);
  });
