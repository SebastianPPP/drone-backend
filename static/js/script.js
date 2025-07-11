/* ---------- ikony ---------- */
function makeIcon(url){
  return new L.Icon({
    iconUrl: url,
    shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
    iconSize:[25,41],iconAnchor:[12,41],popupAnchor:[1,-34],shadowSize:[41,41],
  });
}
const ICON = {
  active:   makeIcon("/static/images/active.png"),     // zielony
  inactive: makeIcon("/static/images/non_active.png"), // czerwony
  detected: makeIcon("/static/images/drone.png"),      // szary
  selected: makeIcon("/static/images/marked.png"),     // niebieski
};

/* ---------- konfiguracja ---------- */
const API = "/api/telemetry/latest";
const ACTIVE_MS   = 5000;   // < 5 s → aktywny
const DETECT_MS   = 10000;  // >10 s → usuwamy z wykrytych

/* ---------- stan ---------- */
let accepted = new Set();
let selected = null;
let lastSeen = {};                      // id → epoch ms
let markers  = {};                      // id → L.marker
let map;

/* ---------- helpers ---------- */
const norm = id => (id || "").trim();  // usuwa spacje, taby, \n
function statusOf(id){
  id = norm(id);
  const t = lastSeen[id];
  if(!t) return accepted.has(id)? "inactive" : "gone";
  const age = Date.now() - t;
  if(!accepted.has(id)) return age>DETECT_MS ? "gone" : "detected";
  return age<=ACTIVE_MS ? "active" : "inactive";
}

/* ---------- mapa ---------- */
function initMap(){
  map = L.map("map").setView([52.1,19.3],6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{attribution:"© OSM"}).addTo(map);
}

/* ---------- render list ---------- */
function render(ids){
  const a = document.getElementById("active-list");
  const i = document.getElementById("inactive-list");
  const d = document.getElementById("detected-list");
  a.innerHTML = i.innerHTML = d.innerHTML = "";

  const addedRow = (parent,id,cls,btnTxt,btnAct)=>{
    const row=document.createElement("div");
    row.className=`item ${cls}${id===selected?" selected":""}`;
    row.textContent=id;
    row.onclick=()=>{selected=id; refresh();};
    const b=document.createElement("button");
    b.textContent=btnTxt;
    b.onclick=e=>{e.stopPropagation();btnAct(id);} ;
    row.appendChild(b);
    parent.appendChild(row);
  };

  const seen = {a:0,i:0,d:0};
  ids.forEach(raw=>{
    const id=norm(raw);
    const st=statusOf(id);
    if(st==="gone") return;
    if(accepted.has(id)){
      if(st==="active"){ addedRow(a,id,"active","Usuń",delFromAccepted); seen.a++; }
      else { addedRow(i,id,"inactive","Usuń",delFromAccepted); seen.i++; }
    }else if(st==="detected"){ addedRow(d,id,"detected","Akceptuj",addToAccepted); seen.d++; }
  });
  if(!seen.a) a.innerHTML="<em>Brak</em>";
  if(!seen.i) i.innerHTML="<em>Brak</em>";
  if(!seen.d) d.innerHTML="<em>Brak</em>";
}
function addToAccepted(id){accepted.add(norm(id)); if(!selected) selected=norm(id); refresh();}
function delFromAccepted(id){accepted.delete(norm(id)); if(selected===norm(id)) selected=null; refresh();}

/* ---------- markery ---------- */
function updateMarkers(data){
  data.forEach(rec=>{
    const id=norm(rec.drone_id);
    const pos=[rec.lat,rec.lon];
    lastSeen[id]=Date.parse(rec.timestamp.split(".")[0]+"Z");
    const st=statusOf(id);
    let icon = (id===selected)? ICON.selected
              : st==="active"? ICON.active
              : st==="inactive"? ICON.inactive
              : ICON.detected;
    if(!markers[id]){
      markers[id]=L.marker(pos,{icon}).addTo(map).bindPopup(id)
        .on("click",()=>{selected=id; refresh();});
    }else{
      markers[id].setLatLng(pos).setIcon(icon);
    }
  });
}

/* ---------- fetch ---------- */
async function refresh(){
  try{
    const res=await fetch(API);
    const data=await res.json();
    const ids=[...new Set([...data.map(d=>norm(d.drone_id)), ...accepted])];
    updateMarkers(data);
    render(ids);
  }catch(e){console.error(e);}  
}

/* ---------- init ---------- */
document.addEventListener("DOMContentLoaded",()=>{
  initMap();
  refresh();
  setInterval(refresh,3000);
});
