// --- i18n Localization Dictionary ---
const currentLang = localStorage.getItem('cdc_lang') || 'en'; 

const i18n = {
    en: {
        radar: "TACTICAL RADAR",
        altitude: "ALTITUDE",
        unmapped: "Unmapped / Plains",
        speed: "SPEED",
        status: "STATUS",
        personnel: "PERSONNEL",
        btn_move: "Move Order",
        btn_stop: "Halt",
        sys_ready: "System Ready. Awaiting orders."
    },
    zh: {
        radar: "战区遥测雷达",
        altitude: "实时海拔",
        unmapped: "未测绘区 / 平原",
        speed: "行军速度",
        status: "当前建制状态",
        personnel: "兵力存活",
        btn_move: "📍下达机动指令",
        btn_stop: "🛑紧急停止",
        sys_ready: "系统就绪。等待指挥官指令。"
    }
};

function t(key) {
    return i18n[currentLang][key] || key;
}

// 🟢 1. Global Variable Registration
let map;
let geojsonLayer = null;
let pathLine = null;
let draftLine = null;
let draftMarker = null;
let draftedTarget = null;
window.unitMarkersMap = {};

let draftedWaypoints = [];
let draftMarkers = [];
let roadLayer = null;
let roadsVisible = false;

let globalWeapons = {};
let globalBattalions = {};
let isDeploying = false;
let selectedUnitId = null;
let selectedUnitLon = null;
let selectedUnitLat = null;
let provinceInfluence = {};
let pendingAction = "move";
let lastLogCount = 0;
let heartbeatInterval = null;

// 🟢 Dynamic Faction Palette (Universal Color Assigner)
const factionPalette = ['#ff7b72', '#7ee787', '#58a6ff', '#e3b341', '#d2a8ff', '#ff94c2', '#a5d6ff'];
let factionColorMap = {};
let paletteIndex = 0;

function getFactionColor(faction) {
    if (!faction) return '#8b949e';
    if (!factionColorMap[faction]) {
        factionColorMap[faction] = factionPalette[paletteIndex % factionPalette.length];
        paletteIndex++;
    }
    return factionColorMap[faction];
}

const mapLayers = {
    'clean': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', { maxZoom: 12 }),
    'topo': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', { maxZoom: 12 }),
    'admin': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 12 })
};
let currentMapMode = 'clean';

// 🟢 2. System Boot: Scan and Mount DLCs
window.onload = function() {
    map = L.map('map', { zoomControl: false, attributionControl: false, doubleClickZoom: false }).setView([0, 0], 2);
    mapLayers['clean'].addTo(map); 
    L.control.scale({ position: 'bottomleft', metric: true, imperial: false }).addTo(map);

    fetch('/api/list_dlcs').then(r => r.json()).then(dlcs => {
        const container = document.getElementById('dlc-list-container');
        container.innerHTML = '';
        if(dlcs.length === 0) {
            container.innerHTML = `<div style="color:#ff7b72; text-align:center;">No DLC detected. Please place modules in the dlc/ directory.</div>`;
            return;
        }
        dlcs.forEach(dlc => {
            container.innerHTML += `
                <div style="border:1px solid #30363d; padding:15px; background:rgba(0,0,0,0.5); cursor:pointer; margin-bottom:10px;" 
                     onmouseover="this.style.borderColor='#58a6ff'" onmouseout="this.style.borderColor='#30363d'"
                     onclick="mountDLC('${dlc.id}')">
                    <div style="color:#7ee787; font-size:18px; font-weight:bold;">📂 ${dlc.name}</div>
                    <div style="color:#8b949e; font-size:12px;">${dlc.desc}</div>
                </div>
            `;
        });
    });
};

function mountDLC(dlcId) {
    document.getElementById('dlc-list-container').innerHTML = `<div style="color:#e3b341; text-align:center; padding:20px;">[ MOUNTING CORE MODULES... ]<br>Loading campaign data...</div>`;
    
    // Clear the palette for the new campaign
    factionColorMap = {}; 
    paletteIndex = 0;

    fetch('/api/mount_dlc', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({dlc_id: dlcId})
    }).then(r => r.json()).then(res => {
        if(res.status === 'ok') {
            document.getElementById('bootloader-screen').style.display = 'none';
            map.setView([res.config.center[0], res.config.center[1]], res.config.center[2] || 6);
            document.title = "CDC Command Radar - " + res.config.name;

            fetch('/api/registry').then(r => r.json()).then(data => {
                globalWeapons = data.weapons;
                globalBattalions = data.battalions;
                updateDeployUI();
            });

            fetch('/geojson').then(r => r.json()).then(data => {
                if (Object.keys(data).length > 0) geojsonLayer = L.geoJSON(data, { style: styleProvince }).addTo(map);
            });

            fetchState();
            heartbeatInterval = setInterval(fetchState, 1000);
            setupMapClicks();
        }
    });
}

function updateDeployUI() {
    const wSelect = document.getElementById('dep-weapon');
    wSelect.innerHTML = '';
    for (const [key, w] of Object.entries(globalWeapons)) {
        wSelect.innerHTML += `<option value="${key}">${w.name} - Range ${w.range}km</option>`;
    }
    const cGrid = document.getElementById('dep-comp-grid');
    cGrid.innerHTML = '';
    for (const [key, b] of Object.entries(globalBattalions)) {
        const size = b.size || 500; 
        cGrid.innerHTML += `<div class="comp-item" title="Base Complement: ${size} personnel"><label>${b.name || key}</label><input type="number" id="dep-${key}" value="0" min="0" oninput="calcDeployStats()" data-size="${size}"></div>`;
    }
    if(document.getElementById('dep-inf')) document.getElementById('dep-inf').value = 3;
    if(document.getElementById('dep-arm')) document.getElementById('dep-arm').value = 1;
    if(document.getElementById('dep-art')) document.getElementById('dep-art').value = 1;
    calcDeployStats();
}

// 🟢 3. Core Radar and Interaction Logic
function switchMapMode(mode) {
    if (mode === currentMapMode) return;
    map.removeLayer(mapLayers[currentMapMode]);
    mapLayers[mode].addTo(map);
    currentMapMode = mode;
    ['clean', 'topo', 'admin'].forEach(m => document.getElementById('btn-view-' + m).classList.remove('active'));
    document.getElementById('btn-view-' + mode).classList.add('active');
}

function toggleHistoricRoads() {
    roadsVisible = !roadsVisible;
    const btn = document.getElementById('btn-toggle-roads');
    if (!roadsVisible) {
        if (roadLayer) map.removeLayer(roadLayer);
        btn.classList.remove('active'); btn.style.borderColor = ""; btn.style.color = ""; return;
    }
    btn.classList.add('active'); btn.style.borderColor = "#ff4444"; btn.style.color = "#ff7b72"; btn.innerHTML = "⏳ Scanning...";
    fetch('/api/roads_overlay').then(r => r.json()).then(data => {
        if (roadLayer) map.removeLayer(roadLayer);
        roadLayer = L.geoJSON(data, { pointToLayer: function (feature, latlng) { return L.circleMarker(latlng, { radius: 1, fillColor: "#ff0000", color: "#ff0000", weight: 1, opacity: 0.6, fillOpacity: 0.8 }); } }).addTo(map);
        btn.innerHTML = "🛣️ Roads"; 
    }).catch(err => { btn.innerHTML = "❌ Load Failed"; roadsVisible = false; });
}

function toggleDeployPanel() {
    const panel = document.getElementById('deploy-panel');
    if (panel.style.display === 'none' || panel.style.display === '') {
        panel.style.display = 'block'; calcDeployStats();
    } else {
        panel.style.display = 'none'; isDeploying = false; document.getElementById('targeting-alert').style.display = 'none';
    }
}

function calcDeployStats() {
    let totalPop = 0;
    for (const key of Object.keys(globalBattalions)) {
        const input = document.getElementById(`dep-${key}`);
        if (input) { totalPop += (parseInt(input.value) || 0) * (parseInt(input.dataset.size) || 500); }
    }
    document.getElementById('dep-pop-display').innerText = totalPop + " Personnel";
    document.getElementById('dep-personnel').value = totalPop || 100;
}

function enableDeployTargeting() {
    isDeploying = true;
    document.getElementById('targeting-alert').style.display = "block";
    document.getElementById('targeting-alert').innerText = `[ AIRDROP INITIATED ] Click on the map to deploy armed forces...`;
}

function setTargetingMode(actionStr) {
    pendingAction = actionStr; clearDraft(); pendingAction = actionStr; 
    document.getElementById('targeting-alert').style.display = "block";
    document.getElementById('targeting-alert').innerText = `[ MISSION PROTOCOL EXCL ] AWAITING TARGET COORDINATES FOR: ${actionStr.toUpperCase()}`;
}

function setupMapClicks() {
    map.on('click', function(e) {
        if (isDeploying) {
            let dynamicComp = {};
            for (const key of Object.keys(globalBattalions)) {
                const input = document.getElementById(`dep-${key}`);
                if (input && parseInt(input.value) > 0) dynamicComp[key] = parseInt(input.value);
            }
            const data = { 
                id: "unit_" + Math.floor(Math.random() * 1000000), name: document.getElementById('dep-name').value, 
                faction: document.getElementById('dep-faction').value, personnel: parseFloat(document.getElementById('dep-personnel').value), 
                equipment_level: 1.0, lon: e.latlng.lng, lat: e.latlng.lat, unit_type: "ARMY", composition: dynamicComp, primary_weapon: document.getElementById('dep-weapon').value 
            };
            fetch('/api/edit_unit', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) }).then(r => r.json()).then(res => {
                if (res.status === 'ok') { alert("✅ Forces successfully airdropped!"); toggleDeployPanel(); fetchState(); } else { alert("HQ Rejected: " + res.msg); }
            });
            return; 
        }

        if (!selectedUnitId) return;

        const tLat = e.latlng.lat; const tLon = e.latlng.lng;
        
        if (pendingAction === 'route') draftedWaypoints.push({lon: tLon, lat: tLat});
        else draftedWaypoints = [{lon: tLon, lat: tLat}]; 
        
        draftMarkers.forEach(m => map.removeLayer(m)); draftMarkers = [];
        if (draftLine) map.removeLayer(draftLine);

        const latlngs = [[selectedUnitLat, selectedUnitLon]];
        const iconHtml = pendingAction === 'attack' ? '🎯' : (pendingAction === 'bombard' ? '💥' : '📍');
        const lineColor = pendingAction === 'attack' ? '#d97706' : (pendingAction === 'route' ? '#d2a8ff' : '#58a6ff');

        draftedWaypoints.forEach((wp, index) => {
            latlngs.push([wp.lat, wp.lon]);
            let htmlText = pendingAction === 'route' ? `<div style="color:${lineColor}; background:rgba(0,0,0,0.7); border:1px solid ${lineColor}; border-radius:50%; width:16px; height:16px; line-height:16px; text-align:center; font-size:10px;">${index+1}</div>` : `<span style="color:${lineColor}; text-shadow:0 0 5px #000;">${iconHtml}</span>`;
            const m = L.marker([wp.lat, wp.lon], {icon: L.divIcon({className: 'mil-icon', html: htmlText, iconSize: [20,20], iconAnchor: [10,10]})}).addTo(map);
            draftMarkers.push(m);
        });

        draftLine = L.polyline(latlngs, {color: lineColor, dashArray: '5,5', weight: 2}).addTo(map);

        document.getElementById('confirmation-panel').style.display = "block";
        let typeStr = pendingAction === 'attack' ? "ATTACK (Assault Advance)" : (pendingAction === 'route' ? `ROUTE (Multi-stage Tactical Route, ${draftedWaypoints.length} stops)` : (pendingAction === 'bombard' ? "BOMBARD (Long-range Fire Mission)" : (pendingAction === 'airstrike' ? "AIRSTRIKE (Close Air Support)" : "MOVE (Direct Maneuver)")));
        document.getElementById('draft-type').innerText = typeStr;
        let coordsText = pendingAction === 'route' ? `DEST LON: ${tLon.toFixed(4)} | LAT: ${tLat.toFixed(4)}` : `LON: ${tLon.toFixed(4)} | LAT: ${tLat.toFixed(4)}`;
        document.getElementById('draft-coords').innerHTML = `${coordsText}<br><span style="color:#e3b341; font-size:12px;">Scanning destination topography...</span>`;
        
        fetch(`/api/terrain?lon=${tLon}&lat=${tLat}`).then(r => r.json()).then(res => {
            if(res.status === 'ok') document.getElementById('draft-coords').innerHTML = `${coordsText}<br><span style="color:#8b949e; font-size:12px;">Dest. Topography: ${res.complexity > 0.6 ? '🏔️ Mountains' : (res.complexity > 0.3 ? '⛰️ Hills' : '🛣️ Plains')} (Drag: ${res.complexity})</span>`;
        });
    });
}

function executeDraftedCommand() {
    if (!selectedUnitId || draftedWaypoints.length === 0) return;
    const payload = { command: `${pendingAction} ${selectedUnitId} ${draftedWaypoints[0].lon} ${draftedWaypoints[0].lat}`, waypoints: draftedWaypoints };
    fetch('/api/command', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) }).then(r => r.json()).then(res => {
        if (res.status === "ok") fetchState(); else alert("Command rejected: " + res.msg); clearDraft();
    });
}

function clearDraft() {
    if (draftLine) map.removeLayer(draftLine);
    if (draftMarkers) draftMarkers.forEach(m => map.removeLayer(m));
    draftMarkers = []; draftedWaypoints = []; pendingAction = "move";
    document.getElementById('confirmation-panel').style.display = "none"; document.getElementById('targeting-alert').style.display = "none";
}

function sendCommand(cmdStr) { fetch('/api/command', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({command: cmdStr}) }); }

function deselectUnit() { selectedUnitId = null; selectedUnitLon = null; selectedUnitLat = null; clearDraft(); if (pathLine) map.removeLayer(pathLine); document.getElementById('unit-info').innerHTML = `<div style="color: #8b949e; font-style: italic; text-align: center; padding: 30px 0;">[ RADAR SCANNING ]<br>Awaiting Commander to select a target...</div>`; fetchState(); }

function getProvinceColor(influence) {
    if (!influence) return 'transparent';
    if (influence >= 50) return '#ff4444'; if (influence > 0) return '#a80000';   
    if (influence <= -50) return '#44ff44'; if (influence < 0) return '#00a800'; return 'transparent';
}

function styleProvince(feature) {
    const provName = feature.properties.shapeName || feature.properties.ADM1_EN;
    const infl = provinceInfluence[provName] || 0;
    return { fillColor: getProvinceColor(infl), weight: 1, opacity: 0.3, color: '#1f6feb', fillOpacity: (Math.abs(infl) / 100) * 0.35 };
}

function getUnitIcon(u) {
    if (u.unit_type === "AIR_FORCE") return "✈️"; if (u.unit_type === "ARTILLERY") return "🎯";
    if (u.composition) { if (u.composition.eng > 0) return "🌉"; if (u.composition.arm > 0) return "🚜"; if (u.composition.sf > 0)  return "🥷"; }
    return "🪖";
}

function fetchState() {
    fetch('/api/state').then(r => r.json()).then(data => {
        if(data.status === "unmounted") return;
        const pad = (n) => (n||0).toString().padStart(2, '0');
        document.getElementById('time-display').innerText = `D${pad(data.time.day)} ${pad(data.time.hour)}:${pad(data.time.minute)}:${pad(data.time.second)}`;
        const statusSpan = document.getElementById('pause-status');
        if (data.time.paused) { statusSpan.innerText = '[ PAUSED ]'; statusSpan.style.color = '#ff7b72'; } 
        else { statusSpan.innerText = `[ RUNNING ${data.time.multiplier}X ]`; statusSpan.style.color = '#7ee787'; }

        provinceInfluence = data.provinces; if (geojsonLayer) geojsonLayer.setStyle(styleProvince);

        updateIntelFeed(data.latest_logs); refreshUnitsSmoothly(data.units);

        if (selectedUnitId && data.units[selectedUnitId]) {
            const u = data.units[selectedUnitId]; selectedUnitLon = u.lon; selectedUnitLat = u.lat; updateTacticalHUD(u);
            if (pathLine) map.removeLayer(pathLine);
            if (u.waypoints && u.waypoints.length > 0) {
                const latlngs = u.waypoints.map(wp => [wp[1], wp[0]]); latlngs.unshift([u.lat, u.lon]); 
                pathLine = L.polyline(latlngs, { color: u.is_attack_move ? '#d97706' : '#58a6ff', dashArray: '5,5', weight: 2, opacity: 0.8 }).addTo(map);
            }
        } else if (selectedUnitId) { selectedUnitId = null; clearDraft(); document.getElementById('unit-info').innerHTML = `<div style="color: #ff7b72; font-weight: bold; text-align: center; padding: 30px 0;">[ SIGNAL LOST ]</div>`; if (pathLine) map.removeLayer(pathLine); }
    });
}

function refreshUnitsSmoothly(unitsData) {
    const currentIds = new Set(Object.keys(unitsData));
    for (const uid in window.unitMarkersMap) {
        if (!currentIds.has(uid) || (unitsData[uid] && unitsData[uid].personnel <= 0)) {
            map.removeLayer(window.unitMarkersMap[uid].marker); if (window.unitMarkersMap[uid].circle) map.removeLayer(window.unitMarkersMap[uid].circle); delete window.unitMarkersMap[uid];
        }
    }
    
    for (const [uid, u] of Object.entries(unitsData)) {
        if (u.personnel <= 0) continue;
        
        // 🟢 Assign Dynamic Colors! 
        const fColor = getFactionColor(u.faction);
        const isSelected = (uid === selectedUnitId);
        
        // Render icon with dynamic inline styles instead of fixed CSS classes
        const dynamicIconHtml = `<div style="color:${fColor};">${getUnitIcon(u)}</div>`;
        
        if (window.unitMarkersMap[uid]) {
            const record = window.unitMarkersMap[uid];
            if (record.lastStance !== u.stance || record.wasSelected !== isSelected) {
                record.marker.setIcon(L.divIcon({ className: `mil-icon ${isSelected ? 'selected-unit' : ''}`, html: dynamicIconHtml, iconSize: [26, 26], iconAnchor: [13, 13] }));
                record.lastStance = u.stance; record.wasSelected = isSelected;
            }
            record.marker.setLatLng([parseFloat(u.lat), parseFloat(u.lon)]); 
            record.circle.setLatLng([parseFloat(u.lat), parseFloat(u.lon)]); 
            record.circle.setRadius((u.radius || 0) * 1000);
            record.circle.setStyle({ color: fColor, fillColor: fColor }); // Update circle color just in case
        } else {
            const marker = L.marker([parseFloat(u.lat), parseFloat(u.lon)], { icon: L.divIcon({ className: `mil-icon ${isSelected ? 'selected-unit' : ''}`, html: dynamicIconHtml, iconSize: [26, 26], iconAnchor: [13, 13] }) }).addTo(map);
            const circle = L.circle([parseFloat(u.lat), parseFloat(u.lon)], { color: fColor, fillColor: fColor, fillOpacity: 0.05, weight: 1, radius: (u.radius || 0) * 1000 }).addTo(map);
            marker.on('click', (e) => { L.DomEvent.stopPropagation(e); if (selectedUnitId !== null && selectedUnitId !== uid) return; selectedUnitId = uid; selectedUnitLon = u.lon; selectedUnitLat = u.lat; clearDraft(); pendingAction = "move"; document.getElementById('targeting-alert').style.display = "none"; fetchState(); });
            window.unitMarkersMap[uid] = { marker: marker, circle: circle, lastStance: u.stance, wasSelected: isSelected };
        }
    }
}

function updateIntelFeed(logs) {
    if (!logs || logs.length === 0) return;
    const container = document.getElementById('logs-container');
    if (logs.length !== lastLogCount || logs[logs.length-1].message !== container.dataset.lastMsg) {
        container.innerHTML = logs.slice().reverse().map(log => `<div class="log-entry ${log.type === "combat" ? "log-combat" : (log.type === "move" ? "log-move" : "log-system")}">${log.message}</div>`).join('');
        container.dataset.lastMsg = logs[logs.length-1].message; lastLogCount = logs.length;
    }
}

function updateTacticalHUD(u) {
    const compStr = Object.entries(u.composition || {}).filter(([k,v])=>v>0).map(([k,v]) => `${k}:${v}`).join(' | ');
    let weaponPanel = u.unit_type === "ARTILLERY" ? `<button class="cmd-btn cmd-warn" onclick="setTargetingMode('bombard')">🎯 Lock Fire Mission Coords</button>` : (u.unit_type === "AIR_FORCE" ? `<button class="cmd-btn cmd-warn" onclick="setTargetingMode('airstrike')">✈️ Authorize Strike Vector</button>` : "");
    const getStanceClass = (s) => u.stance === s ? "cmd-btn active" : "cmd-btn";
    
    // 🟢 Dynamic HUD Color Based on Palette
    const uColor = getFactionColor(u.faction);

    document.getElementById('unit-info').innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #1f6feb; padding-bottom: 5px;">
            <span style="color:#fff; font-size:15px; font-weight:bold;">${u.name}</span><button class="cmd-btn cmd-danger" style="padding: 3px 6px;" onclick="deselectUnit()">❌ Release</button>
        </div>
        <div class="data-row"><span class="data-label">Faction:</span> <span style="color:${uColor}">${u.faction}</span></div>
        <div class="data-row"><span class="data-label">Status:</span> <span style="color:#58a6ff; font-weight:bold;">${u.status}</span></div>
        <div class="data-row"><span class="data-label">Strength:</span> ${Math.floor(u.personnel)} Pers.</div>
        <div class="telemetry-box">
            <div class="telemetry-row"><span>LON: ${parseFloat(u.lon).toFixed(4)}</span><span>LAT: ${parseFloat(u.lat).toFixed(4)}</span><span>SPD: ${u.speed.toFixed(1)} km/h</span></div>
            <div style="text-align:center; border-top:1px dashed #58a6ff; padding-top:5px; margin-top:3px;">Real-time Altitude: <span style="color:#fff; font-size:14px; font-weight:bold;">${Math.floor(u.altitude || 0)}</span> m</div>
        </div>
        <div class="data-row"><span class="data-label">Def. Radius:</span> <span style="color:#7ee787; font-weight:bold;">${(u.radius || 0).toFixed(2)} km</span></div>
        <div class="data-row"><span class="data-label">OOB:</span> <span style="color:#a5d6ff">${compStr || 'Non-Combat Unit'}</span></div>
        <div class="data-row"><span class="data-label">Primary Arm:</span> <span style="color:#e3b341; font-weight:bold;">${u.weapon_name || 'Standard Arms'}</span></div>
        
        <div class="panel-title" style="margin-top: 15px;">⚡ Rules of Engagement (ROE)</div>
        <div style="margin-bottom: 5px; display:flex; gap:5px;">
            <button class="${getStanceClass('AGGRESSIVE')}" style="flex:1" onclick="sendCommand('stance ${u.id} AGGRESSIVE')">⚔️ Aggressive</button>
            <button class="${getStanceClass('DEFENSIVE')}" style="flex:1" onclick="sendCommand('stance ${u.id} DEFENSIVE')">🛡️ Defensive</button>
            <button class="${getStanceClass('STEALTH')}" style="flex:1" onclick="sendCommand('stance ${u.id} STEALTH')">🥷 Stealth</button>
        </div>
        <div class="panel-title" style="margin-top: 15px;">📍 Command Console</div>
        <div style="margin-bottom: 10px; display:flex; gap:5px;">
            <button class="cmd-btn" style="flex:1; border-color:#d97706; color:#e3b341;" onclick="setTargetingMode('attack')">⚔️ Attack</button>
            <button class="cmd-btn" style="flex:1; border-color:#58a6ff; color:#a5d6ff;" onclick="setTargetingMode('move')">📍 Move</button>
            <button class="cmd-btn" style="flex:1; border-color:#d2a8ff; color:#d2a8ff;" onclick="setTargetingMode('route')">🗺️ Route</button>
        </div>
        <div style="text-align:center;">${weaponPanel}</div>
    `;
}
// ==========================================
// IN-GAME EDITOR (ZEUS CONSOLE) LOGIC
// ==========================================

function toggleAdminConsole() {
    const panel = document.getElementById('admin-console');
    panel.style.display = (panel.style.display === 'none' || panel.style.display === '') ? 'block' : 'none';
}

// 💉 Inject Buff/Debuff
function applyAdminModifier() {
    if (!selectedUnitId) {
        alert("Zeus Error: No unit selected on radar!");
        return;
    }
    
    const type = document.getElementById('admin-mod-type').value;
    const val = parseFloat(document.getElementById('admin-mod-val').value);
    const dur = parseFloat(document.getElementById('admin-mod-dur').value);
    const modName = val > 1.0 ? "Zeus_Buff" : "Zeus_Debuff";

    fetch('/api/modifier', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            id: selectedUnitId,
            name: modName,
            type: type,
            value: val,
            duration: dur
        })
    }).then(r => r.json()).then(res => {
        if (res.status === 'ok') {
            fetchState(); // Refresh UI instantly
            // Auto-log the Zeus intervention
            sendCommand(`_ZEUS_LOG_ [ZEUS INTERVENTION] Applied ${type} modifier (x${val}) to unit for ${dur} hours.`);
        }
    });
}

// ⚙️ Live HP Edit (Reinforce or Smite)
function forceUnitHP() {
    if (!selectedUnitId) {
        alert("Zeus Error: No unit selected on radar!");
        return;
    }
    
    const newHP = parseFloat(document.getElementById('admin-edit-hp').value);
    if (isNaN(newHP) || newHP < 0) return;

    fetch('/api/admin_edit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            original_id: selectedUnitId,
            id: selectedUnitId,
            personnel: newHP
        })
    }).then(r => r.json()).then(res => {
        if (res.status === 'ok') {
            fetchState();
            document.getElementById('admin-edit-hp').value = '';
        }
    });
}

// 🤝 / ⚔️ Diplomacy Override
function forceDiplomacy(isAllied) {
    const f1 = document.getElementById('admin-dip-f1').value.trim();
    const f2 = document.getElementById('admin-dip-f2').value.trim();

    if (!f1 || !f2) {
        alert("Zeus Error: Specify both factions.");
        return;
    }

    fetch('/api/diplomacy', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            f1: f1,
            f2: f2,
            allied: isAllied
        })
    }).then(r => r.json()).then(res => {
        if (res.status === 'ok') {
            fetchState();
            document.getElementById('admin-dip-f1').value = '';
            document.getElementById('admin-dip-f2').value = '';
        } else {
            alert("Diplomacy override failed: " + res.msg);
        }
    });
}