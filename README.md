# CDC Sim v0 - Geospatial Strategy Wargame Engine
dedicated for Model united nation milsim
contact at davidwang.10d@gmail.com for further update advice and cooperation

CDC Sim v0 is a military-grade, Python-based Geographic Information System (GIS) wargame and simulation engine designed for tactical and strategic maneuver analysis.
Highly customized, create your own dlc to simulate, the afghan folder in dlc is for demonstrate and test purpose only

---

## 🌍 Core Architecture

The engine uses a decoupled architecture to separate the simulation core from scenario-specific data:

1. **GIS Core (`gis.py`)**: Uses `rasterio` to read and process global 90m DEM (Elevation) data, map hydrology, and compute line-of-sight (LOS) calculations.
2. **Simulation Engine (`engine.py`)**: Resolves combat, logistics, and unit movement based on real-world factors.
3. **DLC / Scenarios**: The root folder is completely decoupled from any specific theater of operation. All factions, unit attributes, and map bounds are loaded dynamically from `/dlc`.

## 🚀 Features

- **Geographic Information System (GIS)**
  - **Fast Tile Mounting**: Supports lossless mosaic processing of 90m DEM tiles.
  - **Line-of-Sight (LOS) 3D Tracing**: Uses Bresenham ray tracing to account for Earth's curvature.
  - **Hydrology & Infrastructure**: Processes rivers, roads, and administrative boundaries dynamically.
- **Dynamic Combat Physics**
  - **Unit Routing and Morale Loss**: Simulates line collapse and routing behavior.
  - **Elevation Advantages**: Boosts firepower efficiency when engaging from high ground.

---

## 🛠️ Quick Start

### Prerequisites

- Python 3.10+
- `rasterio`
- `numpy`
- `Pillow`
- `Flask`

Install dependencies:
```bash
pip install -r requirements.txt
Running the Engine
Clone the repository:

Bash
git clone [https://github.com/your-username/cdc_sim_v0.git](https://github.com/your-username/cdc_sim_v0.git)
cd cdc_sim_v0
Download your map data (e.g., SRTM 90m TIF files) and place them in the appropriate DLC folder.

Start the server:
Bash
python server.py
Open http://localhost:5000 in your browser.

📂 Creating a new DLC
To create a new theater, create a folder under /dlc and supply:

scenario.json: Theater bounds, map config, and diplomacy.

units.json: Initial Order of Battle.

weapons.json: Combat ranges.

battalions.json: Entity performance characteristics.

🤝 Contribution
We welcome PRs to expand the engine's physics and GIS capabilities! Please read the contributing guidelines before submitting.

Free for personal use, contact for commercial use
