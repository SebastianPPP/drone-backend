/* ''' GLOBALNE ZMIENNE ''' */
const socket = io({
    transports: ['websocket'],
    upgrade: false
});

let map;
let droneMarkers = {};
let missionLayer = new L.LayerGroup(); 
let drawingLayer = new L.LayerGroup(); 
let isDrawingMode = false;
let drawingMarkers = []; 
let drawingPolyline = null; 
let finalWaypoints = []; 
let missionPolyline = null; 
let selectedDroneId = null;

// Ikony
const getDroneIconHtml = (color) => `
    <div class="drone-body" style="width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; transition: transform 0.1s linear;">
        <svg viewBox="0 0 24 24" fill="${color}" stroke="white" stroke-width="1.5" style="width: 100%; height: 100%; filter: drop-shadow(0 2px 3px rgba(0,0,0,0.5));">
            <path d="M12 2L4.5 20.29C4.24 20.89 4.75 21.54 5.4 21.37L12 19.5L18.6 21.37C19.25 21.54 19.76 20.89 19.5 20.29L12 2Z" />
        </svg>
    </div>`;

function createDroneIcon(color = '#007bff') {
    return L.divIcon({ className: 'custom-drone-wrapper', html: getDroneIconHtml(color), iconSize: [30, 30], iconAnchor: [15, 15] });
}
function createWaypointIcon(number) {
    return L.divIcon({
        className: 'waypoint-marker',
        html: `<div style="background: #d63384; color: white; width: 24px; height: 24px; border-radius: 50%; border: 2px solid white; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; box-shadow: 0 2px 5px rgba(0,0,0,0.4);">${number}</div>`,
        iconSize: [24, 24], iconAnchor: [12, 12]
    });
}
const editNodeIcon = L.divIcon({ className: 'edit-node', html: '<div style="background:orange; width:12px; height:12px; border-radius:50%; border:2px solid white; box-shadow:0 1px 3px black;"></div>', iconSize: [12, 12], iconAnchor: [6, 6] });

// Inicjalizacja
document.addEventListener("DOMContentLoaded", () => {
    map = L.map('map').setView([52.2297, 21.0122], 15);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OSM' }).addTo(map);
    missionLayer.addTo(map);
    drawingLayer.addTo(map);

    document.getElementById('mission-btn').addEventListener('click', handleMainButton);
    document.getElementById('generate-path-btn').addEventListener('click', generatePath);
    document.getElementById('clear-mission-btn').addEventListener('click', clearMission);
    document.getElementById('mission-type-select').addEventListener('change', (e) => {
        updateDrawingVisuals(); toggleDensityControl(e.target.value);
    });
    map.on('click', onMapClick);

    socket.on('telemetry_update', (drones) => {
        updateMap(drones);
        updateSidebar(drones);
        if (selectedDroneId) {
            const d = drones.find(x => x.drone_id === selectedDroneId);
            if(d) updateHUD(d.roll, d.pitch, d.yaw);
        }
    });
});

// UI
function toggleDensityControl(type) {
    document.getElementById('density-control').style.display = (type === 'lawnmower') ? 'block' : 'none';
}

function handleMainButton() {
    if (finalWaypoints.length > 0 && !isDrawingMode) uploadMission();
    else if (isDrawingMode) toggleDrawingMode(false); 
    else toggleDrawingMode(true); 
}

function toggleDrawingMode(enable) {
    const btn = document.getElementById('mission-btn');
    isDrawingMode = enable;
    if (enable) {
        drawingMarkers = []; drawingLayer.clearLayers(); missionLayer.clearLayers(); finalWaypoints = []; 
        btn.innerText = "Anuluj"; btn.style.background = "#ff9800"; 
        document.getElementById('mission-info').innerText = "Rysowanie..."; document.getElementById('clear-mission-btn').disabled = false;
        toggleDensityControl(document.getElementById('mission-type-select').value);
    } else {
        btn.innerText = "Nowa misja"; btn.style.background = "#28a745"; 
        drawingLayer.clearLayers(); document.getElementById('mission-info').innerText = "Gotowe.";
    }
}

function onMapClick(e) {
    if (!isDrawingMode) return;
    const marker = L.marker(e.latlng, { draggable: true, icon: editNodeIcon }).addTo(drawingLayer);
    drawingMarkers.push(marker);
    marker.on('drag', updateDrawingVisuals);
    updateDrawingVisuals();
}

function updateDrawingVisuals() {
    if (drawingMarkers.length === 0) return;
    const latlngs = drawingMarkers.map(m => m.getLatLng());
    if (drawingPolyline) drawingLayer.removeLayer(drawingPolyline);
    const type = document.getElementById('mission-type-select').value;
    if (type === 'lawnmower' && latlngs.length > 2) drawingPolyline = L.polygon(latlngs, { color: 'orange', dashArray: '5, 10', fillOpacity: 0.2 }).addTo(drawingLayer);
    else drawingPolyline = L.polyline(latlngs, { color: 'orange', dashArray: '5, 10' }).addTo(drawingLayer);
}

function generatePath() {
    if (drawingMarkers.length < 2) { alert("Min. 2 punkty!"); return; }
    const points = drawingMarkers.map(m => [m.getLatLng().lat, m.getLatLng().lng]);
    const type = document.getElementById('mission-type-select').value;
    finalWaypoints = [];

    if (type === 'waypoints') finalWaypoints = points;
    else if (type === 'lawnmower') {
        if (points.length < 3) { alert("Min. 3 punkty!"); return; }
        const turfPoints = [...points, points[0]].map(p => [p[1], p[0]]); 
        const searchArea = turf.polygon([turfPoints]);
        const bbox = turf.bbox(searchArea);
        let dist = parseFloat(document.getElementById('scan-distance').value);
        if (isNaN(dist) || dist < 5) { dist = 5; document.getElementById('scan-distance').value = 5; }
        const step = dist / 111132; 
        let latIter = bbox[1]; let toggle = false;
        if (step <= 0.00001) return;

        while (latIter <= bbox[3]) {
            let rowPoints = [];
            for(let ln = bbox[0]; ln <= bbox[2]; ln += step/5) {
                if (turf.booleanPointInPolygon(turf.point([ln, latIter]), searchArea)) rowPoints.push([latIter, ln]);
            }
            if (rowPoints.length > 1) {
                let segment = [rowPoints[0], rowPoints[rowPoints.length - 1]];
                if (toggle) segment.reverse();
                finalWaypoints.push(...segment);
                toggle = !toggle;
            } else if (rowPoints.length === 1) finalWaypoints.push(rowPoints[0]);
            latIter += step;
        }
        if (finalWaypoints.length === 0) finalWaypoints = points;
    }
    renderEditableMission();
    isDrawingMode = false; drawingLayer.clearLayers(); 
    const btn = document.getElementById('mission-btn');
    btn.innerText = "Wgraj misję"; btn.style.background = "#007bff"; 
    document.getElementById('mission-info').innerText = `Trasa gotowa (${finalWaypoints.length} pkt).`;
}

function renderEditableMission() {
    missionLayer.clearLayers(); 
    missionPolyline = L.polyline(finalWaypoints, { color: '#d63384', weight: 4, opacity: 0.8 }).addTo(missionLayer);
    finalWaypoints.forEach((coords, index) => {
        const marker = L.marker(coords, { icon: createWaypointIcon(index + 1), draggable: true }).addTo(missionLayer);
        marker.bindTooltip(`WP ${index + 1}`, { direction: 'top' });
        marker.on('drag', (e) => {
            finalWaypoints[index] = [e.target.getLatLng().lat, e.target.getLatLng().lng];
            missionPolyline.setLatLngs(finalWaypoints);
        });
        marker.on('dragend', () => {
            const btn = document.getElementById('mission-btn');
            btn.innerText = "Aktualizuj misję"; btn.style.background = "#e0a800"; 
        });
    });
}

async function uploadMission() {
    if (!selectedDroneId) { alert("Wybierz drona!"); return; }
    const payload = { drones: { [selectedDroneId]: { mission_id: "m_"+Date.now(), waypoints: finalWaypoints, role: document.getElementById('mission-type-select').value } } };
    try {
        const res = await fetch('/api/mission/upload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (res.status === 401) location.reload(); 
        else {
             const btn = document.getElementById('mission-btn');
             btn.innerText = "Wysłano"; btn.style.background = "#28a745"; 
             setTimeout(() => { btn.innerText = "Aktualizuj w locie"; btn.style.background = "#17a2b8"; }, 2000);
        }
    } catch (e) { alert("Błąd: " + e); }
}

async function clearMission() {
    toggleDrawingMode(false); missionLayer.clearLayers(); finalWaypoints = [];
    if (selectedDroneId && confirm(`STOP dla ${selectedDroneId}?`)) {
        await fetch('/api/mission/stop', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ drones: [selectedDroneId] }) });
    }
}

// === ZMODYFIKOWANA FUNKCJA AKTUALIZACJI PASKA BOCZNEGO ===
function updateSidebar(drones) {
    const containers = {
        active: document.getElementById('active-list'),
        inactive: document.getElementById('inactive-list'),
        detected: document.getElementById('detected-list')
    };

    const incomingIds = new Set(drones.map(d => d.drone_id));
    
    document.querySelectorAll('.item').forEach(el => {
        const id = el.id.replace('item-', '');
        if (!incomingIds.has(id)) {
            el.remove();
        }
    });

    drones.forEach(d => {
        const listType = d.is_tracked ? (d.online ? 'active' : 'inactive') : 'detected';
        const targetContainer = containers[listType];
        let el = document.getElementById(`item-${d.drone_id}`);

        if (el && el.parentElement !== targetContainer) {
            targetContainer.appendChild(el); 
        }

        // Jeśli element nie istnieje, tworzymy go z nową strukturą
        if (!el) {
            el = document.createElement('div');
            el.id = `item-${d.drone_id}`;
            el.onclick = () => selectDrone(d.drone_id);
            targetContainer.appendChild(el);
            
            // --- TUTAJ JEST WYGLĄD ITEMU ---
            el.innerHTML = `
                <div class="item-content">
                    <div style="flex-grow: 1;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <strong class="d-id" style="font-size:1.1em"></strong> 
                            <span class="d-stat-dot" style="height:10px; width:10px; border-radius:50%; display:inline-block;"></span>
                        </div>
                        
                        <div style="font-size:0.85em; margin-top:4px; line-height:1.4; color:#ccc;">
                            <div>Status misji: <span class="d-mission" style="color:#fff"></span></div>
                            <div>Rola: <span class="d-role" style="color:#fff"></span></div>
                            <div>Bateria: <span class="d-bat" style="color:#fff"></span></div>
                        </div>
                    </div>
                    <button class="list-btn action-btn" style="margin-left:10px;"></button>
                </div>
            `;
            
            const btn = el.querySelector('.action-btn');
            btn.onclick = (e) => {
                e.stopPropagation();
                const isTracked = el.dataset.tracked === "true";
                if (isTracked) deleteDrone(d.drone_id);
                else addDrone(d.drone_id);
            };
        }

        el.dataset.tracked = d.is_tracked;
        el.className = `item ${listType} ${d.drone_id===selectedDroneId?'selected':''}`;

        // Aktualizacja danych w istniejącym elemencie
        el.querySelector('.d-id').innerText = d.drone_id;
        
        // Kropka statusu Online/Offline
        const dot = el.querySelector('.d-stat-dot');
        dot.style.backgroundColor = d.online ? '#2ecc71' : '#e74c3c';

        // Szczegóły: Misja, Rola, Bateria
        el.querySelector('.d-mission').innerText = d.mission_display || "brak";
        el.querySelector('.d-role').innerText = d.server_assigned_role || "brak";
        
        const batSpan = el.querySelector('.d-bat');
        batSpan.innerText = `${d.battery}%`;
        batSpan.style.color = d.battery < 20 ? '#e74c3c' : '#fff';

        // Przycisk akcji (Śmietnik / Plus)
        const btn = el.querySelector('.action-btn');
        if (d.is_tracked) {
            btn.innerText = "🗑️";
            btn.title = "Przenieś do wykrytych";
            btn.className = "list-btn btn-delete action-btn";
        } else {
            btn.innerText = "➕";
            btn.title = "Dodaj drona";
            btn.className = "list-btn btn-add action-btn";
        }
    });

    handleEmptyMessage(containers.active);
    handleEmptyMessage(containers.inactive);
    handleEmptyMessage(containers.detected);
}

function handleEmptyMessage(container) {
    const itemsCount = container.querySelectorAll('.item').length;
    let msg = container.querySelector('.empty-msg');

    if (itemsCount === 0) {
        if (!msg) {
            msg = document.createElement('div');
            msg.className = 'empty-msg';
            msg.innerHTML = '<em>Brak</em>';
            msg.style.padding = '10px';
            msg.style.color = '#888';
            container.appendChild(msg);
        }
    } else {
        if (msg) msg.remove();
    }
}

// Zarządzanie dronem
async function addDrone(id) {
    try {
        await fetch('/api/drone/add', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ drone_id: id })
        });
    } catch(e) { console.error(e); }
}

async function deleteDrone(id) {
    if(!confirm(`Przenieść drona ${id} do wykrytych?`)) return;
    try {
        const res = await fetch('/api/drone/delete', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ drone_id: id })
        });
        
        if (res.status === 200 && selectedDroneId === id) {
            selectedDroneId = null;
            document.getElementById('gauges-container').classList.add('hidden');
            missionLayer.clearLayers();
            finalWaypoints = [];
        }
    } catch (e) { console.error(e); }
}

function updateMap(drones) {
    const currentIds = drones.map(d => d.drone_id);
    for (let id in droneMarkers) {
        if (!currentIds.includes(id)) {
            map.removeLayer(droneMarkers[id]);
            delete droneMarkers[id];
        }
    }

    drones.forEach(d => {
        if (droneMarkers[d.drone_id]) {
            const marker = droneMarkers[d.drone_id];
            marker.setLatLng([d.lat, d.lon]);
            const iconElement = marker.getElement();
            if (iconElement) {
                const body = iconElement.querySelector('.drone-body');
                if (body) body.style.transform = `rotate(${d.yaw}deg)`;
            }
            marker.setOpacity(d.is_tracked ? 1.0 : 0.6);
            // Uaktualnij popup jeśli jest otwarty
            if (marker.isPopupOpen()) {
                 marker.setPopupContent(`
                    <b>${d.drone_id}</b><br>
                    Misja: ${d.mission_display || '-'}<br>
                    Rola: ${d.server_assigned_role || '-'}<br>
                    Bat: ${d.battery}%
                 `);
            }
        } else {
            const m = L.marker([d.lat, d.lon], { icon: createDroneIcon('#007bff') }).addTo(map);
            m.on('click', () => selectDrone(d.drone_id)); 
            m.bindPopup(`<b>${d.drone_id}</b>`);
            m.setOpacity(d.is_tracked ? 1.0 : 0.6);
            droneMarkers[d.drone_id] = m;
        }
    });
}

function selectDrone(id) {
    selectedDroneId = id; 
    document.getElementById('gauges-container').classList.remove('hidden');

    if (droneMarkers[id]) {
        map.flyTo(droneMarkers[id].getLatLng(), 18, {
            animate: true,
            duration: 1.5 
        });
    }
}

function updateHUD(roll, pitch, yaw) {
    const h = document.getElementById('horizon-gradient');
    const pf = 2.5; 
    let cp = Math.max(-60, Math.min(60, pitch));
    h.style.transform = `rotate(${-roll}deg) translateY(${cp * pf}px)`;
    document.getElementById('hud-roll-pitch').innerText = `R:${Math.round(roll)} P:${Math.round(pitch)}`;
    const n = document.getElementById('compass-needle-el');
    n.style.transform = `translateX(-50%) rotate(${-yaw}deg)`;
    document.getElementById('hud-yaw').innerText = `HDG:${Math.round(yaw)}`;
}