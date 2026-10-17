# Westport distances

You asked for a distance tracker: how far everything is from everything else. This file explains the numbers, gives the Nine's commutes, and checks the distances the register states against the map.

The full tables are in `data/distances.json` (for the 3D map) and `data/distances.csv` (one row per pair of places, for a spreadsheet). In the 3D map, the ruler tool measures by road with the same router, so it agrees with these tables.

## What the numbers mean

- **Road miles** is the length of the fastest drive between two points, on the Atlas roads.
- **Drive minutes** is the time for that drive at a fixed speed for each kind of road. There is no traffic, no stop signs or lights, and no time lost at turns, so a real drive takes somewhat longer, most of all downtown.
- **Straight miles** is the distance as the crow flies.
- Each place is joined to the nearest road by a straight walk (the "access leg"): from a house to its street, or from a big building across its lot. Road miles include that walk; drive minutes do not. The median access leg is 54 m. A few points sit well away from any road, so their road miles include a long walk: the old mill site 686 m, FM radio station 575 m, public boat ramp 539 m, Community College 502 m, Lindon County Airport 465 m, Police Substation (south) 451 m, Rosewood development (waterfront lots) 421 m, Fire Station 2 313 m, McKenzie house 296 m, Target shopping center 261 m.
- Every road is two-way. Footpaths are not used. A bridge joins only the roads at its two ends, never the road or river under it. Where two roads cross on the ground, they meet.
- The QA fixes in `data/qa.json` are applied first: snapped road ends and moved place and home points.

Speeds used:

| Road | mph | Road | mph |
|---|---|---|---|
| trunk | 50 | primary | 45 |
| secondary | 35 | tertiary | 30 |
| residential | 25 | service | 12 |
| track | 10 | path | 3 |
| motorway | 65 |  |  |

On the main roads: Ocean Highway is trunk (50 mph); Down East Road, Patriots Boulevard and River Road are primary (45 mph); Island Road, Quarry Road, Coast Road, Harbor Drive, Port Road, Mercer Street, Terminal Road, Jefferson Street and Dalton Bridge are secondary (35 mph). Neighborhood collectors are tertiary (30), house streets residential (25), and driveways, lanes and parking lots are service roads (12).

## Missing road links on the map

The Atlas has pieces that no road reaches. Before any fix, the roads fall into 88 separate pieces; the biggest holds 73% of the road network. Whole subdivisions have streets that stop 50 to 70 m short of the collector they should join. Riverside, with the trailer park and the Hernandez house, connects to nothing: its streets stop 250 to 350 m south of River Road, and Mercer Street stops short short of Ocean Highway. Country Club Road west of the river stops 200 m short of Ocean Highway.

So the router ties each loose piece to the rest with the shortest straight link it can find over land, never across water, and only as many links as it takes to join everything: 18 links, 1.3 km in all. A link is driven at the speed of the road it starts from. After that, every place and home on the map can be reached by road, the beach included: the barrier island is joined by the Ocean Highway high bridge, which the router uses like any other road.

These links join whole neighborhoods or are 80 m or longer. Each one marks a piece of street the Atlas should draw:

| From | To | Length | At (x, y) |
|---|---|---|---|
| Country Club Road | Ocean Highway | 200 m | -4750, 1700 |
| Bobwhite Lane | unnamed service | 122 m | -3300, 6890 |
| Bayberry Court | Willow Lane | 101 m | 1930, 2645 |
| Long Point Drive | Harborview Drive | 73 m | 5217, 817 |

The other 14 are subdivision entrances that stop 50 to 75 m short of their collector, and driveways and lanes that stop a few meters to 50 m short of their road. All 18 are listed in `gap_links` in `data/distances.json`.

## The Nine

Road miles / drive minutes between their homes. Charlie is at the Thompson house on Pelican Point Drive (before Book 3).

| | Calista | Lori | Reya | Nellie | Charlie | Dalton | Zane | Morgan | Elio |
|---|---|---|---|---|---|---|---|---|---|
| **Calista** |  | 5.7 / 10 | 5.1 / 10 | 7.3 / 14 | 4.7 / 9 | 6.4 / 11 | 7.4 / 13 | 7.5 / 12 | 7.3 / 14 |
| **Lori** | 5.7 / 10 |  | 1.2 / 2 | 1.7 / 3 | 2.1 / 4 | 8.6 / 14 | 1.9 / 4 | 9.7 / 15 | 1.7 / 3 |
| **Reya** | 5.1 / 10 | 1.2 / 2 |  | 2.7 / 5 | 1.5 / 3 | 8.0 / 13 | 2.2 / 4 | 9.1 / 14 | 2.7 / 5 |
| **Nellie** | 7.3 / 14 | 1.7 / 3 | 2.7 / 5 |  | 3.8 / 7 | 10.2 / 17 | 3.3 / 7 | 11.3 / 19 | 0.1 / <1 |
| **Charlie** | 4.7 / 9 | 2.1 / 4 | 1.5 / 3 | 3.8 / 7 |  | 7.6 / 12 | 3.2 / 6 | 8.6 / 14 | 3.7 / 7 |
| **Dalton** | 6.4 / 11 | 8.6 / 14 | 8.0 / 13 | 10.2 / 17 | 7.6 / 12 |  | 9.7 / 16 | 1.7 / 3 | 10.2 / 17 |
| **Zane** | 7.4 / 13 | 1.9 / 4 | 2.2 / 4 | 3.3 / 7 | 3.2 / 6 | 9.7 / 16 |  | 10.8 / 18 | 3.3 / 7 |
| **Morgan** | 7.5 / 12 | 9.7 / 15 | 9.1 / 14 | 11.3 / 19 | 8.6 / 14 | 1.7 / 3 | 10.8 / 18 |  | 11.3 / 19 |
| **Elio** | 7.3 / 14 | 1.7 / 3 | 2.7 / 5 | 0.1 / <1 | 3.7 / 7 | 10.2 / 17 | 3.3 / 7 | 11.3 / 19 |  |

From each home to the places they go (road miles / drive minutes):

| | Westport High | the pier | the nine acres | Chadwick's | East's Nook Books | Westport Hospital |
|---|---|---|---|---|---|---|
| **Calista Yuen** | 3.1 / 7 | 2.3 / 4 | 8.2 / 15 | 2.0 / 4 | 1.8 / 4 | 4.9 / 9 |
| **Lori Delacroix** | 4.8 / 7 | 3.6 / 6 | 2.6 / 5 | 3.7 / 6 | 3.9 / 7 | 2.7 / 4 |
| **Reya Patel** | 5.1 / 8 | 3.1 / 5 | 3.6 / 7 | 3.1 / 5 | 3.3 / 6 | 3.0 / 5 |
| **Nellie Sullivan** | 6.3 / 10 | 5.3 / 9 | 3.0 / 6 | 5.3 / 10 | 5.6 / 10 | 4.2 / 7 |
| **Charlie Thompson** | 6.2 / 10 | 2.6 / 4 | 4.6 / 9 | 2.7 / 5 | 2.9 / 5 | 4.1 / 7 |
| **Dalton Abernathy** | 7.5 / 12 | 5.2 / 8 | 11.1 / 19 | 4.9 / 8 | 4.9 / 8 | 9.2 / 14 |
| **Zane Al-Hassan** | 4.7 / 7 | 4.7 / 9 | 4.2 / 8 | 4.8 / 9 | 5.0 / 9 | 2.7 / 4 |
| **Morgan Hernandez** | 8.5 / 14 | 6.2 / 9 | 12.2 / 20 | 6.0 / 9 | 5.9 / 9 | 10.3 / 16 |
| **Elio Rossi** | 6.2 / 10 | 5.2 / 9 | 3.0 / 6 | 5.3 / 9 | 5.5 / 10 | 4.2 / 7 |

Nellie and Elio live next door to each other on Bay Drive (40 m apart), so their rows are nearly the same. Charlie's later room over East's Nook Books is the East's Nook Books column.

Nearly every trip from one of these homes crosses one of the gap links above, so those rows depend on a street the Atlas has not drawn yet: Zane (Long Point Drive to Harborview Drive, 73 m). The other homes reach these places on the roads as drawn, except when the trip goes to one of those homes.

## Canon checks

The register says Westport High "sits on Patriots Boulevard" so that Canon 2's commutes come close. Measured on the map:

| Statement | Register | Canon 2 | Map, fastest drive | Map, shortest road |
|---|---|---|---|---|
| Dalton's trailer to school | about 5 miles, over the Dalton Bridge | 4 miles | 7.5 miles, 12 minutes | 7.5 miles |
| Charlie's drive, Pelican Point Drive to school | about 4 miles, 8 to 9 minutes | | 6.2 miles, 10 minutes | 5.8 miles, 11 minutes |
| Dalton's and Charlie's homes | about 5.3 road miles | 6.3 miles | 7.6 miles, 12 minutes | 7.6 miles |

**Dalton to school.** The route does cross the Dalton Bridge, but it gets there the long way. It runs Holt Street, Jenkins Street, Mercer Street, Ocean Highway, River Road, Dalton Bridge, Jefferson Street, North Jefferson Street, Patriots Boulevard. The trailer park has no street north to River Road, so the drive goes west on Mercer Street to Ocean Highway, then back east along River Road to the bridge. That is 7.5 miles, not 5.

If Jefferson Street carried on south from River Road for about 352 m to the top of Spencer Street, the trailer would be 5.2 miles and 9.9 minutes from school, over the Dalton Bridge, by Holt Street, Jenkins Street, Mercer Street, Spencer Street, Jefferson Street, Dalton Bridge, North Jefferson Street, Patriots Boulevard. That matches the register's "about 5 miles over the Dalton Bridge", so the register's figure assumes a street the map does not have yet. The same piece would bring Morgan's drive to school from 8.5 miles down to 4.3 miles.

**Charlie to school.** 6.2 miles and 10 minutes by Pelican Point Drive, Spinnaker Court, Harbor Drive, Sandpiper Lane, Harborview Drive, Patriots Boulevard. That is about 2.2 miles longer than the register's 4 miles. The school is 2.7 miles from the Thompson house in a straight line, but no road runs that way: the fast drive goes down to Harbor Drive, up Harborview Drive and back west along Patriots Boulevard. The shortest road route, 5.8 miles by Pelican Point Drive, Palmetto Drive, Sandpiper Lane, Harbor Drive, Jefferson Street, North Jefferson Street, Patriots Boulevard, takes 11 minutes. This drive uses only roads drawn on the Atlas, so either the line becomes "about 6 miles, 10 minutes", or the drive needs a more direct road north from Harborview.

**Dalton and Charlie.** 7.6 miles and 12 minutes by Holt Street, Jenkins Street, Mercer Street, Ocean Highway, River Road, Dalton Bridge, Harbor Drive, Sandpiper Lane, Palmetto Drive, Pelican Point Drive, against the register's 5.3 (Canon 2's 6.3). With the Jefferson Street piece above it would be 5.3 miles and 9.7 minutes, which is the register's figure.

A road named "Dalton Bridge" is on the map: the 515 m bridge that carries Jefferson Street over the river from downtown to River Road.

## Files

- `data/distances.json`: every gazetteer place (`place:<id>`) and every person's home (`home:<name>`; people who share a house have the same numbers) with matrices `road_m` (meters), `drive_s` (seconds) and `straight_m` (meters), in the order of `points`, plus the gap links. A missing road route would be -1; there are none.
- `data/distances.csv`: one row per ordered pair of distinct locations (shared homes once), in miles and minutes.
- To rebuild after the Atlas or the QA fixes change: `node tools/dist/distances.mjs`. The tests are `node tools/dist/test-roadgraph.mjs`.
