/* ---------- ikony ---------- */
function makeIcon(url){
  return new L.Icon({
    iconUrl: url,
    shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
    iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
  });
}
const ICON = {
  active:     makeIcon("/static/images/active.png"),     // zielony
  inactive:   makeIcon("/static/images/non_active.png"), // czerwony
  detected:   makeIcon("/static/images/drone.png"),      // szary
  selected:   makeIcon("/static/images/marked.png"),     // niebieski
};

/* ---------- konfiguracja ---------- */
const API = "/api/telemetry/latest";
const ACTIVE_MS   = 5000;   // < 5 s  → aktywny
const DETECT_MS   = 10000;  // >10 s  → znika z „Wykrytych”

/* ---------- stan ---------- */
let accepted = new Set();     // drony zaakceptowane (pozostają na liście na zawsze)
let selected = null;          // kliknięty dron
let lastSeen = {};            // ID → czas w ms (Epoch)
let markers  = {};            // ID → L.marker
let map;

/* ---------- mapa ---------- */
function initMap(){
  map = L.map("map").setView([52.1,19.3],6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
              {attribution:"© OpenStreetMap"}).addTo(map);
}

/* ---------- status drona ---------- */
function statusOf(id){
  const t = lastSeen[id];
  if(!t) return accepted.has(id)? "inactive" : "gone";   // brak danych

  const age = Date.now() - t;

  if(accepted.has(id)){
    return age <= ACTIVE_MS ? "active" : "inactive";   // nigdy "gone"
  }else{
    if(age > DETECT_MS)      return "gone";
    return "detected";                                // w ciągu 10 s
  }
}

/* ---------- rysowanie list ---------- */
function renderLists(ids){
  const aDiv=document.getElementById("active-list");
  const iDiv=document.getElementById("inactive-list");
  const dDiv=document.getElementById("detected-list");

  aDiv.innerHTML=iDiv.innerHTML=dDiv.innerHTML="";

  let cntA=0,cntI=0,cntD=0;

  ids.sort().forEach(id=>{
    const st=statusOf(id);
    if(st==="gone") return;

    let parent,cls,btnTxt,btnAct;

    if(accepted.has(id)){
      if(st==="active"){ parent=aDiv; cls="active"; cntA++; }
      else              { parent=iDiv; cls="inactive"; cntI++; }

      btnTxt="Usuń";
      btnAct=()=>{ accepted.delete(id); if(selected===id)selected=null; refresh(); };
    }else{                                   // wykryty
      parent=dDiv; cls="detected"; cntD++;
      btnTxt="Akceptuj";
      btnAct=()=>{ accepted.add(id); if(!selected)selected=id; refresh(); };
    }

    const row=document.createElement("div");
    row.className=`item ${cls}${id===selected?" selected":""}`;
    row.textContent=id;

    const btn=document.createElement("button");
    btn.textContent=btnTxt;
    btn.onclick=e=>{e.stopPropagation(); btnAct();};
    row.appendChild(btn);

    row.onclick=()=>{selected=id; refresh();};

    parent.appendChild(row);
  });

  if(!cntA) aDiv.innerHTML="<em>Brak</em>";
  if(!cntI) iDiv.innerHTML="<em>Brak</em>";
  if(!cntD) dDiv.innerHTML="<em>Brak</em>";
}

/* ---------- markery ---------- */
function updateMarkers(data){
  // aktualizuj lastSeen
  data.forEach(d=>{
    lastSeen[d.drone_id]=Date.parse(d.timestamp.split(".")[0]+"Z");
  });

  const seenNow = new Set();

  // aktualizuj / twórz markery z nowych rekordów
  data.forEach(d=>{
    const id=d.drone_id, pos=[d.lat,d.lon];
    const st=statusOf(id);
    if(st==="gone") return;
    seenNow.add(id);

    let icon = (id===selected) ? ICON.selected :
               (!accepted.has(id)) ? ICON.detected :
               (st==="active") ? ICON.active : ICON.inactive;

    if(!markers[id]){
      markers[id]=L.marker(pos,{icon}).addTo(map).bindPopup(id)
                   .on("click",()=>{selected=id; refresh();});
    }else{
      markers[id].setLatLng(pos).setIcon(icon);
    }
  });

  // zaktualizuj ikony dronów zaakceptowanych, które dziś NIE przysłały pakietu
  accepted.forEach(id=>{
    if(seenNow.has(id)) return;
    const st=statusOf(id);                    // na pewno inactive
    let icon=(id===selected)?ICON.selected:ICON.inactive;

    if(!markers[id]) return;                  // może zniknął, ale accepted → nic
    markers[id].setIcon(icon);
  });

  // usuń marker tylko dla niewykrytych i niezaakceptowanych „gone”
  Object.keys(markers).forEach(id=>{
    if(statusOf(id)==="gone" && !accepted.has(id)){
      map.removeLayer(markers[id]);
      delete markers[id];
      delete lastSeen[id];
    }
  });
}

/* ---------- główny fetch ---------- */
async function refresh(){
  try{
    const res=await fetch(API);
    const data=await res.json();

    const ids=[...new Set(data.map(d=>d.drone_id)), ...accepted]; // dodaj zaakceptowane, gdyby nic nie wysłały
    updateMarkers(data);
    renderLists(ids);
  }catch(e){console.error(e);}
}

/* ---------- start ---------- */
document.addEventListener("DOMContentLoaded",()=>{
  initMap();
  refresh();
  setInterval(refresh,3000);
});
