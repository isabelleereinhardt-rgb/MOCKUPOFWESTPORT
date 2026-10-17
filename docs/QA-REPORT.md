# Westport Atlas: QA and alignment report

You asked me to check the map for stray assets, make sure everything sits where it should, and line up whatever does not. This is what I checked, what I fixed and what I left for you. I did not edit `data/wpdata.json` or `data/gaz.json`. Every correction is in `data/qa.json`, which the 3D map applies when it loads, so you can review or undo each one on its own. To rerun: `node tools/qa/audit.mjs`.

## The short version

- I checked 35,990 buildings, 1,577 roads, 155 gazetteer places, 49 people's homes, 121 map POIs and 18 labels.
- I found 3,410 issues. 3,358 are fixed. 52 are flagged for you: 10 canon conflicts, 17 points that disagree with the address table, 10 road ends that need a decision, and a few small items.
- Buildings: 37 strays removed (34 mobile homes, 1 retail, 1 clubhouse, 1 shop), 2,223 nudged, trimmed, moved or turned, and 7 added where a home or a named place had no building (marked "added by QA, proposed"). Another 19 entries in add_buildings are the second halves of townhouse rows split around the lane that ran through them.
- Points: 18 place points, 2 home points and 2 labels moved. Roads: 1,070 road points snapped or pulled back.
- After the fixes, the same checks find 0 buildings on roads, 0 in water or marsh, 0 overlapping pairs, 0 on the rail line and 0 on creeks or piers.
- No hero home changed. The nine character houses keep their Atlas footprints exactly, so the house models and `docs/site-specs.json` still fit.

## Counts by check

| Check | What it means | Found | Fixed | Flagged |
|---|---|---|---|---|
| building-in-water | Footprint center, or over 25% of it, over open water | 1 | 0 | 1 |
| building-on-road | Footprint reaches more than 0.25 m into a road (bridges and footpaths ignored) | 133 | 133 | 0 |
| building-on-rail | Footprint on the rail bed | 4 | 4 | 0 |
| building-overlap | Two footprints share more than 1 m2 | 22 | 22 | 0 |
| misaligned-building | House, duplex, mobile home or townhouse 3 to 20 degrees off its street | 2,116 | 2,102 | 14 |
| road-into-building | Dead-end driveway or lane that runs into or through a building | 432 | 432 | 0 |
| road-gap | Road end that stops just short of the road it meets, or pokes just past it, without a shared point | 644 | 644 | 0 |
| road-dead-end | Main road (secondary or bigger) that stops dead in town | 8 | 0 | 8 |
| bridge-dead-end | Bridge that ends over open water | 2 | 0 | 2 |
| address-missing | Home address with no building | 1 | 1 | 0 |
| address-point-mismatch | Point and address table disagree | 17 | 0 | 17 |
| place-off-site | Place point on a road, in water, or far from any building | 18 | 18 | 0 |
| label-placement | Label outside its neighborhood or off its water | 2 | 2 | 0 |
| canon-conflict | Register, gazetteer and map disagree (flagged only) | 10 | 0 | 10 |

## What I fixed, and how

**Buildings on roads (133).** Most are houses and mobile homes whose front corner reaches a meter or two into the street. Some are whole buildings standing in a road: 22 mobile homes in a column on Sand Hill Road; 20 townhouse rows that their own service lanes run through (10 clusters built the same way); a shop in the middle of Fourth Street; Westport Hospital, which Patriots Boulevard, Down East Road and a service lane all ran through. I tried these fixes in order and kept the first one that worked: a nudge of up to 4 m straight away from the road (50); removal when the building stood mostly on the road (35); trimming the side that faces the road, keeping at least 70% and never cutting much more than the part on the road (10); a longer move into free ground, up to 10 m for an ordinary building, 60 m for a big one and 150 m for a named place (18); splitting a row in two where a lane runs through its middle (19); removing a stray that nothing else could clear (1). Before accepting a new position, I checked it against every road, neighbor, creek, the water and the marsh.

**Buildings on the rail line (4).** The main line runs straight through an apartment complex off Ocean Highway (around -6187, 3791) and crosses its parking loop twice; it also clipped the corner of a big industrial building. What happened: industrial #728 was moved 38 m, apartments #914 was moved 24 m, apartments #915 was trimmed, clubhouse #928 was removed. The complex itself still straddles the tracks, which is worth fixing at the source. Yard tracks that run up to a warehouse are rail spurs and were left alone.

**Overlapping buildings (22).** All are small (1 to 2 m2): neighboring downtown storefronts and a few houses that touch. Each pair was nudged apart by less than a meter, or the shared wall was shaved by a few tenths of a meter.

**Houses off square (2,116).** I measured every house, duplex, mobile home and townhouse within 45 m of a street against the direction of the street right in front of it. 27,583 of 29,893 were within 3 degrees. I turned 2,102 that sat 3 to 20 degrees off about their own centers to face the street (median turn 4.5 degrees). I left alone 135 houses more than 20 degrees off (corner lots and cul-de-sacs) and 58 that match their square neighbors on curves and cul-de-sac bulbs, since those were placed that way on purpose.

**Roads (1,076).** 644 road ends met another road without a shared point: 304 stopped just short of it and 340 poked just past it (median 0.5 m, mostly rounding). Each end was snapped onto the road it meets, so routing works; a side street that stops at the curb of a wide road counts as meeting it. 432 dead-end driveways and farm tracks ran into or through a building; most were cut back to stop at the wall, and where the road carries on past the building, the building moved instead. Bridges are never joined to the roads they pass over.

**Homes with no house (1).** QA added a house and moved the home points onto it. It is marked "added by QA, proposed":

- 299 Chadwick Road (Chadwick house, Wade Chadwick, Marlene Chadwick): a 14 x 12 m house, building index 36009, on the left (odd) side of the street, 321.8 m from its start, set back 8 m from the curb like nearby houses, at 6312, -3420. Chadwick Road has no numbered buildings, so the town-wide rule was used: number = 100 + 0.617 x meters from the street's end nearest Courthouse Square, odd numbers on the left. The old point was 228.2 m away, in an empty field.

**Places with nothing on the ground (6).** These points sat in the marsh, in the river or in an empty lot, with no building of their kind nearby. QA added a proposed building for each, at the point when it was dry and free, otherwise on the nearest dry, free ground by a road, and moved the point onto it:

| Place | Address | Added building | Index | At (x, y) | Moved |
|---|---|---|---|---|---|
| Skytech | 691 Union Street | 40 x 24.5 m office, 16 m tall | 36010 | 1721, 364 | at its point |
| harborfront hotel | 807 Hamilton Street | 45 x 18 m hotel, 21 m tall | 36011 | 1689, 178 | 210 m, by Hamilton Street |
| Middle School (south side) | 121 Lane Street | 85 x 22.5 m school, 8 m tall | 36012 | -2679, -3965 | 130 m, by Lane Street |
| Elementary (south side) | 2002 Simmons Street | 85 x 22.5 m school, 8 m tall | 36013 | -1555, -4003 | 70 m, by Simmons Street |
| Lindon County Government Center and Jail | 999 Country Club Road | 60 x 40 m civic, 12 m tall | 36014 | -6228, 1968 | 390 m, by Country Club Road |
| Lowe's | 1546 Ocean Highway | 110 x 75 m retail, 9 m tall | 36015 | -4998, 2573 | 70 m, by Ocean Highway |

**Buildings moved more than a nudge (20).** These stood across a road and had room nearby:

| ID | Building | Place | Moved | Was at (x, y) |
|---|---|---|---|---|
| Q0002 | hospital #46 | Westport Hospital | 124 m | 3360, 2950 |
| Q0017 | industrial #730 |  | 44 m | -6900, 5350 |
| Q0135 | industrial #728 |  | 38 m | -7300, 4900 |
| Q0016 | industrial #719 |  | 36 m | 2358, -2030 |
| Q0136 | apartments #914 |  | 24 m | -6187, 3791 |
| Q0003 | office #48 |  | 23 m | 3465, 3060 |
| Q0045 | townhouse #1178 |  | 22 m | 3167, 3076 |
| Q0018 | civic #738 | Westport Yacht Club | 16 m | 4635, -363 |
| Q0098 | shop #3566 (430 Fourth Street) |  | 13 m | 186, 419 |
| Q0004 | civic #51 | Fire Station 4 | 12 m | 4594, 1650 |
| Q0095 | shop #3223 |  | 12 m | -1270, -19 |
| Q0020 | retail #748 |  | 11 m | 4521, 1743 |
| Q0021 | office #772 | Starbucks | 10 m | -153, 3626 |
| Q0083 | mobile #2627 |  | 8.6 m | -110, 8208 |
| Q0085 | mobile #2631 |  | 8.1 m | -114, 8230 |
| Q0084 | mobile #2629 |  | 8 m | -112, 8219 |
| Q0086 | mobile #2633 |  | 7.1 m | -116, 8242 |
| Q0006 | industrial #59 | the crab house | 6 m | -1252, 18 |
| Q0005 | civic #57 | water tower (FOUNDED 1625) | 5.7 m | 1150, 2350 |
| Q0026 | clubhouse #879 |  | 5.5 m | 1494, 3303 |

**Place points moved (18).** The people who live at a moved home point move with it.

| Place | Address | Was at | Now at | Why |
|---|---|---|---|---|
| Westport Hospital | 1422 Patriots Boulevard | 3360, 2950 | 3318, 2833 | Follows its building #46, which QA moved off a road or neighbor |
| Fire Station 4 | 356 Patriots Boulevard | 4600, 1650 | 4610, 1656 | Follows its building #51, which QA moved off a road or neighbor |
| water tower (FOUNDED 1625) | 592 Mariner Drive | 1150, 2350 | 1145, 2353 | Follows its building #57, which QA moved off a road or neighbor |
| the crab house | 1352 Harbor Drive | -1252, 18 | -1252, 12 | Follows its building #59, which QA moved off a road or neighbor |
| gun shop (the billboard) | 2272 Ocean Highway | -5483, 3807 | -5483, 3808 | Follows its building #98, which QA moved off a road or neighbor |
| Westport Yacht Club | 1660 Eastwood Drive | 4650, -350 | 4640, -338 | Follows its building #738, which QA moved off a road or neighbor |
| Starbucks | 1592 North Jefferson Street | -153, 3626 | -143, 3626 | Follows its building #772, which QA moved off a road or neighbor |
| Westport High School | 378 Gardenia Circle | 420, 4060 | 312, 3886 | Was 118.7 m from the nearest building; moved onto the nearest school building, #18 |
| Walmart Supercenter | 800 Ocean Highway | -4560, 1327 | -4613, 1306 | Sat on the surface of road 85 (unnamed service); moved onto the nearest retail building, #62 |
| Target shopping center | 2382 Ocean Highway | -5491, 4023 | -5396, 4102 | Was 105.8 m from the nearest building; moved onto the nearest retail building, #81 |
| Harborview shopping center | 189 Shore Drive | 4450, 1600 | 4418, 1675 | Was 68 m from the nearest building; moved onto the nearest retail building, #744 |
| Westport Acres shopping center (Food Lion) | 1818 Mariner Drive | 1248, 4281 | 1174, 4252 | Was 66.1 m from the nearest building; moved onto the nearest retail building, #752 |
| Chadwick house | 299 Chadwick Road | 6250, -3200 | 6312, -3420 | Moved onto the house added by QA for 299 Chadwick Road (proposed) |
| harborfront hotel | 807 Hamilton Street | 1897, 208 | 1689, 178 | Moved onto the hotel added by QA (proposed) |
| Middle School (south side) | 121 Lane Street | -2550, -3950 | -2679, -3965 | Moved onto the school added by QA (proposed) |
| Elementary (south side) | 2002 Simmons Street | -1600, -3950 | -1555, -4003 | Moved onto the school added by QA (proposed) |
| Lindon County Government Center and Jail | 999 Country Club Road | -6150, 2350 | -6228, 1968 | Moved onto the civic added by QA (proposed) |
| Lowe's | 1546 Ocean Highway | -5068, 2573 | -4998, 2573 | Moved onto the retail added by QA (proposed) |

**Labels (2).** Water label "Westport River": its anchor sat on the marsh, not open water; its text ran 56.8 degrees across the river instead of along it. Moved it 180 m onto open water and turned it from -28 to 28.8 degrees. Water label "the Marsh": its anchor sat on dry land, not the marsh. Moved it 790 m onto the marsh.

**Next to the hero homes.** The hero footprints did not change, but QA touched a few neighbors. The lot rectangles in `docs/site-specs.json` were measured from the old neighbors; every change is small, so the lots still fit:

- thompson-house: #22168 turned square.
- abernathy-trailer: #175 moved (center 3.6 m), #177 turned square, #174 turned square, #179 moved (center 2.7 m), #178 turned square.

## Flagged for your decision

Canon conflicts are only flagged: I changed nothing that the register or your books settle.

| ID | Conflict | Atlas x, y |
|---|---|---|
| Q3401 | The register puts "the motel on the Highway" at 654 Ocean Highway, but Steven Villanueva's room 12 there is listed at 642 Ocean Highway. Both points are the same spot, motel #99. One number should change; a motel has one street number, and the room number is separate. | -4274, 1180 |
| Q3402 | The Delacroix house is "the big house on the water" (Book 1 Spine), but its lot at 3064 Harbor Drive (building 23936) is about 165 m from open water. Either pick a waterfront lot on Harbor Drive or drop "on the water". | 5519, -635 |
| Q3403 | Golden Corral and Waffle House share one address, 1698 Ocean Highway, though their points are 129.3 m apart. Two businesses on separate lots need two numbers. | -5117, 2846 |
| Q3404 | The register says the pier and pier bar (locked) stand "near the bait shop and the crab house", and that Chadwick's is "near the bait shop and the pier". On the map the pier is 1617 m from Langford's Bait & Tackle and 1573 m from the crab house; Chadwick's is 304 m from the pier but 1381 m from the bait shop. That is about a mile along Harbor Drive, not "near". Moving the bait shop and crab house east, to the 300s to 500s of Harbor Drive, would fix it. | 305, -209 |
| Q3405 | 49 streets that run through downtown (Harbor Drive, Main Street, Second Street, Third Street, Fourth Street, Fifth Street and others) are numbered outward from Courthouse Square in both directions, so the same range of numbers appears on both halves with no East or West in the name. That is why East's Nook Books, Manning's Jewelry, Charlie's room over East's Nook Books sit on buildings numbered differently from their addresses: the Atlas puts their number on the other half of the street. Adding East/West Main Street (and so on) would make every downtown address unique. | -308, 191 |

Smaller notes:

- Q3406: The Chadwick house is "on the family land by the field". Chadwick Road has no numbered buildings; by the town's numbering, 299 falls about 321.8 m along the road, 393 m from the middle of the nine acres (516 Chadwick Road). If the house should sit at the field, a number in the 500s fits better.
- Q3407: The McKenzie farmhouse is listed at 2282 Oak Grove Road, but no Atlas building has that address. The point sits on house #3158 (no street number), 310.9 m off Oak Grove Road beside the stretch numbered about 2270, so the number fits a farmhouse set well back from the road. It is outside the city limits, which matches "just outside town". QA keeps the point on that building.
- Q3408: The register says Westport High "sits on Patriots Boulevard", but its address is 378 Gardenia Circle and the school is 224 m from Patriots Boulevard.
- Q3409: A street is named "Lane Lane", which reads as a generator slip. Rename it.
- Q3410: 2 places that are buildings have no street address yet: Police Substation (south), FM radio station.

Map items I left alone because a fix needs your call:

| ID | Check | Detail | Atlas x, y |
|---|---|---|---|
| Q0161 | misaligned-building | house #16358 (143 Linden Drive) sits 12.6 degrees off Linden Drive, but turning it is blocked: it would overlap a neighbor. Left as is. | 1657, 4145 |
| Q0162 | misaligned-building | house #16381 (256 Linden Drive) sits 16.6 degrees off Linden Drive, but turning it is blocked: it would overlap a neighbor. Left as is. | 1684, 4423 |
| Q0163 | misaligned-building | house #16861 (132 Aspen Circle) sits 12.4 degrees off Aspen Circle, but turning it is blocked: it would overlap a neighbor. Left as is. | 25, 4072 |
| Q0164 | misaligned-building | house #16873 (466 Laurel Road) sits 13.7 degrees off Laurel Road, but turning it is blocked: it would overlap a neighbor. Left as is. | -137, 5091 |
| Q0165 | misaligned-building | house #17097 (116 Honeysuckle Circle) sits 16.8 degrees off Honeysuckle Circle, but turning it is blocked: it would overlap a neighbor. Left as is. | -916, 4678 |
| Q0166 | misaligned-building | house #22989 (1472 Oak Point Drive) sits 14.2 degrees off Oak Point Drive, but turning it is blocked: it would overlap a neighbor. Left as is. | 6059, 306 |
| Q3353 | road-dead-end | Harbor Drive (secondary, road 16) stops dead, 110 m short of road 45 (Pinecrest Road). A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | -1750, 40 |
| Q3354 | road-dead-end | Mercer Street (secondary, road 23) stops dead, 57.7 m short of road 2 (Ocean Highway). A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | -3600, -1750 |
| Q3355 | road-dead-end | Mercer Street (secondary, road 23) stops dead. A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | 1700, -2050 |
| Q3356 | road-dead-end | Quarry Road (secondary, road 24) stops dead, 24.7 m short of road 2 (Ocean Highway). A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | -3600, -1950 |
| Q3357 | road-dead-end | Port Road (secondary, road 29) stops dead, 81.5 m short of road 2 (Ocean Highway). A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | -3420, -3250 |
| Q3358 | road-dead-end | Port Road (secondary, road 30) stops dead, 68.1 m short of road 66 (Terminal Road). A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | 3000, -3100 |
| Q3359 | road-dead-end | Down East Road (primary, road 42) stops dead, 17.5 m short of road 114 (unnamed service). A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | 3300, 2980 |
| Q3360 | road-dead-end | Terminal Road (secondary, road 66) stops dead, 38.2 m short of road 30 (Port Road). A main road should end at another road. QA only closes small gaps; this needs a new piece of road or a decision. | 2950, -3150 |
| Q3361 | bridge-dead-end | Bridge road 82 (unnamed service, service) ends over open water and joins nothing there: a bridge to nowhere. QA does not delete roads; it should be removed or carried to the far bank. | -6100, 2232 |
| Q3362 | bridge-dead-end | Bridge road 318 (Ash Street, residential) ends over open water and joins nothing there: a bridge to nowhere. QA does not delete roads; it should be removed or carried to the far bank. | 1437, -113 |

Minor items left as they are: Q0001 (shop #58: its center is over open water, but it stands on a pier, so it stays as a pier building); Q0388 (mobile #181, 4.5 degrees off; turning it would hit a neighbor or road); Q0389 (mobile #205, 4.5 degrees off; turning it would hit a neighbor or road); Q0390 (mobile #2635, 6.9 degrees off; turning it would hit a neighbor or road); Q0391 (house #13421 (390 Pecan Drive), 3.9 degrees off; turning it would hit a neighbor or road); Q0392 (house #14471 (287 Wisteria Circle), 3.2 degrees off; turning it would hit a neighbor or road); Q0393 (house #15550 (176 Elderberry Lane), 3.5 degrees off; turning it would hit a neighbor or road); Q0394 (house #16167 (463 Hickory Lane), 6 degrees off; turning it would hit a neighbor or road); Q0395 (house #22198 (113 Sandpiper Lane), 4 degrees off; turning it would hit a neighbor or road).

Points that sit on a different building than the address table gives (kept, since the point usually shows what you meant):

- Q3364: Food Lion (downtown) (food-lion-downtown): the point sits on retail #12, while "673 Third Street" is on shop #3287 (673 Third Street), 1846.9 m away. The point is taken as the intent; nothing moved.
- Q3365: Elementary (Pinecrest) (es-pinecrest): the Atlas gives "431 Wedgewood Drive" to house #11009 (431 Wedgewood Drive), 154.6 m away, which is not a school building. Two places share one address; the point was not moved onto it.
- Q3366: Westport Elementary (es-acres-w): the Atlas gives "185 Laurel Road" to house #14734 (185 Laurel Road), 219 m away, which is not a school building. Two places share one address; the point was not moved onto it.
- Q3367: Elementary (south side) (es-south): the Atlas gives "2002 Simmons Street" to house #32274 (2002 Simmons Street), 178.2 m away, which is not a school building. Two places share one address; the point was not moved onto it.
- Q3368: the old Iron Rail dining car (closed) (iron-rail): the point sits on office #126, while "1059 Railroad Street" is on house #30972 (1059 Railroad Street), 189.7 m away. The point is taken as the intent; nothing moved.
- Q3369: Riverside Mobile Home Community (riverside-mhc): the point sits on mobile #469, while "1118 Holt Street" is on mobile #31446 (1118 Holt Street), 261.3 m away. The point shows the intent: a lot inside a community that shares one street address. Kept as info; nothing moved.
- Q3370: Westport Acres shopping center (Food Lion) (acres-center): the Atlas gives "1818 Mariner Drive" to house #17758 (1818 Mariner Drive), 116.4 m away, which is not a shop building. Two places share one address; the point was not moved onto it.
- Q3371: East's Nook Books (easts-nook): the point sits on shop #3800 (228 Main Street), which the Atlas numbers "228 Main Street", not "226 Main Street"; that exact address belongs to shop #3413 (226 Main Street), 407.3 m away (numbers climb both ways from Courthouse Square, so that number falls on the other side of Courthouse Square). The point is taken as the intent; nothing moved.
- Q3372: Manning's Jewelry (mannings): the point sits on shop #3687 (510 Main Street), which the Atlas numbers "510 Main Street", not "508 Main Street"; that exact address belongs to shop #3491 (508 Main Street), 1320.2 m away (numbers climb both ways from Courthouse Square, so that number falls on the other side of Courthouse Square). The point is taken as the intent; nothing moved.
- Q3373: Freeman's Records (freemans): the point sits on shop #4221 (155 Lincoln Street), which the Atlas numbers "155 Lincoln Street", not "513 Main Street". The point is taken as the intent; nothing moved.
- Q3374: Green's Barbershop (greens-barbershop): the point sits on shop #4362 (239 Jefferson Street), which the Atlas numbers "239 Jefferson Street", not "122 Second Street". The point is taken as the intent; nothing moved.
- Q3375: Xu's Karate (xu-karate): the point sits on shop #3953 (300 Cedar Street), which the Atlas numbers "300 Cedar Street", not "258 Third Street". The point is taken as the intent; nothing moved.
- Q3376: Abernathy trailer, lot 47 (home-abernathy): the point sits on mobile #173, while "1118 Holt Street" is on mobile #31446 (1118 Holt Street), 113.6 m away. The point shows the intent: a lot inside a community that shares one street address. Kept as info; nothing moved.
- Q3377: Charlie's room over East's Nook Books (home-charlie3): the point sits on shop #3800 (228 Main Street), which the Atlas numbers "228 Main Street", not "226 Main Street"; that exact address belongs to shop #3413 (226 Main Street), 407.3 m away (numbers climb both ways from Courthouse Square, so that number falls on the other side of Courthouse Square). The point is taken as the intent; nothing moved.
- Q3378: Charlie Thompson's later home: the point sits on shop #3800 (228 Main Street), which the Atlas numbers "228 Main Street", not "226 Main Street"; that exact address belongs to shop #3413 (226 Main Street), 407.3 m away (numbers climb both ways from Courthouse Square, so that number falls on the other side of Courthouse Square). The point is taken as the intent; nothing moved.
- Q3379: Dalton Abernathy's home: the point sits on mobile #173, while "1118 Holt Street" is on mobile #31446 (1118 Holt Street), 113.6 m away. The point shows the intent: a lot inside a community that shares one street address. Kept as info; nothing moved.
- Q3380: Lisa Abernathy's home: the point sits on mobile #173, while "1118 Holt Street" is on mobile #31446 (1118 Holt Street), 113.6 m away. The point shows the intent: a lot inside a community that shares one street address. Kept as info; nothing moved.

## Most important items

| ID | Item | Address or name | Atlas x, y | What happened |
|---|---|---|---|---|
| Q3363 | Chadwick house, Wade Chadwick, Marlene Chadwick: no house at 299 Chadwick Road | 299 Chadwick Road | 6250, -3200 | Added by QA, proposed: a 14 x 12 m house on the left side of Chadwick Road, 321.8 m from its start (Chadwick Road has no numbered buildings, so the town-wide rule was used: number = 100 + 0.617 x meters from the street's end nearest Courthouse Square, odd numbers on the left), and moved the points 228.2 m onto it |
| Q3381 | Skytech: no building | 691 Union Street | 1721, 364 | Added by QA, proposed: a 40 x 24.5 m office at its point, and moved the point onto it |
| Q3382 | harborfront hotel: no building | 807 Hamilton Street | 1897, 208 | Added by QA, proposed: a 45 x 18 m hotel on the nearest dry, free ground by Hamilton Street, 210 m from the old point, and moved the point onto it |
| Q3383 | Middle School (south side): no building | 121 Lane Street | -2550, -3950 | Added by QA, proposed: a 85 x 22.5 m school on the nearest dry, free ground by Lane Street, 130 m from the old point, and moved the point onto it |
| Q3384 | Elementary (south side): no building | 2002 Simmons Street | -1600, -3950 | Added by QA, proposed: a 85 x 22.5 m school on the nearest dry, free ground by Simmons Street, 70 m from the old point, and moved the point onto it |
| Q3385 | Lindon County Government Center and Jail: no building | 999 Country Club Road | -6150, 2350 | Added by QA, proposed: a 60 x 40 m civic on the nearest dry, free ground by Country Club Road, 390 m from the old point, and moved the point onto it |
| Q3386 | Lowe's: no building | 1546 Ocean Highway | -5068, 2573 | Added by QA, proposed: a 110 x 75 m retail on the nearest dry, free ground by Ocean Highway, 70 m from the old point, and moved the point onto it |
| Q0002 | Westport Hospital stood on Patriots Boulevard | 1422 Patriots Boulevard | 3360, 2950 | Moved 124 m to the nearest free ground, clear of every road it touched (across a main road; there was no room on its own side) |
| Q0004 | Fire Station 4 stood on Patriots Boulevard | 356 Patriots Boulevard | 4594, 1650 | Moved 12 m to the nearest free ground |
| Q0005 | water tower (FOUNDED 1625) stood on Mariner Drive | 592 Mariner Drive | 1150, 2350 | Moved 5.7 m to clear it (more than a 4 m nudge, into free ground) |
| Q0006 | the crab house stood on Harbor Drive | 1352 Harbor Drive | -1252, 18 | Moved 6 m to clear it (more than a 4 m nudge, into free ground) |
| Q0009 | movie theater (12 screens) stood on Patriots Boulevard | 2760 Ocean Highway | -5825, 4566 | Trimmed 8.5 m off the side facing it (keeps 91% of that side) |
| Q0018 | Westport Yacht Club stood on a service road | 1660 Eastwood Drive | 4635, -363 | Moved 16 m to the nearest free ground |
| Q0021 | Starbucks stood on North Jefferson Street | 1592 North Jefferson Street | -153, 3626 | Moved 10 m to the nearest free ground |
| Q0131 | gun shop (the billboard) stood on Sycamore Street | 2272 Ocean Highway | -5483, 3807 | Shifted 1.1 m away from it |
| Q3387 | Westport High School: point off its building | 378 Gardenia Circle | 420, 4060 | Moved the point 205.3 m onto school #18, the nearest school building |
| Q3388 | Walmart Supercenter: point off its building | 800 Ocean Highway | -4560, 1327 | Moved the point 57.9 m onto retail #62, the nearest retail building big enough for it |
| Q3389 | Target shopping center: point off its building | 2382 Ocean Highway | -5491, 4023 | Moved the point 123.7 m onto retail #81, the nearest retail building |
| Q3390 | Harborview shopping center: point off its building | 189 Shore Drive | 4450, 1600 | Moved the point 81.5 m onto retail #744, the nearest retail building |
| Q3391 | Westport Acres shopping center (Food Lion): point off its building | 1818 Mariner Drive | 1248, 4281 | Moved the point 79.7 m onto retail #752, the nearest retail building |
| Q3361 | Bridge that ends over the water (the county center driveway) | unnamed service | -6100, 2232 | flagged |
| Q3362 | Bridge that ends over the water (the county center driveway) | Ash Street | 1437, -113 | flagged |
| Q3353 | Harbor Drive stops dead | Harbor Drive | -1750, 40 | flagged |
| Q3354 | Mercer Street stops dead | Mercer Street | -3600, -1750 | flagged |
| Q3355 | Mercer Street stops dead | Mercer Street | 1700, -2050 | flagged |
| Q3356 | Quarry Road stops dead | Quarry Road | -3600, -1950 | flagged |
| Q3357 | Port Road stops dead | Port Road | -3420, -3250 | flagged |
| Q3358 | Port Road stops dead | Port Road | 3000, -3100 | flagged |
| Q3359 | Down East Road stops dead | Down East Road | 3300, 2980 | flagged |
| Q3360 | Terminal Road stops dead | Terminal Road | 2950, -3150 | flagged |
| Q0135 | industrial #728 on the rail line |  | -7300, 4900 | Moved 38 m to the nearest free ground, clear of every road it touched |
| Q0136 | apartments #914 on the rail line |  | -6187, 3791 | Moved 24 m to the nearest free ground, clear of every road it touched |
| Q0137 | apartments #915 on the rail line |  | -6197, 3846 | Trimmed 11.5 m off the side facing it (keeps 77% of that side) |
| Q0138 | clubhouse #928 on the rail line |  | -6055, 3628 | No nudge, move or trim clears it without a new conflict, so this stray was removed |
| Q3399 | Label "Westport River" off its water | Westport River | -7600, 3150 | Moved it 180 m onto open water and turned it from -28 to 28.8 degrees |
| Q3400 | Label "the Marsh" off its water | the Marsh | 8700, 2500 | Moved it 790 m onto the marsh |
| Q3401 | Canon: The register puts "the motel on the Highway" at 654 Ocean Highway, but Steven Villanueva's room 12 there is listed at 642 Ocean Highway |  | -4274, 1180 | flagged |
| Q3402 | Canon: The Delacroix house is "the big house on the water" (Book 1 Spine), but its lot at 3064 Harbor Drive (building 23936) is about 165 m from open water |  | 5519, -635 | flagged |
| Q3403 | Canon: Golden Corral and Waffle House share one address, 1698 Ocean Highway, though their points are 129.3 m apart |  | -5117, 2846 | flagged |
| Q3404 | Canon: The register says the pier and pier bar (locked) stand "near the bait shop and the crab house", and that Chadwick's is "near the bait shop and the pier" |  | 305, -209 | flagged |
| Q3405 | Canon: 49 streets that run through downtown (Harbor Drive, Main Street, Second Street, Third Street, Fourth Street, Fifth Street and others) are numbered outward from Courthouse Square in both directions, so the same range of numbers appears on both halves with no East or West in the name |  | -308, 191 | flagged |

## Verification

After applying every fix in `data/qa.json` to the Atlas, I ran the building checks again on the result, including the added buildings:

| Check | Remaining | Not covered by a flag |
|---|---|---|
| Buildings on roads | 0 | 0 |
| Buildings on the rail line | 0 | 0 |
| Buildings on creeks | 0 | 0 |
| Buildings on piers | 0 | 0 |
| Buildings over open water | 0 | 0 |
| Buildings in the marsh | 0 | 0 |
| Overlapping pairs (over 1 m2) | 0 | 0 |

Nothing remains. The pier bar building stands over the water on its pier, as it should, and is not counted.

The footprints for this check are rebuilt from the fix lists exactly as written to `data/qa.json`. I also checked that all 644 snapped road ends sit on the road they join (within 2 cm), that no hero home appears in the fixes, and that no building is both removed and replaced.

## How the checks work

- Roads are measured with these half-widths: trunk 7.5 m, primary 6.5, secondary 5.5, tertiary 4.5, residential 3.75, service 2.75, track 2, motorway 9. Bridges (raised) and footpaths are ignored for buildings. An intrusion counts when it is deeper than 0.25 m, because Atlas coordinates are rounded to half a meter (buildings) and a meter (roads). The rail bed is 2.5 m each side of the main line and 2 m for yard tracks; creeks 3 m; piers 2 m and the downtown boardwalk 3 m.
- Land and water come from the Atlas land polygons (outer ring land, inner rings water), and the marsh from the marsh polygons. Footprints are sampled on a 6 x 6 grid for water and marsh, and 10 x 10 for roads.
- Overlaps are exact convex polygon intersections. A spatial grid keeps the whole run to a few seconds.
- A road end counts as a gap when it is 0.3 to 4 m from another road, or within the other road's half-width plus 1 m (a side street that stops at the curb of a wide road). Ends are snapped to a vertex of the other road when one is within 1.5 m, otherwise onto its centerline.
- Street numbers in the Atlas follow one rule: a house number is about 100 + 0.617 x its distance in meters from the street's end nearest Courthouse Square (1,000 per mile), with odd numbers on the left going outward (9,422 of 14,101 odd numbers). I fitted this on 351 streets, and it is what placed the added Chadwick house.
- 72 places sit on a civic or commercial building that has no number in the Atlas address table. For those the gazetteer address is the only one, which is fine.
- Hero homes (`docs/site-specs.json`) are never changed. Buildings that carry a named place or a character's home are never removed; when one had to move off a road, its point moved with it. Landmark builders (the water tower, for example) should place their models on the footprint from `data/qa.json` when it lists the building.

## Pictures

- `renders/qa/01-chadwick-house-added.png`: Chadwick house: 299 Chadwick Road had no building. Added by QA, proposed (green); the home point moves onto it.
- `renders/qa/02-townhouse-lane.png`: Townhouse rows that their own service lane runs through. Each row is split in two around the lane (orange = the kept half, green = the other half).
- `renders/qa/03-mobiles-on-road.png`: Mobile homes standing on Sand Hill Road. Red = removed (standing on the road); orange = moved clear or turned square.
- `renders/qa/04-water-tower.png`: Water tower footprint on Mariner Drive. Moved clear of the road; the landmark point moves with it.
- `renders/qa/05-county-center.png`: County Government Center: point in the river, bridge stub to nowhere. Added by QA, proposed (green) on the nearest dry ground; the bridge stub is flagged.
- `renders/qa/06-driveway-into-building.png`: Driveway running through fire-6 (civic #53). The driveway is cut back so it stops at the wall (road_snaps); the part through and past the building goes.
- `renders/qa/07-misaligned-houses.png`: Houses turned square to their street. Orange = turned about its center; faint outline = before.
- `renders/qa/08-labels.png`: Label "Westport River" off its water. Moved onto the water it names.

In each picture, the left half is the Atlas as it is and the right half has the fixes applied. Red means removed, orange changed, green added by QA, and blue dots are moved points (a thin line joins each to where it was).
