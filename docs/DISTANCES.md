# Westport distances

You asked for a distance tracker: how far everything is from everything else. This file explains the numbers, gives the Nine's commutes, and checks the distances the register states against the map.

The full tables are in `data/distances.json` (for the 3D map) and `data/distances.csv` (one row per pair of places, for a spreadsheet). In the 3D map, the ruler tool measures by road with the same router, so it agrees with these tables.

## What the numbers mean

- **Road miles** is the length of the fastest drive between two points, on the Atlas roads.
- **Drive minutes** is the time for that drive at a fixed speed for each kind of road. There is no traffic, no stop signs or lights, and no time lost at turns, so real drives take a little longer, often 10 to 30% in town.
- **Straight miles** is the distance as the crow flies.
- Each place is joined to the nearest road by a straight walk (the "access leg"). Road miles include that walk; drive minutes do not. For most places it is a few meters to a driveway or parking lot; the median is 54 m.
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

Ocean Highway is a trunk road (50 mph). Patriots Boulevard, River Road and Down East Road are primary (45). Harbor Drive, Mercer Street, the Dalton Bridge and downtown Jefferson Street are secondary (35). Neighborhood collectors are tertiary (30), house streets residential (25), and driveways, lanes and parking lots service roads (12).

## Missing road links on the map

The Atlas has pieces that no road reaches. Before any fix, the roads fall into 88 separate pieces; the biggest holds 73% of the road network. Whole subdivisions have streets that stop 50 to 70 m short of the collector they should join. Riverside, with the trailer park and the Hernandez house, connects to nothing: its streets stop about 300 m south of River Road, and Mercer Street stops 58 m short of Ocean Highway. Country Club Road west of the river stops 200 m short of Ocean Highway.

So the router ties each loose piece to the rest with the shortest straight link it can find over land, never across water, and only as many links as it takes to join everything: 87 links, 3.7 km in all. A link is driven at the speed of the road it starts from. After that, every place and home on the map can be reached by road, the beach included: the barrier island is joined by the Ocean Highway high bridge, which the router uses like any other road.

These are the links of 50 m or more. Each one marks a street the Atlas should draw (the full list is `gap_links` in `data/distances.json`):

| From | To | Length | At (x, y) |
|---|---|---|---|
| Country Club Road | Ocean Highway | 200 m | -4750, 1700 |
| Bobwhite Lane | unnamed service | 122 m | -3300, 6890 |
| Bayberry Court | Willow Lane | 101 m | 1930, 2645 |
| Ridgewood Drive | Kentucky Avenue | 100 m | -2912, 2766 |
| Kingston Avenue | Ward Street | 83 m | -1428, 2115 |
| Long Point Drive | Harborview Drive | 73 m | 5217, 817 |
| Plover Drive | Osprey Lane | 71 m | 7245, -1239 |
| Gull Drive | Eastwood Drive | 71 m | 3129, 1112 |
| Gull Drive | Channel Drive | 71 m | 6090, -1209 |
| Spinnaker Court | Pine Point Drive | 71 m | 5983, 84 |
| Tern Road | unnamed service | 65 m | 4827, 3781 |
| Gardenia Circle | Cardinal Lane | 61 m | -2650, 7570 |
| Briar Court | Dogwood Lane | 60 m | 1411, 4828 |
| Mulberry Lane | Honeysuckle Circle | 60 m | -1019, 5248 |
| Hickory Lane | Hickory Lane | 60 m | 1020, 4265 |
| Hemlock Lane | Holly Court | 60 m | -1004, 2945 |
| Longleaf Lane | Cherry Road | 60 m | 480, 5563 |
| unnamed service | Airport Road | 60 m | -9770, 7791 |
| Elderberry Lane | Sweetgum Drive | 60 m | 968, 2701 |
| Mercer Street | Ocean Highway | 58 m | -3600, -1750 |
| Nelson Road | Chadwick Street | 57 m | -2955, -3842 |
| Canady Lane | Small Avenue | 57 m | -1242, -3760 |
| Simmons Road | Small Avenue | 56 m | -1100, -3998 |
| Lassiter Street | Lane Lane | 56 m | -815, -3803 |
| Bufflehead Drive | Bluebird Drive | 54 m | 4759, 5175 |
| Martin Circle | Pintail Road | 54 m | 5512, 5886 |
| Killdeer Lane | Swallow Drive | 54 m | 5578, 4125 |
| Swallow Drive | Canvasback Court | 54 m | 4445, 3913 |
| Thrush Circle | Mockingbird Road | 54 m | 6039, 4773 |
| Kingfisher Drive | Mockingbird Road | 54 m | 3166, 4613 |
| Lark Court | Bluebird Drive | 54 m | 3581, 4110 |
| Dove Court | Bluebird Drive | 54 m | 3685, 3942 |
| Heron Court | Osprey Circle | 54 m | 5160, 4867 |
| Bobwhite Road | unnamed service | 53 m | 4772, 4736 |

## The Nine

Road miles / drive minutes between their homes. Charlie is at the Thompson house on Pelican Point Drive (before Book 3).

| | Calista | Lori | Reya | Nellie | Charlie | Dalton | Zane | Morgan | Elio |
|---|---|---|---|---|---|---|---|---|---|
| **Calista** |  | 5.7 / 10 | 5.1 / 10 | 7.3 / 14 | 4.7 / 9 | 6.4 / 11 | 7.4 / 13 | 7.5 / 12 | 7.3 / 14 |
| **Lori** | 5.7 / 10 |  | 1.2 / 2 | 1.7 / 3 | 2.1 / 4 | 8.6 / 14 | 1.9 / 4 | 9.7 / 15 | 1.7 / 3 |
| **Reya** | 5.1 / 10 | 1.2 / 2 |  | 2.7 / 5 | 1.5 / 3 | 8.0 / 13 | 2.2 / 4 | 9.1 / 14 | 2.7 / 5 |
| **Nellie** | 7.3 / 14 | 1.7 / 3 | 2.7 / 5 |  | 3.8 / 7 | 10.2 / 17 | 3.3 / 7 | 11.3 / 19 | 0.1 / 0 |
| **Charlie** | 4.7 / 9 | 2.1 / 4 | 1.5 / 3 | 3.8 / 7 |  | 7.6 / 12 | 3.2 / 6 | 8.6 / 14 | 3.7 / 7 |
| **Dalton** | 6.4 / 11 | 8.6 / 14 | 8.0 / 13 | 10.2 / 17 | 7.6 / 12 |  | 9.7 / 16 | 1.7 / 3 | 10.2 / 17 |
| **Zane** | 7.4 / 13 | 1.9 / 4 | 2.2 / 4 | 3.3 / 7 | 3.2 / 6 | 9.7 / 16 |  | 10.8 / 18 | 3.3 / 7 |
| **Morgan** | 7.5 / 12 | 9.7 / 15 | 9.1 / 14 | 11.3 / 19 | 8.6 / 14 | 1.7 / 3 | 10.8 / 18 |  | 11.3 / 19 |
| **Elio** | 7.3 / 14 | 1.7 / 3 | 2.7 / 5 | 0.1 / 0 | 3.7 / 7 | 10.2 / 17 | 3.3 / 7 | 11.3 / 19 |  |

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

## Canon checks

The register says Westport High "sits on Patriots Boulevard" so that Canon 2's commutes come close. Measured on the map:

| Statement | Register | Canon 2 | Map, fastest drive | Map, shortest road |
|---|---|---|---|---|
| Dalton's trailer to school | about 5 miles, over the Dalton Bridge | 4 miles | 7.5 miles, 12 minutes | 7.5 miles |
| Charlie's drive, Pelican Point Drive to school | about 4 miles, 8 to 9 minutes | | 6.2 miles, 10 minutes | 5.8 miles, 11 minutes |
| Dalton's and Charlie's homes | about 5.3 road miles | 6.3 miles | 7.6 miles, 12 minutes | 7.6 miles |

**Dalton to school.** The route does cross the Dalton Bridge, but it gets there the long way. It runs Holt Street, Jenkins Street, Mercer Street, Ocean Highway, River Road, Dalton Bridge, Jefferson Street, North Jefferson Street, Patriots Boulevard. The trailer park has no street north to River Road, so the drive goes west on Mercer Street to Ocean Highway, then back east along River Road to the bridge. That is 7.5 miles, not 5. If Jefferson Street carried on south from River Road for about 352 m to the top of Spencer Street, the trailer would be 5.2 miles and 9.9 minutes from school, over the Dalton Bridge, by Holt Street, Jenkins Street, Mercer Street, Spencer Street, Jefferson Street, Dalton Bridge, North Jefferson Street, Patriots Boulevard. That matches the register's "about 5 miles over the Dalton Bridge", so the missing piece of street is the problem, not the school's position.

**Charlie to school.** 6.2 miles and 10 minutes by Pelican Point Drive, Spinnaker Court, Harbor Drive, Sandpiper Lane, Harborview Drive, Patriots Boulevard. The register's 4 miles and 8 to 9 minutes is short by about 2.2 miles. In a straight line the school is 2.7 miles from the Thompson house; Pelican Point Drive sits in Harborview, and the drive has to go around by Harborview Drive and Patriots Boulevard. The shortest road route, 5.8 miles through slower streets, takes 11 minutes. To get 4 miles, the school would need to sit about 2.2 miles closer to Harborview along Patriots Boulevard, or the line should read "about 6 miles, 10 minutes".

**Dalton and Charlie.** 7.6 miles and 12 minutes by Holt Street, Jenkins Street, Mercer Street, Ocean Highway, River Road, Dalton Bridge, Harbor Drive, Sandpiper Lane, Palmetto Drive, Pelican Point Drive, against the register's 5.3 (Canon 2's 6.3). With the Jefferson Street piece above it would be 5.3 miles, 9.7 minutes.

A road named "Dalton Bridge" is on the map: the 515 m bridge that carries Jefferson Street over the river from downtown to River Road.

## Files

- `data/distances.json`: every gazetteer place (`place:<id>`) and every person's home (`home:<name>`; people who share a house have the same numbers) with matrices `road_m` (meters), `drive_s` (seconds) and `straight_m` (meters), in the order of `points`. A missing road route would be -1; there are none.
- `data/distances.csv`: one row per ordered pair of distinct locations (shared homes once), in miles and minutes.
- To rebuild after the Atlas or the QA fixes change: `node tools/dist/distances.mjs`. The tests are `node tools/dist/test-roadgraph.mjs`.
