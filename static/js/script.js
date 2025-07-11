/* ---------- ikony ---------- */
function makeIcon(url) {
  return new L.Icon({
    iconUrl: url,
    shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
    iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
  });
}
const ICON = {
  active:     makeIcon("/static/images/active.png"),   // zielony
  inactive:   makeIcon("/static/images/non_active.png"), // czerwony
  detected:   makeIcon("/static/images/drone.png"),    // szary
  selected:   makeIcon("/static/images/marked.png"),   // niebieski
};

/* ---------- konfiguracja ---------- */
const API = "/api/telemetry/latest";
const ACTIVE_MS   = 5000;   // < 5 s  → aktywny
const DETECT_MS   = 10000;  // >10 s → wykryty znika

/* ---------- stan ---------- */
let accepted = new Set();      // zaakceptowane ID
let selected = null;           // aktualnie kliknięte ID
let lastSeen = {};             // ID → ms od epoch
let markers  = {};             // ID → L.marker
let map;

/* ---------- mapa ---------- */
function initMap() {
  map = L.map("map").setView([52.1, 19.3], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
              {attribution:"© OpenStreetMap"}).addTo(map);
}

/* ---------- status drona ---------- */
function statusOf(id){
  const t = lastSeen[id];
  if (!t) return "gone";
  const ago = Date.now() - t;
  if (ago > DETECT_MS)      return "gone";      // usuń
  if (ago > ACTIVE_MS)      return "inactive";  // w accepted → nieaktywny
  return "active";                              // w accepted → aktywny
}

/* ---------- render list ---------- */
function render(allIds){
  const aDiv = document.getElementById("active-list");
  const iDiv = document.getElementById("inactive-list");
  const dDiv = document.getElementById("detected-list");

  // wyczyść
  [aDiv,iDiv,dDiv].forEach(div=>div.innerHTML="");

  // posortowane ID dla powtarzalności
  allIds.sort();

  let anyA=0, anyI=0, anyD=0;

  allIds.forEach(id=>{
    const st = statusOf(id);
    let divParent, cls, btnTxt, btnHandler;

    if (accepted.has(id)) {
      if (st==="active"){   divParent=aDiv; cls="active";   anyA++; }
      else if(st==="inactive"){ divParent=iDiv; cls="inactive"; anyI++; }
      else { accepted.delete(id); return; }           // gone
      btnTxt="Usuń"; btnHandler=()=>{accepted.delete(id); refresh();};
    } else { // niezaakceptowany
      if (st==="gone") return;                        // zbyt stary → ignoruj
      divParent=dDiv; cls="detected"; anyD++;
      btnTxt="Akceptuj"; btnHandler=()=>{accepted.add(id); refresh();};
    }

    const row=document.createElement("div");
    row.className=`item ${cls}${id===selected?" selected":""}`;
    row.textContent=id;
    row.onclick=()=>{selected=id; refresh();};

    const btn=document.createElement("button");
    btn.textContent=btnTxt;
    btn.onclick=e=>{e.stopPropagation(); btnHandler();};
    row.appendChild(btn);

    divParent.appendChild(row);
  });

  if(!anyA) aDiv.innerHTML="<em>Brak</em>";
  if(!anyI) iDiv.innerHTML="<em>Brak</em>";
  if(!anyD) dDiv.innerHTML="<em>Brak</em>";
}

/* ---------- markery ---------- */
function updateMarkers(data){
  data.forEach(d=>{
    const id=d.drone_id;
    const pos=[d.lat,d.lon];

    // timestamp → ms (obcinamy mikrosekundy: 'YYYY-MM-DDTHH:MM:SS')
    const tsMs = Date.parse(d.timestamp.split(".")[0]+"Z");
    lastSeen[id]=tsMs;

    const st = statusOf(id);
    if(st==="gone") return;

    const icon = (id===selected)       ? ICON.selected :
                 (!accepted.has(id))   ? ICON.detected :
                 (st==="inactive")     ? ICON.inactive :
                                         ICON.active;

    if(!markers[id]){
      markers[id]=L.marker(pos,{icon}).addTo(map).bindPopup(id)
                   .on("click",()=>{selected=id; refresh();});
    } else {
      markers[id].setLatLng(pos).setIcon(icon);
    }
  });

  /* usuwamy markery dronów, których nie ma w lastSeen (przestarzałe) */
  Object.keys(markers).forEach(id=>{
    if(statusOf(id)==="gone"){
      map.removeLayer(markers[id]);
      delete markers[id];
      delete lastSeen[id];
      accepted.delete(id);
      if(selected===id) selected=null;
    }
  });
}

/* ---------- główny fetch ---------- */
async function refresh(){
  try{
    const res=await fetch(API);
    const data=await res.json();
    console.log("Odebrano rekordów:", data.length);

    const ids=[...new Set(data.map(d=>d.drone_id))];
    updateMarkers(data);
    render(ids);
  }catch(e){console.error(e);}
}

/* ---------- start ---------- */
document.addEventListener("DOMContentLoaded",()=>{
  initMap();
  refresh();
  setInterval(refresh, 3000);
});
