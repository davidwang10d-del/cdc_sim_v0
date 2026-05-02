from flask import Flask, jsonify, request, render_template
import threading
import os
import json
import logging

# Import core components and hot-plug registries
from app import MilitaryUnit, load_dlc_registries, WEAPON_REGISTRY, BATTALION_REGISTRY
from engine import SimulationEngine
from gis import haversine_distance 

# Disable Flask's default verbose logging to keep the simulation console clean
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# 🟢 Global variables: Engine and physics thread initialized as empty shells
engine = None
physics_thread = None

def start_physics_thread():
    """Delay activation of the physics timeline after mounting a DLC"""
    global physics_thread
    if physics_thread is None or not physics_thread.is_alive():
        def run_physics():
            print("⚙️ [Physics Engine] Core heartbeat thread activated, theater timeline is now flowing.")
            engine.run_clock()
            
        physics_thread = threading.Thread(target=run_physics, daemon=True)
        physics_thread.start()

# ==========================================
# 1. Frontend Page Routing
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status_page():
    return render_template('status.html')

@app.route('/editor')
def editor_page():
    return render_template('cdc_editor.html')

# ==========================================
# 2. DLC Bootloader
# ==========================================
@app.route('/api/list_dlcs', methods=['GET'])
def list_dlcs():
    """Scan the dlc folder to retrieve all campaign modules"""
    dlcs = []
    dlc_base = 'dlc'
    if not os.path.exists(dlc_base):
        os.makedirs(dlc_base)
        
    for d in os.listdir(dlc_base):
        scenario_path = os.path.join(dlc_base, d, 'scenario.json')
        if os.path.exists(scenario_path):
            try:
                with open(scenario_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    dlcs.append({
                        "id": d,
                        "name": data.get("scenario_name", d),
                        "desc": data.get("description", "No background briefing data.")
                    })
            except Exception as e:
                print(f"Error reading DLC [{d}]: {e}")
    return jsonify(dlcs)

@app.route('/api/mount_dlc', methods=['POST'])
def mount_dlc():
    """Ignition: Mount the specified DLC, inject physical laws, and start the heartbeat"""
    global engine
    data = request.json
    dlc_id = data.get("dlc_id")
    
    if not dlc_id:
        return jsonify({"status": "error", "msg": "DLC ID not specified"})

    try:
        dlc_path = os.path.join("dlc", dlc_id)
        # 1. Hot-Swapping: Inject campaign-specific weapon and battalion registries
        load_dlc_registries(dlc_path)
        # 2. Instantiate the physics engine
        engine = SimulationEngine(dlc_id)
        # 3. Activate physics multithreading
        start_physics_thread()
        
        return jsonify({
            "status": "ok", 
            "config": {
                "name": engine.scenario_data.get("scenario_name"),
                "center": engine.scenario_data.get("map_center", [34.0, 67.0]),
                "zoom": engine.scenario_data.get("map_zoom", 6)
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "msg": f"Mount failed: {str(e)}"})

# ==========================================
# 3. Geography and Dashboard State Synchronization
# ==========================================
@app.route('/geojson')
def get_geojson():
    if not engine: return jsonify({"type": "FeatureCollection", "features": []})
    # Dynamically read the province boundaries of the current DLC
    prov_file = engine.scenario_data.get("map_config", {}).get("provinces_file", "")
    if os.path.exists(prov_file):
        with open(prov_file, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({"type": "FeatureCollection", "features": []})

@app.route('/api/registry', methods=['GET'])
def get_registry():
    return jsonify({
        "weapons": WEAPON_REGISTRY,
        "battalions": BATTALION_REGISTRY
    })

@app.route('/api/state', methods=['GET'])
def get_state():
    if not engine: return jsonify({"status": "unmounted"})
    
    units_data = {}
    for u_id, u in engine.units.items():
        units_data[u_id] = u.to_dict()
    
    return jsonify({
        "status": "ok",
        "time": {
            "day": int(engine.game_hours // 24), 
            "hour": int(engine.game_hours % 24), 
            "minute": int((engine.game_hours * 60) % 60),
            "second": int((engine.game_hours * 3600) % 60),
            "multiplier": engine.time_multiplier, 
            "paused": engine.is_paused
        },
        "units": units_data, 
        "provinces": engine.province_influence,
        "latest_logs": engine.structured_logs[-15:] if hasattr(engine, 'structured_logs') else []
    })

@app.route('/api/logs', methods=['GET'])
def get_logs():
    if not engine: return jsonify({"logs": []})
    logs = engine.structured_logs if hasattr(engine, 'structured_logs') else []
    return jsonify({"logs": logs})

@app.route('/api/terrain', methods=['GET'])
def get_terrain():
    if not engine: return jsonify({"status": "error", "complexity": 0.0})
    try:
        lon = float(request.args.get('lon'))
        lat = float(request.args.get('lat'))
        tc = engine.map_engine.get_terrain_complexity(lon, lat)
        return jsonify({"status": "ok", "complexity": round(tc, 2)})
    except Exception as e:
        return jsonify({"status": "error", "complexity": 0.0})

@app.route('/api/roads_overlay')
def get_roads_overlay():
    if not engine: return jsonify({})
    return jsonify(engine.map_engine.export_road_geojson())

# ==========================================
# 4. Tactical Commands and Backend Intervention Core
# ==========================================
@app.route('/api/command', methods=['POST'])
def execute_command():
    if not engine: return jsonify({"status": "error", "msg": "System is idling, please mount a campaign first"})
    data = request.json
    cmd_raw = data.get("command", "").strip().split()
    waypoints_data = data.get("waypoints", []) 
    
    if not cmd_raw: 
        return jsonify({"status": "error", "msg": "Command is empty"})
        
    cmd = cmd_raw[0].lower()
    msg = "Execution successful"
    
    try:
        if cmd == "play": 
            engine.is_paused = False
            engine.log_event("▶️ [System] Resuming simulation.", faction="SYSTEM", msg_type="system")
            
        elif cmd == "pause": 
            engine.is_paused = True
            engine.log_event("⏸️ [System] Suspending simulation.", faction="SYSTEM", msg_type="system")
            
        elif cmd == "speed": 
            engine.time_multiplier = float(cmd_raw[1])
            
        elif cmd in ["move", "attack", "route"]:
            u_id = cmd_raw[1]
            if u_id not in engine.units:
                return jsonify({"status": "error", "msg": "Unit not found"})
                
            u = engine.units[u_id]
            targets = []
            if waypoints_data:
                for wp in waypoints_data:
                    targets.append((float(wp['lon']), float(wp['lat'])))
            elif len(cmd_raw) >= 4:
                targets.append((float(cmd_raw[2]), float(cmd_raw[3])))
                
            if not targets:
                return jsonify({"status": "error", "msg": "Target coordinates not provided"})

            full_path = []
            curr_lon, curr_lat = u.lon, u.lat
            
            for t_lon, t_lat in targets:
                segment = engine.map_engine.find_path(
                    start_lon=curr_lon, start_lat=curr_lat, 
                    target_lon=t_lon, target_lat=t_lat, 
                    unit_composition=u.composition
                )
                if len(segment) > 1 and haversine_distance(curr_lon, curr_lat, segment[0][0], segment[0][1]) < 0.1:
                    segment.pop(0)
                full_path.extend(segment)
                curr_lon, curr_lat = t_lon, t_lat
                
            u.waypoints = full_path
            u.target_lon = targets[-1][0]
            u.target_lat = targets[-1][1]
            u.status = "MOVING"
            
            if cmd == "attack":
                u.is_attack_move = True 
                engine.log_event(f"⚔️ [Attack Move] {u.name} is initiating an attack move towards the target!", faction=u.faction, msg_type="combat")
            elif cmd == "route":
                u.is_attack_move = False
                engine.log_event(f"🗺️ [Multi-point Maneuver] {u.name} received an advanced tactical route with {len(targets)} waypoints.", faction=u.faction, msg_type="move")
            else: 
                u.is_attack_move = False 
                engine.log_event(f"🚀 [Maneuver Transfer] {u.name} is maneuvering towards the target holding fire.", faction=u.faction, msg_type="move")

        elif cmd == "airstrike":
            u_id, t_lon, t_lat = cmd_raw[1], float(cmd_raw[2]), float(cmd_raw[3])
            if u_id in engine.units:
                u = engine.units[u_id]
                if u.unit_type == "AIR_FORCE":
                    u.base_lon, u.base_lat = u.lon, u.lat
                    u.waypoints = [(t_lon, t_lat)]
                    u.status = "AIRSTRIKE_OUTBOUND"
                    engine.log_event(f"🛫 [Strike] {u.name} scrambled and is flying towards the target zone.", faction=u.faction, msg_type="combat")
            
        elif cmd == "bombard":
            u_id, t_lon, t_lat = cmd_raw[1], float(cmd_raw[2]), float(cmd_raw[3])
            if u_id in engine.units:
                u = engine.units[u_id]
                u.target_lon, u.target_lat = t_lon, t_lat
                u.status = "BOMBARDING"
                engine.log_event(f"☄️ [Firepower] {u.name} initiated artillery bombardment.", faction=u.faction, msg_type="combat")
                
        elif cmd == "stance":
            u_id, mode = cmd_raw[1], cmd_raw[2].upper()
            if u_id in engine.units:
                engine.units[u_id].stance = mode

    except Exception as e: 
        msg = f"API internal command failure: {str(e)}"
    
    return jsonify({"status": "ok", "msg": msg})

@app.route('/api/edit_unit', methods=['POST'])
def edit_unit():
    if not engine: return jsonify({"status": "error", "msg": "System is idling"})
    data = request.json
    u_id = data.get("id")
    if u_id in engine.units: 
        return jsonify({"status": "error", "msg": "Unit ID conflict"})
    
    primary_weapon = data.get("primary_weapon", "None")
    
    udata = {
        "name": data.get("name", "Newly Formed Unit"), 
        "faction": data.get("faction", "Unknown"),
        "personnel": float(data.get("personnel", 1000)), 
        "equipment_level": float(data.get("equipment_level", 1.0)),
        "lon": float(data.get("lon", 69.2)), 
        "lat": float(data.get("lat", 34.5)),
        "unit_type": data.get("unit_type", "ARMY"), 
        "composition": data.get("composition", {"inf": 3}),
        "primary_weapon": primary_weapon,
        "morale": 100.0
    }
    
    new_unit = MilitaryUnit(u_id, udata)
    new_unit.altitude = engine.map_engine.get_elevation(new_unit.lon, new_unit.lat)
    engine.units[u_id] = new_unit
    
    # Dynamically find weapon name (universal compatibility)
    weapon_info = WEAPON_REGISTRY.get(primary_weapon)
    if not weapon_info and WEAPON_REGISTRY:
        weapon_info = list(WEAPON_REGISTRY.values())[0]
    weapon_name = weapon_info.get('name', 'Standard Armament') if weapon_info else 'Standard Armament'
    
    engine.log_event(f"🚩 [Armed Mobilization] {udata['name']} (Equipment: {weapon_name}) arrived in the theater, current altitude {int(new_unit.altitude)} meters.", faction=udata["faction"], msg_type="system")
    engine.save_state()
    return jsonify({"status": "ok"})

@app.route('/api/admin_edit', methods=['POST'])
def admin_edit():
    if not engine: return jsonify({"status": "error"})
    data = request.json
    oid = data.get("original_id")
    nid = data.get("id")
    if oid not in engine.units: 
        return jsonify({"status": "error", "msg": "Unit not found"})
    
    u = engine.units.pop(oid)
    u.id = nid
    u.name = data.get("name", u.name)
    u.faction = data.get("faction", u.faction)
    u.personnel = float(data.get("personnel", u.personnel))
    u.equipment_level = float(data.get("equipment_level", u.equipment_level))
    u.lon = float(data.get("lon", u.lon))
    u.lat = float(data.get("lat", u.lat))
    u.unit_type = data.get("unit_type", u.unit_type)
    u.composition = data.get("composition", u.composition)
    u.primary_weapon = data.get("primary_weapon", u.primary_weapon)
    
    engine.units[nid] = u 
    u.parse_composition() 
    engine.save_state()
    return jsonify({"status": "ok"})

@app.route('/api/modifier', methods=['POST'])
def add_modifier():
    if not engine: return jsonify({"status": "error"})
    data = request.json
    uid = data.get('id')
    if uid in engine.units:
        engine.units[uid].modifiers.append({
            "name": data.get('name'), 
            "type": data.get('type'), 
            "value": float(data.get('value', 1.0)), 
            "duration": float(data.get('duration', 24.0))
        })
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"})

@app.route('/api/set_influence', methods=['POST'])
def set_influence():
    if not engine: return jsonify({"status": "error"})
    data = request.json
    prov = data.get('province')
    infl = float(data.get('influence', 0))
    if prov:
        engine.province_influence[prov] = infl
        engine.save_state()
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"})

@app.route('/api/diplomacy', methods=['POST'])
def set_diplomacy():
    if not engine: return jsonify({"status": "error"})
    data = request.json
    f1 = data.get('f1')
    f2 = data.get('f2')
    allied = bool(data.get('allied', False))
    
    if f1 and f2:
        engine.set_alliance(f1, f2, allied)
        action = "signed" if allied else "abrogated"
        engine.log_event(f"🤝 [Diplomatic Radar] {f1} and {f2} {action} a bilateral non-aggression pact.", faction="SYSTEM")
        engine.save_state()
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "msg": "Faction data missing"})

@app.route('/api/save_game', methods=['POST'])
def save_game_api():
    if not engine: return jsonify({"status": "error"})
    slot = request.json.get("slot", "manual_save")
    engine.save_game(slot)
    return jsonify({"status": "ok"})

@app.route('/api/load_game', methods=['POST'])
def load_game_api():
    if not engine: return jsonify({"status": "error"})
    slot = request.json.get("slot", "default")
    if slot == "initial_reset":
        engine.load_initial_scenario()
        return jsonify({"status": "ok", "msg": "System hard reset, rolled back to the scenario's initial state."})
    
    success, msg = engine.load_game(slot)
    return jsonify({"status": "ok" if success else "error", "msg": msg})

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 [CDC Theater Core] Global Strategic Simulation Architecture v3.0 ready")
    print("🌐 Listening on port: 5000 | Awaiting campaign DLC mount command from dashboard...")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)