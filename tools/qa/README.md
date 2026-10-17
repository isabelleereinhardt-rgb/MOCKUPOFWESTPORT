# Atlas QA and alignment

`audit.mjs` checks the Westport Atlas for stray or misplaced assets and writes its corrections as data. It never edits `data/wpdata.json` or `data/gaz.json`.

## Rerun

From the repo root (Node 22, no npm packages):

```sh
node tools/qa/audit.mjs            # writes data/qa.json, docs/QA-REPORT.md and renders/qa/*.png
node tools/qa/audit.mjs --no-plots # skips the PNGs (they need python3 with Pillow)
```

A run takes a few seconds and prints a summary, the fix counts and the verification counts.

## Outputs

| File | What |
|---|---|
| `data/qa.json` | Fixes and issues. The 3D app applies the fixes at load time. The format is documented at the top of `audit.mjs`. |
| `docs/QA-REPORT.md` | The report to the author: what was checked, fixed and flagged, and the verification. |
| `renders/qa/*.png` | Before and after plots of typical fixes, drawn by `plots.py`. |

## Applying `data/qa.json`

1. Drop `fixes.remove_buildings`.
2. Swap in `fixes.replace_buildings[].poly` (meters, same vertex order). Kind, height and address stay.
3. Append `fixes.add_buildings`; the k-th one gets index `wpdata.b.length + k`.
4. Move `gaz.places` and `wpdata.pois` by id (`move_places`), people's homes by name (`move_people`) and labels by text plus `was` (`move_labels`; an optional `rot` is a new text rotation).
5. Set road vertices from `fixes.road_snaps` (`road`, `vertex` = point index, `to`).

## Rules the audit follows

- Hero homes (`docs/site-specs.json`) are never changed. Buildings that carry a named place or a character's home are never removed; if one moves, its point moves with it.
- Canon conflicts between the register, the gazetteer and the map are only flagged.
- Every new or moved footprint is checked against all roads, creeks, the rail line, piers, other buildings, open water and the marsh before it is accepted.

## Debugging

`QA_DEBUG=46 node tools/qa/audit.mjs --no-plots` prints the fix attempts for building 46. `QA_DEBUG_SITE=1` prints the site search for places that get a proposed building.
