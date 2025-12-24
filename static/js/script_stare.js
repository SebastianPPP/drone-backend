// Globalne zmienne

let map;
let droneMarkers = {}; // Przechowuje markery dronów

// Warstwy mapy
let missionLayer = new L.LayerGroup(); // Warstwa gotowej trasy 
let drawingLayer = new L.LayerGroup(); // Warstwa rysowania obszaru 

// Stan aplikacji
let isDrawingMode = false;
let drawingMarkers = []; // Markery pomarańczowe 
let drawingPolyline = null; // Obrys obszaru

let finalWaypoints = []; // Gotowa lista punktów [lat, lon] do wysłania
let missionPolyline = null; // Niebieska linia trasy

let selectedDroneId = null; // ID aktualnie śledzonego drona

// 1. Ikona Drona
const getDroneIconHtml = (color) => `
    <div class="drone-body" style="
        width: 30px; height: 30px; 
        display: flex; align-items: center; justify-content: center;
        transition: transform 0.2s linear; /* Płynny obrót */
    ">
        <svg viewBox="0 0 24 24" fill="${color}" stroke="white" stroke-width="1.5" style="width: 100%; height: 100%; filter: drop-shadow(0 2px 3px rgba(0,0,0,0.5));">
            <path d="M12 2L4.5 20.29C4.24 20.89 4.75 21.54 5.4 21.37L12 19.5L18.6 21.37C19.25 21.54 19.76 20.89 19.5 20.29L12 2Z" />
        </svg>
    </div>
`;

// Funkcja tworząca ikonę drona
function createDroneIcon(color = '#007bff') {
    return L.divIcon({
        className: 'custom-drone-wrapper', 
        html: getDroneIconHtml(color),
        iconSize: [30, 30],
        iconAnchor: [15, 15] 
    });
}

// 2. Ikona Waypointsa
function createWaypointIcon(number) {
    return L.divIcon({
        className: 'waypoint-marker',
        html: `<div style="
            background: #d63384; color: white; 
            width: 24px; height: 24px; 
            border-radius: 50%; border: 2px solid white; 
            display: flex; align-items: center; justify-content: center; 
            font-size: 12px; font-weight: bold; 
            box-shadow: 0 2px 5px rgba(0,0,0,0.4);">
            ${number}
        </div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12]
    });
}

// 3. Ikona punktu 
const editNodeIcon = L.divIcon({
    className: 'edit-node',
    html: '<div style="background:orange; width:12px; height:12px; border-radius:50%; border:2px solid white; box-shadow:0 1px 3px black;"></div>',
    iconSize: [12, 12],
    iconAnchor: [6, 6]
});


// Inicjalizacje
document.addEventListener("DOMContentLoaded", () => {
    // 1. Inicjalizacja mapy
    map = L.map('map').setView([52.2297, 21.0122], 15);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map);

    missionLayer.addTo(map);
    drawingLayer.addTo(map);

    // 2. Podpięcie zdarzeń (Listenery)
    document.getElementById('mission-btn').addEventListener('click', handleMainButton);
    document.getElementById('generate-path-btn').addEventListener('click', generatePath);
    document.getElementById('clear-mission-btn').addEventListener('click', clearMission);
    
    // Obsługa zmiany typu misji
    document.getElementById('mission-type-select').addEventListener('change', (e) => {
        updateDrawingVisuals(); 
        toggleDensityControl(e.target.value); 
    });

    map.on('click', onMapClick);

    // 3. Start pętli telemetrii
    setInterval(fetchTelemetry, 1000);
});

// Gęstość punktów dla trybu Lawnmower
function toggleDensityControl(type) {
    const ctrl = document.getElementById('density-control');
    if (type === 'lawnmower') {
        ctrl.style.display = 'block';
    } else {
        ctrl.style.display = 'none';
    }
}


// Logika dla głównego przycisku misji
function handleMainButton() {
    // SCENARIUSZ 1: Mamy gotową trasę -> Wgraj lub Aktualizuj w locie
    if (finalWaypoints.length > 0 && !isDrawingMode) {
        uploadMission();
    } 
    // SCENARIUSZ 2: Jesteśmy w trakcie rysowania -> Anuluj
    else if (isDrawingMode) {
        toggleDrawingMode(false); 
    } 
    // SCENARIUSZ 3: Stan spoczynku -> Zacznij nową misję
    else {
        toggleDrawingMode(true); 
    }
}

function toggleDrawingMode(enable) {
    const btn = document.getElementById('mission-btn');
    isDrawingMode = enable;

    if (enable) {
        // START RYSOWANIA
        drawingMarkers = [];
        drawingLayer.clearLayers();
        missionLayer.clearLayers(); 
        finalWaypoints = []; 

        btn.innerText = "Anuluj";
        btn.style.background = "#ff9800"; // Pomarańczowy
        document.getElementById('mission-info').innerText = "Klikaj na mapie, by wyznaczyć punkty obszaru/trasy.";
        document.getElementById('clear-mission-btn').disabled = false;
        
        // Upewnij się, że input metrów jest widoczny jeśli trzeba
        toggleDensityControl(document.getElementById('mission-type-select').value);
        
    } else {
        // KONIEC RYSOWANIA
        btn.innerText = "Nowa misja";
        btn.style.background = "#28a745"; 
        drawingLayer.clearLayers(); 
        document.getElementById('mission-info').innerText = "Edycja zakończona.";
    }
}

// Rysowanie
function onMapClick(e) {
    if (!isDrawingMode) return;
    const { lat, lng } = e.latlng;

    // Dodajemy marker edycji
    const marker = L.marker([lat, lng], { draggable: true, icon: editNodeIcon }).addTo(drawingLayer);
    drawingMarkers.push(marker);

    // Aktualizuj linię przy przesuwaniu
    marker.on('drag', updateDrawingVisuals);
    updateDrawingVisuals();
}

function updateDrawingVisuals() {
    if (drawingMarkers.length === 0) return;
    const latlngs = drawingMarkers.map(m => m.getLatLng());
    
    if (drawingPolyline) drawingLayer.removeLayer(drawingPolyline);

    const type = document.getElementById('mission-type-select').value;
    
    // Rysuj linię otwartą lub zamknięty wielokąt
    if (type === 'lawnmower' && latlngs.length > 2) {
        drawingPolyline = L.polygon(latlngs, { color: 'orange', dashArray: '5, 10', fillOpacity: 0.2 }).addTo(drawingLayer);
    } else {
        drawingPolyline = L.polyline(latlngs, { color: 'orange', dashArray: '5, 10' }).addTo(drawingLayer);
    }
}

// Generowanie trasy na podstawie narysowanych punktów
function generatePath() {
    if (drawingMarkers.length < 2) { alert("Min. 2 punkty!"); return; }

    const points = drawingMarkers.map(m => [m.getLatLng().lat, m.getLatLng().lng]);
    const type = document.getElementById('mission-type-select').value;
    finalWaypoints = [];

    // Waypointsy - po prostu kopiujemy punkty
    if (type === 'waypoints') {
        finalWaypoints = points;
    } 
    
    // Lawnmower (pokrycie obszaru)
    else if (type === 'lawnmower') {
        if (points.length < 3) { alert("Min. 3 punkty dla Lawnmower!"); return; }
        
        // Konfiguracja Turf.js
        const turfPoints = [...points, points[0]].map(p => [p[1], p[0]]); // [lon, lat]
        const searchArea = turf.polygon([turfPoints]);
        const bbox = turf.bbox(searchArea); // [minLon, minLat, maxLon, maxLat]

        // Odległość między liniami w metrach
        let distanceMeters = parseFloat(document.getElementById('scan-distance').value);
        if (isNaN(distanceMeters) || distanceMeters < 5) {
            alert("Minimum 5 metrów! Ustawiam 5m.");
            distanceMeters = 5;
            document.getElementById('scan-distance').value = 5;
        }

        // Przybliżenie: 1 stopień szerokości = 111,132 metrów
        const step = distanceMeters / 111132; 

        let latIter = bbox[1];
        let toggle = false;

        // Przechodzimy przez obszar w liniach poziomych
        while (latIter <= bbox[3]) {
            let rowPoints = [];
            
            // Próbkujemy linię poziomą
            for(let ln = bbox[0]; ln <= bbox[2]; ln += step/5) { // Dzielimy step na mniejsze kawałki dla precyzji wykrycia krawędzi
                if (turf.booleanPointInPolygon(turf.point([ln, latIter]), searchArea)) {
                    rowPoints.push([latIter, ln]);
                }
            }

            // OPTYMALIZACJA: Bierzemy tylko punkt wejścia i wyjścia w wierszu
            // Dron leci prosto od krawędzi do krawędzi, bez zbędnych punktów w środku pola.
            if (rowPoints.length > 1) {
                const startPoint = rowPoints[0];
                const endPoint = rowPoints[rowPoints.length - 1];
                let segment = [startPoint, endPoint];
                
                if (toggle) segment.reverse(); 
                finalWaypoints.push(...segment);
                toggle = !toggle;
            } else if (rowPoints.length === 1) {
                 finalWaypoints.push(rowPoints[0]);
            }
            
            latIter += step;
        }
        
        if (finalWaypoints.length === 0) finalWaypoints = points; // Fallback w razie błędu
    }

    // Renderujemy wynik jako edytowalne fioletowe punkty
    renderEditableMission();

    // Zamykamy tryb rysowania
    isDrawingMode = false;
    drawingLayer.clearLayers(); 
    
    const btn = document.getElementById('mission-btn');
    btn.innerText = "Wgraj misję";
    btn.style.background = "#007bff"; // Niebieski
    document.getElementById('mission-info').innerText = `Gotowe: ${finalWaypoints.length} pkt.`;
}


// Renderowanie edytowalnej misji 
function renderEditableMission() {
    missionLayer.clearLayers(); 

    // 1. Linia trasy
    missionPolyline = L.polyline(finalWaypoints, { color: '#d63384', weight: 4, opacity: 0.8 }).addTo(missionLayer);

    // 2. Markery Waypointów
    finalWaypoints.forEach((coords, index) => {
        const marker = L.marker(coords, { 
            icon: createWaypointIcon(index + 1), // Ikona z numerem
            draggable: true 
        }).addTo(missionLayer);

        marker.bindTooltip(`WP ${index + 1}`, { direction: 'top' });

        // Obsługa przesuwania punktu w locie
        marker.on('drag', (e) => {
            const newPos = e.target.getLatLng();
            finalWaypoints[index] = [newPos.lat, newPos.lng];
            missionPolyline.setLatLngs(finalWaypoints); // Aktualizuj linię natychmiast
        });

        // Po puszczeniu markera -> Zmień przycisk na "Aktualizuj"
        marker.on('dragend', () => {
            const btn = document.getElementById('mission-btn');
            btn.innerText = "Aktualizuj misję";
            btn.style.background = "#e0a800"; 
            document.getElementById('mission-info').innerText = "Trasa zmieniona! Wyślij aktualizację do drona.";
        });
    });
}

// Wysyłanie misji
async function uploadMission() {
    if (!selectedDroneId) { alert("Wybierz drona z listy!"); return; }
    
    const payload = {
        drones: {
            [selectedDroneId]: {
                mission_id: "m_" + Date.now(),
                waypoints: finalWaypoints,
                role: document.getElementById('mission-type-select').value
            }
        }
    };

    try {
        const res = await fetch('/api/mission/upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.status === 401) location.reload(); 
        else {
             const btn = document.getElementById('mission-btn');
             btn.innerText = "Misja aktywna";
             btn.style.background = "#28a745"; 
             setTimeout(() => {
                 btn.innerText = "Aktualizuj w locie";
                 btn.style.background = "#17a2b8"; 
             }, 2000);
             document.getElementById('mission-info').innerText = "Wysłano pomyślnie.";
        }
    } catch (e) { alert("Błąd połączenia: " + e); }
}

// Czyszczenie misji
async function clearMission() {
    toggleDrawingMode(false); 
    missionLayer.clearLayers();
    finalWaypoints = [];
    document.getElementById('mission-info').innerText = "";

    if (selectedDroneId && confirm(`Wysłać STOP do ${selectedDroneId}?`)) {
        await fetch('/api/mission/stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ drones: [selectedDroneId] })
        });
    }
}

// Pobieranie telemetrii i aktualizacja UI
async function fetchTelemetry() {
    try {
        const response = await fetch('/api/telemetry');
        const drones = await response.json();
        updateMap(drones);
        updateSidebar(drones);
        
        // Jeśli mamy wybranego drona, aktualizujemy HUD (kompasy itp.)
        if (selectedDroneId) {
            const d = drones.find(x => x.drone_id === selectedDroneId);
            if(d) updateHUD(d.roll, d.pitch, d.yaw);
        }
    } catch (e) { console.error(e); }
}

function updateMap(drones) {
    drones.forEach(d => {
        if (droneMarkers[d.drone_id]) {
            const marker = droneMarkers[d.drone_id];
            marker.setLatLng([d.lat, d.lon]);

            // Aktualizacja obrotu drona (ikona)
            const iconElement = marker.getElement();
            if (iconElement) {
                const body = iconElement.querySelector('.drone-body');
                if (body) {
                    body.style.transform = `rotate(${d.yaw}deg)`;
                }
            }
            
        } else {
            // Tworzenie nowego markera drona
            const m = L.marker([d.lat, d.lon], { icon: createDroneIcon('#007bff') }).addTo(map);
            m.on('click', () => selectDrone(d.drone_id));
            m.bindPopup(`<b>${d.drone_id}</b>`);
            droneMarkers[d.drone_id] = m;
        }
    });
}

function updateSidebar(drones) {
    const act = document.getElementById('active-list');
    const inact = document.getElementById('inactive-list');
    act.innerHTML=''; inact.innerHTML='';
    if(drones.length===0) { act.innerHTML='<em>Szukanie...</em>'; return; }

    drones.forEach(d => {
        const el = document.createElement('div');
        el.className = `item ${d.online?'active':'inactive'} ${d.drone_id===selectedDroneId?'selected':''}`;
        el.innerHTML = `<strong>${d.drone_id}</strong> <small>(${d.online?'On':'Off'})</small><br>Bat:${d.battery}% | ${d.server_assigned_role}`;
        el.onclick = () => selectDrone(d.drone_id);
        if(d.online) act.appendChild(el); else inact.appendChild(el);
    });
}

function selectDrone(id) {
    selectedDroneId = id;
    document.getElementById('gauges-container').classList.remove('hidden');
    fetchTelemetry();
}

function updateHUD(roll, pitch, yaw) {
    // Sztuczny horyzont
    const h = document.getElementById('horizon-gradient');
    const pf = 2.5; 
    let cp = Math.max(-60, Math.min(60, pitch));
    h.style.transform = `rotate(${-roll}deg) translateY(${cp * pf}px)`;
    document.getElementById('hud-roll-pitch').innerText = `R: ${Math.round(roll)}° P: ${Math.round(pitch)}°`;

    // Kompas
    const n = document.getElementById('compass-needle-el');
    n.style.transform = `translateX(-50%) rotate(${-yaw}deg)`;
    document.getElementById('hud-yaw').innerText = `HDG: ${Math.round(yaw)}°`;
}