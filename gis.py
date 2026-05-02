import os
import glob
import math
import heapq
import json
import numpy as np
from PIL import Image

try:
    import rasterio
    from rasterio.merge import merge
    HAS_RASTERIO = True
except ImportError as e:
    print(f"⚠️ Engine module import blocked: {e}")
    HAS_RASTERIO = False
    merge = None

def haversine_distance(lon1, lat1, lon2, lat2):
    """
    [Function] Standard spherical distance calculation (km)
    [Logic] Uses the haversine formula to convert geographic lat/lon coordinates 
            into the shortest great-circle distance on the Earth's surface.
    """
    R = 6371.0
    dlon = math.radians(lon2 - lon1)
    dlat = math.radians(lat2 - lat1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class MapEngine:
    def __init__(self, map_config):
        """
        [Function] Initializes the GIS engine, supporting folder-level 90m tile scanning or direct mounting of a single TIF.
        """
        print("\n" + "="*50)
        print(f"🌍 [GIS] Military-grade GIS engine starting, reading theater configuration...")
        self.grid_w, self.grid_h = map_config.get("grid_resolution", [200, 200])
        bounds = map_config.get("bounds", {})
        self.min_lon, self.max_lon = bounds.get("min_lon", 60.0), bounds.get("max_lon", 75.0)
        self.min_lat, self.max_lat = bounds.get("min_lat", 29.0), bounds.get("max_lat", 39.0)
        
        self.use_real_dem = False
        self.dem_full = None
        self.transform = None
        self.width = 0
        self.height = 0

        dem_dir = map_config.get("dem_dir", map_config.get("dem_file", ""))

        # --- 1. Dual-mode DEM Data Mounting Core (Ultra-fast Direct Read) ---
        if HAS_RASTERIO and dem_dir and os.path.exists(dem_dir):
            try:
                # Scenario A: Input is a directory containing 90m tiles
                if os.path.isdir(dem_dir):
                    search_path = os.path.join(dem_dir, "*.tif")
                    tif_files = glob.glob(search_path) + glob.glob(os.path.join(dem_dir, "*.tiff"))
                    
                    if not tif_files:
                        print(f"⚠️ [GIS] No .tif files found in {dem_dir}, falling back to virtual plains.")
                        self._fallback_to_plains()
                    else:
                        print(f"📂 [GIS] Detected {len(tif_files)} elevation tiles, executing lossless mosaic...")
                        src_files_to_mosaic = [rasterio.open(f) for f in tif_files]
                        
                        self.dem_full, self.transform = merge(src_files_to_mosaic)
                        self.dem_full = self.dem_full[0].astype(np.float32)
                        self.height, self.width = self.dem_full.shape
                        
                        for src in src_files_to_mosaic: 
                            src.close()
                        self._process_dem_matrix()
                        
                # Scenario B: Input is a single, aggregated 90m TIF file
                elif os.path.isfile(dem_dir) and dem_dir.endswith(('.tif', '.tiff')):
                    print(f"📄 [GIS] Detected single theater DEM, executing ultra-fast mount...")
                    with rasterio.open(dem_dir) as src:
                        self.dem_full = src.read(1).astype(np.float32)
                        self.transform = src.transform
                        self.height, self.width = self.dem_full.shape
                        
                    self._process_dem_matrix()
                else:
                    print(f"⚠️ [GIS] Unrecognized format for {dem_dir}, falling back to virtual plains.")
                    self._fallback_to_plains()
                    
            except Exception as e:
                print(f"⚠️ [GIS] DEM load exception: {e}, falling back to virtual plains.")
                self._fallback_to_plains()
        else:
            print(f"⚠️ [GIS] Entity missing or rasterio environment lacking, falling back to virtual plains.")
            self._fallback_to_plains()

        # --- 2. Mount Vector Features ---
        self.river_matrix = np.zeros((self.grid_h, self.grid_w), dtype=np.int8)
        if map_config.get("rivers_file"): self.load_rivers(map_config["rivers_file"])
        
        self.road_matrix = np.zeros((self.grid_h, self.grid_w), dtype=np.int8)
        if map_config.get("roads_file"): self.load_roads(map_config["roads_file"])

    def _process_dem_matrix(self):
        """Elevation matrix preprocessing & pathfinding grid generation"""
        self.dem_full[self.dem_full < -100] = 0
        self.use_real_dem = True 
        
        img = Image.fromarray(self.dem_full, mode='F')
        img_small = img.resize((self.grid_w, self.grid_h), Image.Resampling.BILINEAR)
        data_small = np.clip(np.array(img_small), 0, 5000)
        
        self.cost_matrix = data_small / 5000.0
        self.path_grid = 1.0 + (self.cost_matrix ** 2) * 50.0
        
        print(f"✅ [GIS] Global terrain matrix ready! Total coverage pixels: {self.width}x{self.height}")

    def _fallback_to_plains(self):
        """Disaster recovery fallback plan"""
        self.use_real_dem = False
        self.cost_matrix = np.zeros((self.grid_h, self.grid_w))
        self.path_grid = np.ones((self.grid_h, self.grid_w))

    def get_elevation(self, lon, lat):
        """
        Get the true elevation (meters) for a specific longitude and latitude - [Equipped with data void self-healing algorithm and out-of-bounds protection]
        """
        if self.use_real_dem and self.dem_full is not None and self.transform is not None:
            try:
                col, row = ~self.transform * (lon, lat)
                col, row = int(col), int(row)
                
                # Out-of-bounds protection
                if 0 <= row < self.dem_full.shape[0] and 0 <= col < self.dem_full.shape[1]:
                    alt = float(self.dem_full[row, col])
                    
                    # 1. Normal case: If it's a valid mountain elevation, return directly
                    if alt > 5.0: 
                        return alt
                    
                    # 2. Patch triggered: If 0 or NODATA void, initiate smart nearest-neighbor pixel interpolation
                    for radius in range(1, 15):
                        for dy in range(-radius, radius + 1):
                            for dx in range(-radius, radius + 1):
                                if abs(dx) == radius or abs(dy) == radius:
                                    nr, nc = row + dy, col + dx
                                    # Ensure the ray doesn't fly out of the matrix boundary
                                    if 0 <= nr < self.dem_full.shape[0] and 0 <= nc < self.dem_full.shape[1]:
                                        val = float(self.dem_full[nr, nc])
                                        if val > 5.0: # Borrow the nearest true elevation
                                            return val
            except Exception:
                pass
                
        # Global out-of-bounds fallback: Treat units stepping out of the map boundary as being on a 500m plateau
        return 500.0

    def get_terrain_complexity(self, lon, lat):
        """Calculate terrain damping coefficient"""
        alt = self.get_elevation(lon, lat)
        slope_factor = abs(math.sin(lon * 5.0) * math.cos(lat * 5.0))
        if alt > 3000: 
            return 0.8
        elif alt > 1500: 
            return 0.5 + slope_factor * 0.3
        return 0.2 + slope_factor * 0.2

    def check_line_of_sight(self, lon1, lat1, lon2, lat2):
        """
        Bresenham pixel-level 3D ray tracing: Earth curvature correction + Anti-out-of-bounds reinforcement
        """
        dist_km = haversine_distance(lon1, lat1, lon2, lat2)
        if dist_km <= 0.3: 
            return True 
            
        if not self.use_real_dem or self.dem_full is None or self.transform is None:
            return True

        alt1 = self.get_elevation(lon1, lat1) + 5.0 
        alt2 = self.get_elevation(lon2, lat2) + 5.0

        try:
            r0, c0 = ~self.transform * (lon1, lat1)
            r1, c1 = ~self.transform * (lon2, lat2)
            
            # Safety lock: Ensure both probe ends are inside the matrix, otherwise allow LOS
            if not (0 <= r0 < self.dem_full.shape[0] and 0 <= c0 < self.dem_full.shape[1]):
                return True
            if not (0 <= r1 < self.dem_full.shape[0] and 0 <= c1 < self.dem_full.shape[1]):
                return True

            x0, y0 = int(c0), int(r0)
            x1, y1 = int(c1), int(r1)
        except Exception:
            return True

        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        total_pixel_dist = math.hypot(dx, dy)
        if total_pixel_dist == 0: 
            return True

        R_eq = 8500.0  
        x, y = x0, y0

        while True:
            # Safe boundary check: Ensure every tracked pixel is not out of bounds
            if 0 <= y < self.dem_full.shape[0] and 0 <= x < self.dem_full.shape[1]:
                curr_dist = math.hypot(x - x0, y - y0)
                ratio = curr_dist / total_pixel_dist
                
                d1 = dist_km * ratio
                d2 = dist_km * (1.0 - ratio)
                drop_m = (d1 * d2) / (2.0 * R_eq) * 1000.0 
                
                ray_alt = alt1 + (alt2 - alt1) * ratio - drop_m
                
                if self.dem_full[y, x] > ray_alt:
                    return False

            if x == x1 and y == y1: 
                break
                
            e2 = 2 * err
            if e2 > -dy: 
                err -= dy
                x += sx
            if e2 < dx: 
                err += dx
                y += sy

        return True

    def lonlat_to_grid(self, lon, lat):
        """Map geographic coordinates to pathfinding grid space"""
        x = int((lon - self.min_lon) / (self.max_lon - self.min_lon) * self.grid_w)
        y = int((self.max_lat - lat) / (self.max_lat - self.min_lat) * self.grid_h)
        return max(0, min(self.grid_w - 1, x)), max(0, min(self.grid_h - 1, y))

    def grid_to_lonlat(self, x, y):
        """Reverse project pathfinding grid coordinates back to real geographic space"""
        lon = self.min_lon + (x / self.grid_w) * (self.max_lon - self.min_lon)
        lat = self.max_lat - (y / self.grid_h) * (self.max_lat - self.min_lat)
        return lon, lat

    def _draw_line_on_grid(self, x0, y0, x1, y1, matrix):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        
        while True:
            if 0 <= x0 < self.grid_w and 0 <= y0 < self.grid_h:
                matrix[y0][x0] = 1 
            if x0 == x1 and y0 == y1: 
                break
            e2 = 2 * err
            if e2 >= dy: 
                err += dy
                x0 += sx
            if e2 <= dx: 
                err += dx
                y0 += sy

    def load_rivers(self, geojson_path):
        if not os.path.exists(geojson_path):
            print(f"⚠️ [GIS] Hydrology data not found: {geojson_path}. Current map has no river penalties.")
            return
            
        try:
            with open(geojson_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            river_count = 0
            for feature in data.get('features', []):
                geom = feature.get('geometry', {})
                if geom.get('type') == 'LineString':
                    coords = geom.get('coordinates', [])
                    for i in range(len(coords) - 1):
                        lon1, lat1 = coords[i]
                        lon2, lat2 = coords[i+1]
                        x0, y0 = self.lonlat_to_grid(lon1, lat1)
                        x1, y1 = self.lonlat_to_grid(lon2, lat2)
                        self._draw_line_on_grid(x0, y0, x1, y1, self.river_matrix)
                    river_count += 1
                    
            print(f"🌊 [GIS] Successfully rasterized {river_count} real river branches and burned them into the physics grid!")
        except Exception as e:
            print(f"⚠️ [GIS] Hydrology network parsing failed: {e}")

    def load_roads(self, filepath):
        if not os.path.exists(filepath):
            print(f"⚠️ [GIS] Road data not found: {filepath}. Current map has no road network.")
            return
            
        if filepath.endswith('.tif') or filepath.endswith('.tiff'):
            if not HAS_RASTERIO:
                print("⚠️ [GIS] Reading TIF roads requires rasterio.")
                return
            try:
                with rasterio.open(filepath) as src:
                    road_data = src.read(1)
                    transform = src.transform
                    
                print(f"🛣️ [GIS] Raster historical road network detected, executing matrix vectorization & dimensionality reduction...")
                
                rows, cols = np.where(road_data > 0)
                if len(rows) == 0:
                    print("⚠️ [GIS] No valid paths extracted from the road map!")
                    return
                
                lons, lats = transform * (cols, rows)
                
                valid = (lons >= self.min_lon) & (lons <= self.max_lon) & (lats >= self.min_lat) & (lats <= self.max_lat)
                lons = lons[valid]
                lats = lats[valid]
                
                grid_x = ((lons - self.min_lon) / (self.max_lon - self.min_lon) * self.grid_w).astype(int)
                grid_y = ((self.max_lat - lats) / (self.max_lat - self.min_lat) * self.grid_h).astype(int)
                
                grid_x = np.clip(grid_x, 0, self.grid_w - 1)
                grid_y = np.clip(grid_y, 0, self.grid_h - 1)
                
                self.road_matrix[grid_y, grid_x] = 1
                print(f"🛣️ [GIS] Miracle complete! Successfully extracted {len(lons)} valid road nodes from the scan and burned them into the pathfinding core!")
            except Exception as e:
                print(f"⚠️ [GIS] TIF road network parsing failed: {e}")

        elif filepath.endswith('.geojson'):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                road_count = 0
                for feature in data.get('features', []):
                    geom = feature.get('geometry', {})
                    if geom.get('type') == 'LineString':
                        coords = geom.get('coordinates', [])
                        for i in range(len(coords) - 1):
                            lon1, lat1 = coords[i]
                            lon2, lat2 = coords[i+1]
                            x0, y0 = self.lonlat_to_grid(lon1, lat1)
                            x1, y1 = self.lonlat_to_grid(lon2, lat2)
                            self._draw_line_on_grid(x0, y0, x1, y1, self.road_matrix)
                        road_count += 1
                print(f"🛣️ [GIS] Successfully burned {road_count} vector roads into the physics grid!")
            except Exception as e: 
                print(f"⚠️ [GIS] GeoJSON road network parsing failed: {e}")

    def is_on_road(self, lon, lat):
        if getattr(self, 'road_matrix', None) is None: 
            return False
        x, y = self.lonlat_to_grid(lon, lat)
        return self.road_matrix[y][x] == 1

    def find_path(self, start_lon, start_lat, target_lon, target_lat, unit_composition=None):
        start_pos = self.lonlat_to_grid(start_lon, start_lat)
        end_pos = self.lonlat_to_grid(target_lon, target_lat)

        if start_pos == end_pos: 
            return [(target_lon, target_lat)]

        river_penalty = 50.0 
        if unit_composition:
            if unit_composition.get("arm", 0) > 0 or unit_composition.get("art", 0) > 0:
                river_penalty = 500.0
            if unit_composition.get("eng", 0) > 0:
                river_penalty = 10.0

        open_set = []
        heapq.heappush(open_set, (0.0, start_pos))
        came_from = {}
        g_score = {start_pos: 0.0}

        def heuristic(a, b): 
            return abs(a[0] - b[0]) + abs(a[1] - b[1])

        while open_set:
            current_cost, current = heapq.heappop(open_set)
            if current == end_pos: 
                break

            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
                neighbor = (current[0] + dx, current[1] + dy)
                
                if 0 <= neighbor[0] < self.grid_w and 0 <= neighbor[1] < self.grid_h:
                    is_road = getattr(self, 'road_matrix', None) is not None and self.road_matrix[neighbor[1]][neighbor[0]] == 1
                    
                    if is_road: 
                        terrain_cost = 0.5 
                    else:
                        terrain_cost = self.path_grid[neighbor[1]][neighbor[0]]
                        if getattr(self, 'river_matrix', None) is not None:
                            if self.river_matrix[neighbor[1]][neighbor[0]] == 1:
                                terrain_cost += river_penalty
                            
                    move_cost = terrain_cost * (1.414 if dx != 0 and dy != 0 else 1.0)
                    tentative_g_score = g_score[current] + move_cost

                    if neighbor not in g_score or tentative_g_score < g_score[neighbor]:
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative_g_score
                        f_score = tentative_g_score + heuristic(neighbor, end_pos)
                        heapq.heappush(open_set, (f_score, neighbor))

        if end_pos not in came_from: 
            return [(target_lon, target_lat)]
            
        path = []
        curr = end_pos
        while curr != start_pos:
            path.append(self.grid_to_lonlat(curr[0], curr[1]))
            curr = came_from[curr]
            
        path.reverse()
        path.append((target_lon, target_lat))
        
        simplified_path = path[::1] 
        if path[-1] not in simplified_path:
            simplified_path.append(path[-1])
            
        return simplified_path

    def export_road_geojson(self):
        features = []
        for y in range(self.grid_h):
            for x in range(self.grid_w):
                if self.road_matrix[y][x] == 1:
                    lon, lat = self.grid_to_lonlat(x, y)
                    feature = {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {"type": "historic_road"}
                    }
                    features.append(feature)
        return {"type": "FeatureCollection", "features": features}


class ProvinceEngine:
    def __init__(self, geojson_path):
        self.provinces = []
        if not geojson_path or not os.path.exists(geojson_path):
            print(f"⚠️ [Geopolitics] No valid province boundary file provided: {geojson_path}")
            return
            
        try:
            with open(geojson_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for feat in data.get('features', []):
                    name = feat['properties'].get('shapeName', 'Unknown')
                    geom = feat.get('geometry', {})
                    polys = []
                    
                    if geom.get('type') == 'Polygon': 
                        polys.append(geom.get('coordinates', [])[0])
                    elif geom.get('type') == 'MultiPolygon':
                        for p in geom.get('coordinates', []): 
                            polys.append(p[0])
                            
                    self.provinces.append({'name': name, 'polygons': polys})
        except Exception as e:
            print(f"⚠️ [Geopolitics] Boundary load failed: {e}")

    def get_province(self, lon, lat):
        for prov in self.provinces:
            for poly in prov['polygons']:
                if self._point_in_polygon(lon, lat, poly): 
                    return prov['name']
        return "Unknown"

    def _point_in_polygon(self, x, y, poly):
        n = len(poly)
        inside = False
        p1x, p1y = poly[0]
        
        for i in range(n + 1):
            p2x, p2y = poly[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
            
        return inside