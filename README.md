# Westport 3D

A to-scale, realistic 3D map of Westport, North Carolina (seat of Lindon County, pop. 74,529), the town of *Those Born of Shadows*. It is built on the Westport Atlas: every street, building, shoreline, address and gazetteer entry comes from the Atlas files, in meters from Courthouse Square. The Nine's homes and the town's landmarks are modeled in Blender and set on their exact Atlas footprints.

Fictional town · map data generated for TBOS · not a real survey.

## Open it

- `index.html`: the interactive map. Serve the folder over HTTP (for example `npx http-server .`) and open it in a desktop browser with WebGL 2. The first load builds the whole town and takes a few seconds.
- `homes.html`: the Nine's homes, with Blender renders, an interactive 3D model of each house and lot, and downloads.
- A hosted copy of both pages is published as a private claude.ai artifact: https://claude.ai/artifact/PNmbeKZzNHmYG8j76fDkic (share it from its Share menu). Hosts like that one cannot serve `.glb` files, so the hosted copy carries each model base64-packed as `<name>.glb.json` (`node tools/pack-models.mjs <out dir>`), and the map reads those automatically whenever it is not running from a local server.

## What the map does

- **Look.** Realistic (sun, sky, shadows, reflections on the water and glass, contact shading), Atlas and Shadows (your map tokens), and Clay (a white model). The time of day runs from sunrise to night; at night the windows light up.
- **Views.** 3D for an angled look, 2D for straight down with north up, and Street for eye level. In Street view, drag to look, use W A S D or the arrow keys to walk, Shift to run, and Esc to leave.
- **Gazetteer.** Search places, people, streets or a street address (for example `648 Oak Street`). Click a result, a label or a building to open its card.
- **The Nine.** Each home is labeled with the character's name in their color, on a dark plate with a leader to the roof. There are no X marks.
- **Distance tracker.**
  - Measure by road or in a straight line between any points you click. It gives driving and walking times and the roads taken.
  - Every card lists how far the place is from the Nine's homes and the key places (Westport High, the pier, the nine acres, Chadwick's, East's Nook Books, Courthouse Square, the hospital).
  - Distances shows a table from any place to every other place and home, plus a 9 by 9 table of the Nine's homes.
  - `data/distances.csv` has every pair.
- **Map check.** Every building, road, place and label was audited for strays and misalignment. The corrections are applied at load time without changing the Atlas files, and the panel lists every fix and every item flagged for your decision.

## How it is built

| Part | File |
|---|---|
| Atlas data (unchanged) | `data/wpdata.json`, `data/gaz.json` |
| Map check results | `data/qa.json`, report in `docs/QA-REPORT.md`, tool `tools/qa/audit.mjs` |
| Distances | `data/distances.json`, `data/distances.csv`, `docs/DISTANCES.md`, router `src/roadgraph.js`, tool `tools/dist/distances.mjs` |
| Models | `models/homes`, `models/landmarks`, `models/archetypes`, `models/vegetation`, listed in `data/models.json` (built by `tools/build-manifest.mjs`) |
| Blender scripts | `tools/blender/` (shared toolkit `tools/blender/lib/wp.py`) |
| Renders | `renders/` (Blender Cycles) |
| Surface textures | `assets/tex/` (made by `tools/textures/web_textures.py` from the same generators as the models) |
| Map code | `src/` (three.js 0.186.1) |

`src/` modules: `core.js` (data and lookups), `ground.js`, `water.js`, `roads.js`, `buildings.js`, `lots.js` (driveways and parked cars), `trees.js`, `models.js` (Blender homes and landmarks, and the loader for packed models), `archetypes.js` (close-range building models), `sky.js`, `labels.js`, `measure.js`, `ui.js`, `main.js`.

### Rebuild

```sh
pip install bpy==5.2.2                                   # Blender as a Python module
python3 tools/blender/homes/monet_williams_house.py      # any model script
node tools/qa/audit.mjs                                  # map check
node tools/dist/distances.mjs                            # distance tables
node tools/build-manifest.mjs                            # refresh data/models.json
node tools/pack-models.mjs dist                          # packed models for a host that cannot serve .glb
python3 tools/textures/web_textures.py                   # surface textures
```

### Coordinates

The Atlas frame is in meters, with x running east and y north, and the origin at Courthouse Square. In the 3D scene, x is east, z is south and y is up. Model files face their street along +Z, with the origin at the footprint center on grade. `docs/ASSET-SPEC.md` has the full conventions, and `docs/site-specs.json` the footprint, frontage and curb line of each home.

## Sources

- Westport Atlas (gaz.json, wpdata.json) and the register (`docs/westport-register.md`, from the TBOS design system).
- The author's photos: Monet's house, Lori's house, Dalton's trailer park.
- The author's Pinterest board "Those of Shadow's" (house references).
- The TBOS design system: map tokens, type and character colors.

Nothing here changes canon. Cards show each item's status from the register, and model designs are interpretations unless a photo was supplied.
