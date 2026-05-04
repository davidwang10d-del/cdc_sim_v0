import math
import json
import os
import random

# Global dictionaries, initially empty. Will be hot-injected when mounting a DLC.
WEAPON_REGISTRY = {}
BATTALION_REGISTRY = {}

def load_dlc_registries(dlc_path):
    """Hot-swapping: Mount the weapon and battalion registries of the specified DLC"""
    global WEAPON_REGISTRY, BATTALION_REGISTRY
    w_path = os.path.join(dlc_path, 'weapons.json')
    b_path = os.path.join(dlc_path, 'battalions.json')
    
    # Clear before each new DLC mount to prevent data contamination
    WEAPON_REGISTRY.clear()
    BATTALION_REGISTRY.clear()
    
    if os.path.exists(w_path):
        with open(w_path, 'r', encoding='utf-8') as f:
            WEAPON_REGISTRY.update(json.load(f))
    if os.path.exists(b_path):
        with open(b_path, 'r', encoding='utf-8') as f:
            BATTALION_REGISTRY.update(json.load(f))

# 🟢 Fix 1: Restored the accidentally deleted spherical distance formula (used for calculating march speed and range)
def haversine_distance(lon1, lat1, lon2, lat2):
    R = 6371.0
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# 🟢 Fix 2: Restored the fallback default weapon registry (prevents crashing if DLC fails to load or is unmounted)
_FALLBACK_WEAPONS = {
    "AK-74": {"name": "Standard Armament", "range": 0.5, "soft_attack": 1.0, "hard_attack": 0.1, "ap": 0.0}
}

# ==========================================
# 1. Military Entity Core Class
# ==========================================
class MilitaryUnit:
    def __init__(self, unit_id, data):
        self.id = unit_id
        self.name = data["name"]
        self.faction = data["faction"]
        
        self.personnel = float(data.get("personnel", 1000.0))
        self.equipment_level = float(data.get("equipment_level", 1.0))
        
        self.lon = float(data["lon"])
        self.lat = float(data["lat"])
        
        self.unit_type = data.get("unit_type", "ARMY")
        self.composition = data.get("composition", {"inf": 3})
        
        self.primary_weapon = data.get("primary_weapon", "AK-74")
        self.weapon_name = WEAPON_REGISTRY.get(self.primary_weapon, WEAPON_REGISTRY.get("AK-74", _FALLBACK_WEAPONS["AK-74"]))["name"]
        self.icon = data.get("icon", "")  # customize icon
        self.morale = float(data.get("morale", 100.0))
        self.status = data.get("status", "IDLE")
        
        self.waypoints = data.get("waypoints", [])
        self.target_lon = data.get("target_lon") 
        self.target_lat = data.get("target_lat")
        
        self.current_province = "Unknown"
        self.stance = data.get("stance", "AGGRESSIVE")
        self.base_lon = None
        self.base_lat = None
        
        self.dynamic_eq_modifier = 1.0
        self.entrenchment = float(data.get("entrenchment", 0.0))
        self.modifiers = data.get("modifiers", []) 
        
        self.is_attack_move = False 
        self.active_fire_range = 0.5 
        
        # Physical footprint radius (km)
        self.radius = 0.5 

        self.parse_composition()

    def parse_composition(self):
        if self.unit_type not in ["ARMY", "AIR_FORCE", "ARTILLERY"]:
            self.unit_type = "ARMY"

        self.active_fire_range = WEAPON_REGISTRY.get(self.primary_weapon, WEAPON_REGISTRY.get("AK-74", _FALLBACK_WEAPONS["AK-74"]))["range"]

        # Dynamically calculate defense line radius: scales with personnel (1000 troops -> ~1.5km radius; 2500 troops -> ~2.5km)
        if self.personnel > 0:
            self.radius = max(0.5, math.sqrt(self.personnel) * 0.05)
        else:
            self.radius = 0.0

        if self.unit_type != "ARMY":
            self.speed = 800.0 if self.unit_type == "AIR_FORCE" else 0.0
            self.base_soft_attack = 500.0 if self.unit_type == "AIR_FORCE" else 0.0
            self.base_hard_attack = 300.0 if self.unit_type == "AIR_FORCE" else 0.0
            self.base_defense = 50.0 if self.unit_type == "AIR_FORCE" else 5.0
            self.base_breakthrough = 0.0
            self.max_org = 100.0
            self.ap = 500.0 
            self.armor = 0.0
            self.softness = 1.0
            self.terrain_mod = 1.0
            if self.unit_type == "AIR_FORCE":
                self.active_fire_range = 15.0
                self.radius = 0.1 # Air force has virtually no ground physical collision
            return

        total_bats = sum(self.composition.values())
        if total_bats == 0: 
            total_bats = 1
            
        speeds = []
        soft, hard, defense, breakthrough, org_sum, armor_sum, terrain_sum, ap = 0, 0, 0, 0, 0, 0, 0, 0
        soft_bats = 0

        for b_type, count in self.composition.items():
            if count <= 0 or b_type not in BATTALION_REGISTRY: 
                continue
                
            reg = BATTALION_REGISTRY[b_type]
            speeds.append(reg["speed"])
            soft += reg["soft"] * count
            hard += reg["hard"] * count
            defense += reg["defense"] * count
            breakthrough += reg["breakthrough"] * count
            org_sum += reg["org"] * count
            ap = max(ap, reg["ap"]) 
            armor_sum += reg["armor"] * count
            terrain_sum += reg["terrain"] * count
            
            if b_type in ["inf", "art", "sf", "eng"]: 
                soft_bats += count

        self.speed = min(speeds) if speeds else 5.0
        eq_mod = self.equipment_level * self.dynamic_eq_modifier
        
        self.base_soft_attack = soft * eq_mod
        self.base_hard_attack = hard * eq_mod
        self.base_defense = defense * eq_mod
        self.base_breakthrough = breakthrough * eq_mod
        self.max_org = max(10.0, org_sum / total_bats) 
        self.ap = ap * eq_mod
        self.armor = (armor_sum / total_bats) * eq_mod
        self.softness = soft_bats / total_bats
        self.terrain_mod = terrain_sum / total_bats

    def get_mod_multiplier(self, mod_type):
        mult = 1.0
        for mod in self.modifiers:
            if mod["type"] == mod_type: 
                mult *= mod["value"]
        return mult

    def get_terrain_efficiency(self, terrain_complexity):
        if self.unit_type == "AIR_FORCE": return 2.0
        if self.unit_type == "ARTILLERY": return 1.0
        
        actual_eff = max(0.1, 1.0 - (terrain_complexity * (1.0 - self.terrain_mod)))
        
        if self.stance == "DEFENSIVE": 
            actual_eff *= (1.0 + self.entrenchment)
        elif self.stance == "STEALTH": 
            actual_eff *= 0.7 
            
        return actual_eff * self.get_mod_multiplier("combat") * (max(10, self.morale) / 100.0)

    def update_position(self, delta_time_hours, engine):
        if self.personnel <= 0: 
            return

        self.parse_composition() 
        
        if self.current_province == "Unknown": 
            self.current_province = engine.prov_engine.get_province(self.lon, self.lat)
        
        self.modifiers = [m for m in self.modifiers if (m["duration"] - delta_time_hours) > 0]
        for m in self.modifiers: 
            m["duration"] -= delta_time_hours

        if self.waypoints and self.status in ["IDLE", "DEFENDING"]:
            self.status = "MOVING"

        if self.status == "IDLE":
            self.morale = min(self.max_org, self.morale + 2.0 * delta_time_hours)
            if self.stance == "DEFENSIVE": 
                self.entrenchment = min(1.0, self.entrenchment + 0.05 * delta_time_hours)
        else: 
            self.entrenchment = 0.0

        if self.status not in ["MOVING", "AIRSTRIKE_OUTBOUND", "AIRSTRIKE_RTB", "ROUTING"] or not self.waypoints: 
            return

        current_target_lon, current_target_lat = self.waypoints[0]
        dist_km = haversine_distance(self.lon, self.lat, current_target_lon, current_target_lat)
        
        if dist_km < 0.1:
            self.lon = current_target_lon
            self.lat = current_target_lat
            self.waypoints.pop(0) 
            
            if not self.waypoints:
                if self.status == "MOVING": 
                    self.status = "IDLE"
                    self.is_attack_move = False 
                    engine.log_event(f"📡 [Maneuver] {self.name} reached designated coordinates.", faction=self.faction, msg_type="move")
                elif self.status == "ROUTING": 
                    self.status = "IDLE"
                    self.morale = 30.0
                    engine.log_event(f"🏳️ [Rally] {self.name} ended routing and barely reformed the defense line.", faction=self.faction, msg_type="move")
                elif self.status == "AIRSTRIKE_OUTBOUND": 
                    self.status = "AIRSTRIKE_RTB"
                    self.waypoints = [(self.base_lon, self.base_lat)]
                    engine.log_event(f"💥 [Airstrike] {self.name} completed bombing run, pulling up for RTB!", faction=self.faction, msg_type="combat")
                elif self.status == "AIRSTRIKE_RTB": 
                    self.status = "IDLE"
                    engine.log_event(f"🛬 [Air Force RTB] {self.name} returned to base.", faction=self.faction, msg_type="move")
                return
            else:
                current_target_lon, current_target_lat = self.waypoints[0]
                dist_km = haversine_distance(self.lon, self.lat, current_target_lon, current_target_lat)

        tp = engine.map_engine.get_terrain_complexity(self.lon, self.lat)
        self.altitude = engine.map_engine.get_elevation(self.lon, self.lat)
        tsm = 1.0 if self.unit_type == "AIR_FORCE" else (1.0 - (tp * (1.0 - min(1.0, self.terrain_mod))))
        
        # Original speed calculation
        actual_speed = self.speed * tsm * (0.5 if self.stance == "STEALTH" else 1.0) * (1.5 if self.status == "ROUTING" else 1.0) * self.get_mod_multiplier("speed")
        
        # Fix: If in attack move and enemies enter weapon range on radar, force move speed to zero (halt and establish defense line)
        if self.is_attack_move and self.status == "MOVING":
            for other in engine.units.values():
                if other.personnel > 0 and not engine.is_allied(self.faction, other.faction):
                    edge_dist = max(0.0, haversine_distance(self.lon, self.lat, other.lon, other.lat) - self.radius - other.radius)
                    if other.id in engine.detected_units and edge_dist <= self.active_fire_range:
                        actual_speed = 0.0  # Halted by enemy contact, engaging on site
                        break

        # Fix: If artillery position, simulate fatigue/recalibration time without an explicit ammo concept
        if self.status == "BOMBARDING":
            if not hasattr(self, 'bombard_timer'):
                self.bombard_timer = 2.0 # Set the physical limit of one fire for effect barrage to 2 hours
            self.bombard_timer -= delta_time_hours
            if self.bombard_timer <= 0:
                self.status = "IDLE"
                delattr(self, 'bombard_timer')
                engine.log_event(f"🔇 [Ceasefire] {self.name} barrels overheated / barrage complete, halting bombardment for maintenance.", faction=self.faction)
            return # Artillery absolutely cannot move while bombarding
        step_km = actual_speed * delta_time_hours
        ratio = min(1.0, step_km / dist_km) if dist_km > 0 else 1.0
        
        self.lon += (current_target_lon - self.lon) * ratio
        self.lat += (current_target_lat - self.lat) * ratio
        
        if self.unit_type == "AIR_FORCE" and self.status.startswith("AIRSTRIKE") and self.personnel > 0:
            for other in engine.units.values():
                if other.personnel > 0 and not engine.is_allied(self.faction, other.faction) and other.unit_type == "ARMY" and "sf" in other.composition and other.equipment_level >= 3.0:
                    # Air interception edge detection
                    if max(0.0, haversine_distance(self.lon, self.lat, other.lon, other.lat) - self.radius - other.radius) <= 10.0:
                        if random.random() < 0.4 * delta_time_hours:
                            self.personnel = 0
                            engine.log_event(f"💥 [AA Net] {self.name} was shot out of the sky by {other.name}'s anti-air fire net and crashed!", faction=self.faction, msg_type="combat")
                            break

        new_prov = engine.prov_engine.get_province(self.lon, self.lat)
        if new_prov != self.current_province and self.current_province != "Unknown" and self.stance != "STEALTH":
            if self.status != "ROUTING":
                engine.log_event(f"🚨 [Zone Alert] {self.name} crossed the border into {new_prov}.", faction=self.faction, msg_type="move")
        self.current_province = new_prov
        # Real-time synchronization of local physical altitude (meters)
        self.altitude = engine.map_engine.get_elevation(self.lon, self.lat)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name, 
            "faction": self.faction, 
            "icon": getattr(self, 'icon', ""),
            "personnel": self.personnel,
            "lon": self.lon, 
            "lat": self.lat, 
            "speed": self.speed,
            "equipment_level": self.equipment_level, 
            "unit_type": self.unit_type, 
            "composition": self.composition,
            "primary_weapon": self.primary_weapon,
            "weapon_name": self.weapon_name,
            "morale": self.morale, 
            "stance": self.stance,
            "entrenchment": self.entrenchment, 
            "modifiers": self.modifiers,
            "waypoints": self.waypoints, 
            "target_lon": self.target_lon, 
            "target_lat": self.target_lat,
            "status": self.status,
            "is_attack_move": self.is_attack_move,
            "active_fire_range": self.active_fire_range,
            "radius": self.radius, # Export physical radius for frontend circle rendering
            "altitude": getattr(self, 'altitude', 0.0), # Export altitude
            "stats": {
                "soft": self.base_soft_attack, 
                "hard": self.base_hard_attack, 
                "armor": self.armor, 
                "ap": self.ap, 
                "softness": self.softness
            }
        }