import time
import math
import os
import json
import random

from gis import MapEngine, ProvinceEngine, haversine_distance
from app import MilitaryUnit

# ==========================================
# 2. Grand Strategy Simulation Engine (Tactical Maneuver Edition)
# ==========================================
class SimulationEngine:
    def __init__(self, dlc_id, log_file="battle_log.txt"):
        """
        [Architecture] Universal DLC Mounting Engine
        [Logic] Dynamically concatenates relative paths based on dlc_id, reads the corresponding 
                campaign's JSON configuration, and achieves "Hot-Swapping" capability 
                (e.g., instantly switching to Middle East, Taiwan Strait, Eastern Europe).
        """
        self.dlc_dir = os.path.join("dlc", dlc_id)
        scenario_file = os.path.join(self.dlc_dir, "scenario.json")
        
        print(f"\n=== 🌐 Initializing Grand Strategy Engine | Mounting Theater: [{dlc_id}] ===")
        
        if not os.path.exists(scenario_file):
            raise FileNotFoundError(f"🚨 [Critical Error] Scenario file not found: {scenario_file}")
            
        with open(scenario_file, 'r', encoding='utf-8') as f:
            self.scenario_data = json.load(f)
            
        map_config = self.scenario_data.get("map_config", {})
        
        # 🟢 Core: Dynamically convert relative paths inside DLC config to absolute/relative paths readable by the server
        for key in ["dem_file", "dem_dir", "roads_file", "rivers_file", "provinces_file"]:
            if map_config.get(key) and map_config[key] != "":
                map_config[key] = os.path.join(self.dlc_dir, map_config[key])
                
        # Feed the dynamic path configuration to the GIS engine
        self.map_engine = MapEngine(map_config)
        self.prov_engine = ProvinceEngine(map_config.get("provinces_file", ""))
        
        self.init_units_file = os.path.join(self.dlc_dir, self.scenario_data.get("initial_units_file", "units.json"))
        self.log_file = log_file
        
        self.province_influence = {}
        self.units = {}
        self.structured_logs = []
        
        self.detected_units = {} 
        self.diplomacy = {}
        
        self.time_multiplier = 1.0
        self.is_paused = True
        self.game_hours = 0.0
        
        with open(self.log_file, 'w', encoding='utf-8') as f: 
            f.write(f"=== CDC Classified Simulation Physics Log | Campaign: {self.scenario_data.get('scenario_name', 'Universal')} ===\n")
            
        if os.path.exists("save_autosave.json"): 
            self.load_game("autosave")
        else: 
            self.load_initial_scenario()

    def log_event(self, message, faction="SYSTEM", msg_type="system"):
        d = int(self.game_hours // 24)
        h = int(self.game_hours % 24)
        m = int((self.game_hours * 60) % 60)
        s = int((self.game_hours * 3600) % 60)
        
        timestamp = f"[D{d:02d} {h:02d}:{m:02d}:{s:02d}] "
        full_msg = timestamp + message
        
        with open(self.log_file, 'a', encoding='utf-8') as f: 
            f.write(full_msg + "\n")
        print(full_msg)
        
        self.structured_logs.append({
            "timestamp": f"D{d:02d} {h:02d}:{m:02d}:{s:02d}", 
            "faction": faction, 
            "message": message, 
            "type": msg_type
        })
        self.structured_logs = self.structured_logs[-300:] 

    def set_alliance(self, f1, f2, allied=True):
        if f1 not in self.diplomacy: 
            self.diplomacy[f1] = {}
        if f2 not in self.diplomacy: 
            self.diplomacy[f2] = {}
            
        self.diplomacy[f1][f2] = {"allied": allied}
        self.diplomacy[f2][f1] = {"allied": allied}

    def is_allied(self, f1, f2):
        if f1 == f2: 
            return True
        return self.diplomacy.get(f1, {}).get(f2, {}).get("allied", False)

    def load_initial_scenario(self):
        self.units.clear()
        self.province_influence.clear()
        self.detected_units.clear()
        self.diplomacy.clear()
        self.game_hours = 0.0
        
        # 🟢 Diplomacy & Faction Hot-Swapping: Dynamically load relations from JSON's diplomacy_blocs
        blocs = self.scenario_data.get("diplomacy_blocs", [])
        for bloc in blocs:
            members = bloc.get("members", [])
            for m1 in members:
                for m2 in members:
                    self.set_alliance(m1, m2, True)
        
        if os.path.exists(self.init_units_file):
            with open(self.init_units_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for k, v in data.items(): 
                    self.units[k] = MilitaryUnit(k, v)
                    
        self.log_event(f"🔄 [System] Initial tactical scenario [{self.scenario_data.get('scenario_name', 'Unknown')}] loaded successfully.", faction="SYSTEM")

    def save_game(self, slot_name):
        filename = f"save_{slot_name}.json"
        save_data = {
            "game_hours": self.game_hours, 
            "provinces": self.province_influence, 
            "detected_units": self.detected_units,
            "diplomacy": self.diplomacy,
            "units": {k: v.to_dict() for k, v in self.units.items()}
        }
        with open(filename, 'w', encoding='utf-8') as f: 
            json.dump(save_data, f, ensure_ascii=False, indent=2)
            
        if slot_name != "autosave": 
            self.log_event(f"💾 [System] Battle state backed up to: [{slot_name}]", faction="SYSTEM")

    def load_game(self, slot_name):
        filename = f"save_{slot_name}.json"
        if not os.path.exists(filename): 
            return False, f"Save file not found: {filename}"
            
        with open(filename, 'r', encoding='utf-8') as f: 
            save_data = json.load(f)
            
        self.game_hours = save_data.get("game_hours", 0.0)
        self.province_influence = save_data.get("provinces", {})
        self.detected_units = save_data.get("detected_units", {})
        self.diplomacy = save_data.get("diplomacy", {})
        
        self.units.clear()
        for k, v in save_data.get("units", {}).items(): 
            self.units[k] = MilitaryUnit(k, v)
            
        self.log_event(f"📂 [System] Save file awakened: [{slot_name}]", faction="SYSTEM")
        return True, "Load successful"

    def save_state(self):
        self.save_game("autosave")

    def get_unit_visibility(self, unit):
        base_vis = unit.personnel / 1000.0 
        stance_mod = 1.0
        if unit.stance == "STEALTH": 
            stance_mod = 0.3
        elif unit.stance == "DEFENSIVE": 
            stance_mod = 0.7
            
        tc = self.map_engine.get_terrain_complexity(unit.lon, unit.lat)
        terrain_hide_factor = max(0.3, 1.0 - (tc * 0.7)) 
        return max(0.1, base_vis * stance_mod * terrain_hide_factor)

    def get_unit_recon_power(self, observer):
        recon_score = 1.0
        if observer.unit_type == "AIR_FORCE": 
            recon_score = 10.0 
            
        if observer.unit_type == "ARMY":
            if "sf" in observer.composition: 
                recon_score += observer.composition["sf"] * 2.0 
            if "arm" in observer.composition: 
                recon_score -= observer.composition["arm"] * 0.2 
                
        return max(0.5, recon_score * observer.equipment_level)

    def _try_detect(self, observer, target, edge_dist, dt):
        max_range = 60.0 if observer.unit_type == "AIR_FORCE" else 25.0
        if edge_dist > max_range: 
            return 
            
        # 🏔️ Radar Line-of-Sight Blockage: Non-air force units will have their recon signals completely blocked by mountains
        if observer.unit_type != "AIR_FORCE" and target.unit_type != "AIR_FORCE":
            if not self.map_engine.check_line_of_sight(observer.lon, observer.lat, target.lon, target.lat):
                return
            
        recon = self.get_unit_recon_power(observer)
        visibility = self.get_unit_visibility(target)
        safe_dist = max(0.1, edge_dist)
        
        prob = (recon * visibility) / (safe_dist ** 1.5) * dt * 2.0
        
        if random.random() < prob:
            if target.id not in self.detected_units:
                if target.stance == "STEALTH":
                    self.log_event(f"👁️ [Intel] {observer.name} saw through the cover and locked onto the stealthed {target.name}!", faction=observer.faction)
                else:
                    self.log_event(f"📡 [Contact] {observer.name}'s vanguard radar detected the outline of {target.name}.", faction=observer.faction)
            self.detected_units[target.id] = 12.0 

    def detection_tick(self, dt):
        for uid in list(self.detected_units.keys()):
            self.detected_units[uid] -= dt
            if self.detected_units[uid] <= 0:
                del self.detected_units[uid]
                if uid in self.units:
                    self.log_event(f"🌫️ [Contact Lost] {self.units[uid].name} vanished into the fog of war.", faction="SYSTEM", msg_type="system")

        ulist = list(self.units.values())
        for i in range(len(ulist)):
            for j in range(i + 1, len(ulist)):
                u1, u2 = ulist[i], ulist[j]
                if self.is_allied(u1.faction, u2.faction) or u1.personnel <= 0 or u2.personnel <= 0:
                    continue
                
                # Edge distance calculation
                center_dist = haversine_distance(u1.lon, u1.lat, u2.lon, u2.lat)
                edge_dist = max(0.0, center_dist - u1.radius - u2.radius)
                
                self._try_detect(u1, u2, edge_dist, dt)
                self._try_detect(u2, u1, edge_dist, dt)

    def is_crossing_river(self, u1, u2):
        if getattr(self.map_engine, 'river_matrix', None) is None: 
            return False
            
        steps = 5
        for i in range(1, steps):
            ratio = i / steps
            slon = u1.lon + (u2.lon - u1.lon) * ratio
            slat = u1.lat + (u2.lat - u1.lat) * ratio
            
            x, y = self.map_engine.lonlat_to_grid(slon, slat)
            if self.map_engine.river_matrix[y][x] == 1:
                return True
        return False

    def tactical_aura_tick(self, dt):
        for u in self.units.values():
            u.dynamic_eq_modifier = 1.0

        ulist = list(self.units.values())
        for i in range(len(ulist)):
            for j in range(i + 1, len(ulist)):
                u1, u2 = ulist[i], ulist[j]
                
                center_dist = haversine_distance(u1.lon, u1.lat, u2.lon, u2.lat)
                edge_dist = max(0.0, center_dist - u1.radius - u2.radius)
                
                if self.is_allied(u1.faction, u2.faction) and edge_dist <= 15.0:
                    if u1.unit_type == "ARMY" and "sf" in u1.composition and u1.equipment_level >= 4.0: 
                        u2.dynamic_eq_modifier = max(u2.dynamic_eq_modifier, 1.5)
                    if u2.unit_type == "ARMY" and "sf" in u2.composition and u2.equipment_level >= 4.0: 
                        u1.dynamic_eq_modifier = max(u1.dynamic_eq_modifier, 1.5)

    def political_tick(self, dt):
        fp = {}
        for u in self.units.values():
            if u.personnel <= 0 or u.status == "MOVING" or u.status.startswith("AIRSTRIKE") or u.status == "ROUTING": 
                continue
            prov = u.current_province
            if prov == "Unknown" or prov.startswith("境外") or prov.startswith("Foreign"): 
                continue
                
            weight = u.personnel * u.equipment_level * (0.1 if u.stance == "STEALTH" else 1.0)
            if prov not in fp: 
                fp[prov] = 0.0
            
            # Since politics are scenario-dependent, we calculate influence dynamically.
            # (Simplified: Add weight to province. Future scope: multi-faction contest logic)
            fp[prov] += weight 

        for prov, net_force in fp.items():
            if prov not in self.province_influence: 
                self.province_influence[prov] = 0.0
                
            shift = (net_force / 10000.0) * 0.5 * dt 
            old_infl = self.province_influence[prov]
            new_infl = max(-100.0, min(100.0, old_infl + shift))
            self.province_influence[prov] = new_infl
            
            # (Note: Political logging can be expanded here via scenario.json faction mappings)

    def combat_tick(self, delta_time_hours):
        self.detection_tick(delta_time_hours)
        
        for u in self.units.values():
            if u.personnel <= 0 or u.unit_type in ["AIR_FORCE", "ARTILLERY"]: 
                continue
                
            visible_enemies = []
            for uid in self.detected_units:
                if uid in self.units and self.units[uid].personnel > 0 and not self.is_allied(u.faction, self.units[uid].faction):
                    center_dist = haversine_distance(u.lon, u.lat, self.units[uid].lon, self.units[uid].lat)
                    edge_dist = max(0.0, center_dist - u.radius - self.units[uid].radius)
                    visible_enemies.append((edge_dist, self.units[uid]))
                    
            if not visible_enemies: 
                continue
                
            visible_enemies.sort(key=lambda x: x[0])
            nearest_edge_dist, nearest_enemy = visible_enemies[0]

            # Guerrilla tactical evasion retreat
            if u.stance == "STEALTH" and nearest_edge_dist <= u.active_fire_range * 0.8:
                if u.status != "MOVING": 
                    ea = math.atan2(u.lat - nearest_enemy.lat, u.lon - nearest_enemy.lon)
                    # Set retreat distance to 3~5 km, converted to degrees (divided by 111.0)
                    deg = random.uniform(3.0, 5.0) / 111.0 
                    u.waypoints = [(u.lon + math.cos(ea) * deg, u.lat + math.sin(ea) * deg)]
                    u.status = "MOVING"
                    u.is_attack_move = False 
                    if random.random() < 0.2: 
                        self.log_event(f"🥷 [Tactical Evasion] {u.name} completed the ambush and is falling back under cover!", faction=u.faction, msg_type="combat")

        for u in self.units.values():
            if u.status == "BOMBARDING" and u.personnel > 0:
                for target in self.units.values():
                    if target.personnel > 0 and not self.is_allied(u.faction, target.faction):
                        center_dist = haversine_distance(u.target_lon, u.target_lat, target.lon, target.lat)
                        # Target hit detection: dist to center <= kill radius (5.0) + unit radius
                        if target.id in self.detected_units and max(0.0, center_dist - target.radius) <= 5.0: 
                            tc = self.map_engine.get_terrain_complexity(target.lon, target.lat)
                            cas = (u.get_terrain_efficiency(tc) * 1.5) * u.personnel * delta_time_hours * 0.005 
                            target.personnel = max(0, target.personnel - cas)
                            target.morale = max(0, target.morale - cas * 0.5) 
                            if target.personnel > 0 and target.morale < 10.0 and target.status not in ["ROUTING"]:
                                target.status = "ROUTING"
                                target.stance = "STEALTH"
                                self.log_event(f"🌪️ [Position Collapse] {target.name} suffered precision bombardment, defense line routed!", faction=target.faction, msg_type="combat")

        unit_list = list(self.units.values())
        for i in range(len(unit_list)):
            for j in range(i + 1, len(unit_list)):
                u1 = unit_list[i]
                u2 = unit_list[j]
                
                if self.is_allied(u1.faction, u2.faction) or u1.personnel <= 0 or u2.personnel <= 0: 
                    continue
                    
                center_dist = haversine_distance(u1.lon, u1.lat, u2.lon, u2.lat)
                edge_dist = max(0.0, center_dist - u1.radius - u2.radius)
                
                max_engage_dist = max(u1.active_fire_range, u2.active_fire_range, 0.3)
                if edge_dist > max_engage_dist:
                    continue

                u1_can_see = u2.id in self.detected_units
                u2_can_see = u1.id in self.detected_units
                
                # 🏔️ 3D Physics: Detect real mountain blockage between two points
                has_los = self.map_engine.check_line_of_sight(u1.lon, u1.lat, u2.lon, u2.lat)
                
                # ☄️ Weapon Physics: Range >= 4.0km enables indirect/blind fire over mountains
                u1_indirect = u1.active_fire_range >= 4.0
                u2_indirect = u2.active_fire_range >= 4.0
                
                if not has_los and not u1_indirect and not u2_indirect:
                    continue

                if not u1_can_see and not u2_can_see and edge_dist > 0.3: 
                    continue 
                    
                u1_engages = False
                if edge_dist <= 0.3:
                    u1_engages = True
                elif u1_can_see and edge_dist <= u1.active_fire_range:
                    if has_los or u1_indirect:
                        if u1.status == "IDLE" or getattr(u1, 'is_attack_move', False) or u1.stance == "AGGRESSIVE":
                            u1_engages = True
                        
                u2_engages = False
                if edge_dist <= 0.3:
                    u2_engages = True
                elif u2_can_see and edge_dist <= u2.active_fire_range:
                    if has_los or u2_indirect:
                        if u2.status == "IDLE" or getattr(u2, 'is_attack_move', False) or u2.stance == "AGGRESSIVE":
                            u2_engages = True

                if not u1_engages and not u2_engages:
                    continue
                    
                river_crossed = self.is_crossing_river(u1, u2)
                atk1_mult = 1.0 if u1_can_see else 0.0 
                atk2_mult = 1.0 if u2_can_see else 0.0
                
                if u1_can_see and not u2_can_see and u1_engages and random.random() < 0.1 * delta_time_hours:
                    self.log_event(f"🥷 [One-sided Massacre] {u1.name} initiated BVR/ambush fire on {u2.name} from the shadows!", faction=u1.faction, msg_type="combat")
                elif u2_can_see and not u1_can_see and u2_engages and random.random() < 0.1 * delta_time_hours:
                    self.log_event(f"🥷 [One-sided Massacre] {u2.name} initiated BVR/ambush fire on {u1.name} from the shadows!", faction=u2.faction, msg_type="combat")

                if river_crossed:
                    if u1_engages and u2.status != "MOVING" and u1.waypoints:
                        penalty = 0.85 if u1.composition.get("eng", 0) > 0 else 0.5
                        atk1_mult *= penalty
                        if u2_can_see and random.random() < 0.1 * delta_time_hours:
                            self.log_event(f"💥 [River Crossing] {u1.name} met fierce resistance while crossing the river!", faction=u1.faction, msg_type="combat")
                    elif u2_engages and u1.status != "MOVING" and u2.waypoints:
                        penalty = 0.85 if u2.composition.get("eng", 0) > 0 else 0.5
                        atk2_mult *= penalty
                        if u1_can_see and random.random() < 0.1 * delta_time_hours:
                            self.log_event(f"💥 [River Crossing] {u2.name} met fierce resistance while crossing the river!", faction=u2.faction, msg_type="combat")
                
                tc = self.map_engine.get_terrain_complexity(u1.lon, u1.lat)
                cw = max(3000, 45000 - (tc * 45000))
                
                eff_p1 = u1.personnel if u1.unit_type == "AIR_FORCE" else min(u1.personnel, cw)
                eff_p2 = u2.personnel if u2.unit_type == "AIR_FORCE" else min(u2.personnel, cw)
                
                eff1 = u1.get_terrain_efficiency(tc)
                eff2 = u2.get_terrain_efficiency(tc)
                
                # 🦅 Elevation Advantage: If the height difference is >200m, the higher unit gains a 20% firepower efficiency boost
                alt_diff = getattr(u1, 'altitude', 0.0) - getattr(u2, 'altitude', 0.0)
                if alt_diff > 200: eff1 *= 1.2 
                elif alt_diff < -200: eff2 *= 1.2
                
                atk1 = (u1.base_soft_attack * u2.softness) + (u1.base_hard_attack * (1.0 - u2.softness))
                if u1.ap < u2.armor: 
                    atk1 *= 0.5 
                    
                atk2 = (u2.base_soft_attack * u1.softness) + (u2.base_hard_attack * (1.0 - u1.softness))
                if u2.ap < u1.armor: 
                    atk2 *= 0.5

                def1 = (u1.base_breakthrough if u1.status in ["MOVING", "ROUTING"] else u1.base_defense) * eff1
                def2 = (u2.base_breakthrough if u2.status in ["MOVING", "ROUTING"] else u2.base_defense) * eff2
                
                final_atk1 = (atk1 * eff1 * (eff_p1 / 1000.0) * atk1_mult * 0.2) if u1_engages else 0.0
                final_atk2 = (atk2 * eff2 * (eff_p2 / 1000.0) * atk2_mult * 0.2) if u2_engages else 0.0
                
                if u1.unit_type == "AIR_FORCE": 
                    final_atk1 *= 3.0
                    final_atk2 *= 0.1
                elif u2.unit_type == "AIR_FORCE": 
                    final_atk2 *= 3.0
                    final_atk1 *= 0.1

                def calc_hits(a, d):
                    return (min(a, d) * 0.1) + (max(0, a - d) * 0.4)

                h2 = calc_hits(final_atk1, def2) * delta_time_hours * 5.0
                h1 = calc_hits(final_atk2, def1) * delta_time_hours * 5.0

                if u1.status == "ROUTING": 
                    h2 = 0 
                if u2.status == "ROUTING": 
                    h1 = 0

                u1.personnel = max(0, u1.personnel - h1)
                u2.personnel = max(0, u2.personnel - h2)
                
                u1.morale = max(0, u1.morale - h1)
                u2.morale = max(0, u2.morale - h2)

                # 🟢 Fixed and enabled organization collapse and routing logic
                for tu in [u1, u2]:
                    if tu.personnel > 0 and tu.morale < 10.0 and tu.status not in ["ROUTING", "AIRSTRIKE_OUTBOUND", "AIRSTRIKE_RTB"]:
                        tu.status = "ROUTING"
                        tu.stance = "STEALTH"
                        ea = random.uniform(0, 2 * math.pi) 
                        deg = random.uniform(0.3, 0.5)
                        tu.waypoints = [(tu.lon + math.cos(ea) * deg, tu.lat + math.sin(ea) * deg)]
                        self.log_event(f"🌪️ [Line Collapse] {tu.name} organization depleted! Remnants dropped their gear and are routing to the rear!", faction=tu.faction, msg_type="combat")

                if u1.personnel == 0: 
                    self.log_event(f"☠️ [Annihilated] Corpses litter the field, {u1.name} has been completely wiped out.", faction=u1.faction, msg_type="combat")
                if u2.personnel == 0: 
                    self.log_event(f"☠️ [Annihilated] Corpses litter the field, {u2.name} has been completely wiped out.", faction=u2.faction, msg_type="combat")

    def run_clock(self):
        last_time = time.time()
        while True:
            try:
                current_time = time.time()
                dt_real = current_time - last_time
                last_time = current_time
                
                if not self.is_paused:
                    # Convert real seconds to game hours based on 1s = 12 game-seconds, multiplied by UI flow rate (Delta Time)
                    dt_game_hours = dt_real * (12.0 / 3600.0) * self.time_multiplier
                    self.game_hours += dt_game_hours
                    
                    # ✅ Safety Lock: Use list() to force a memory snapshot, preventing dict iteration crashes if Flask API injects new units
                    for u in list(self.units.values()): 
                        u.update_position(dt_game_hours, self)
                        
                    # Execute physics resolution modules sequentially
                    self.tactical_aura_tick(dt_game_hours)
                    self.political_tick(dt_game_hours)
                    self.combat_tick(dt_game_hours)
                    
            except Exception as e:
                # Engine Crash Tolerance: Do not let the thread die on error, print stack and enter next loop
                print(f"\n🚨 [System Alert] Physics engine anomaly detected, auto-resetting heartbeat: {e}")
                import traceback
                traceback.print_exc()
                
            # Physics Safety Lock: Lock max refresh rate to approx 10 Ticks/sec to prevent dt from underflowing 64-bit floats
            time.sleep(0.1)