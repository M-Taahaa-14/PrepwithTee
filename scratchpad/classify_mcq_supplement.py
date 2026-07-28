"""Manual supplement: classify the 115 questions that the automated script couldn't resolve."""
import json, sqlite3

con = sqlite3.connect("data/index.db")
con.row_factory = sqlite3.Row

def lookup_ids(refs: list[str]) -> list[int]:
    """Convert ref strings like '5054/P1/s20/v1/Q5' to DB question ids.

    Drops the variant filter on purpose — the same question number appears in
    all variants (v1/v2/v3) of the same paper; we want to classify all of them.
    Uses the paper letter (P1/P2) to select the correct paper number.
    """
    ids = []
    for ref in refs:
        parts = ref.split("/")
        syllabus, paper_str, sess_yr, _variant, q_str = parts
        paper_num = int(paper_str[1:])   # P1 -> 1, P2 -> 2
        session = sess_yr[:1]
        year = 2000 + int(sess_yr[1:])
        number = int(q_str[1:])
        rows = con.execute("""
            SELECT q.id FROM questions q
            JOIN papers p ON q.paper_id = p.id
            WHERE p.syllabus=? AND p.paper=? AND p.session=? AND p.year=?
              AND q.number=?
        """, (syllabus, paper_num, session, year, number)).fetchall()
        for row in rows:
            ids.append(row[0])
        if not rows:
            print(f"  WARN: not found: {ref}")
    return ids

results = []

def add(refs, topic, confidence=0.88):
    ids = lookup_ids(refs)
    for i in ids:
        results.append({"id": i, "topic": topic, "secondary_topic": None,
                        "difficulty": None, "confidence": confidence,
                        "rationale": "MCQ manual supplement"})

# ── 5054 P1 ──────────────────────────────────────────────────────────────────
# Forces (moments, stability, balanced forces, Newton)
add(["5054/P1/s21/v1/Q8",   # beam pivoted at X, 200g mass
     "5054/P1/w22/v1/Q3",   # car on steep hill, brakes fail → resultant force → motion
     "5054/P1/w22/v2/Q4",   # same (car, brakes fail)
     "5054/P1/s23/v1/Q7",   # only two horizontal forces on trolley
     "5054/P1/w24/v1/Q13",  # uniform beam balanced by three weights
     "5054/P1/w25/v1/Q6",   # parachutist at constant speed → balanced forces
    ], "Forces")

# Pressure (least pressure = least force/area, glass objects with square bases)
add(["5054/P1/s22/v1/Q6",   # four glass objects square bases, least pressure
     "5054/P1/w23/v2/Q16",  # hammer post into ground (pressure = F/A)
    ], "Pressure")

# Physical quantities & measurement
add(["5054/P1/w22/v2/Q3",   # one-thousandth of a metre (unit prefixes)
     "5054/P1/w24/v1/Q4",   # student walks X to Y, 3.0 km/h (measuring time/speed)
     "5054/P1/s25/v1/Q5",   # measure masses and volumes of samples (density experiment → Density)
    ], "Physical quantities & measurement")

# Density (measuring mass and volume → density)
add(["5054/P1/s25/v1/Q5",   # reclassify to Density (measuring mass+volume of samples)
    ], "Density", confidence=0.90)

# Motion (car with failed brakes going downhill → accelerating)
add(["5054/P1/w22/v2/Q7",   # car at 60 km/h, driver applies brakes (stopping distance)
    ], "Motion")

# Mass & weight
add(["5054/P1/w24/v1/Q8",   # car weighs 8000 N, what is mass
    ], "Mass & weight")

# Transfer of thermal energy (evaporation rate depends on surface area)
add(["5054/P1/s25/v1/Q17",  # water in beaker at temperature T, surface area affects evaporation
    ], "Transfer of thermal energy")

# Practical electricity (heating effect)
add(["5054/P1/s24/v2/Q30",  # which appliance uses heating effect of electricity
    ], "Practical electricity")

# ── 0625 P1 ──────────────────────────────────────────────────────────────────
# Physical quantities & measurement
add(["0625/P1/m20/v2/Q1",   # area of metal sheet from rulers
     "0625/P1/s21/v3/Q1",   # plastic rod alongside ruler (length measurement)
     "0625/P1/s22/v3/Q4",   # students measure two different objects P and Q (precision/accuracy)
     "0625/P1/w24/v1/Q1",   # area of metal sheet from rulers
     "0625/P1/m25/v2/Q3",   # time for ball bearing to fall (measuring time)
     "0625/P1/w25/v3/Q1",   # girl uses ruler to measure length of metal rod (parallax)
    ], "Physical quantities & measurement")

# Motion (speed, distance-time, average speed)
add(["0625/P1/s20/v2/Q1",   # athletes finish times
     "0625/P1/w20/v2/Q2",   # car driver, four journeys
     "0625/P1/w20/v3/Q3",   # athlete runs 300m up hill in 100s (speed)
     "0625/P1/s21/v3/Q3",   # cyclist 300m up slope
     "0625/P1/w21/v2/Q2",   # graph: object moving at constant speed (d-t graph)
     "0625/P1/s22/v1/Q3",   # train at 40 m/s, man next to track (distance/speed)
     "0625/P1/s22/v2/Q3",   # same train question
     "0625/P1/s22/v3/Q3",   # same
     "0625/P1/w23/v2/Q2",   # average speed of cyclist
     "0625/P1/s24/v2/Q1",   # athletes run twice around track
     "0625/P1/s24/v3/Q3",   # four objects moving along straight line
     "0625/P1/s25/v1/Q3",   # student's times in three races
    ], "Motion")

# Mass & weight
add(["0625/P1/w20/v2/Q4",   # stone has weight 4.1 N, what is mass
     "0625/P1/w21/v3/Q3",   # force meter for weights, balance for mass
     "0625/P1/s23/v1/Q1",   # which unit is unit of weight (newton)
     "0625/P1/s23/v2/Q4",   # which statement about mass or weight not correct
     "0625/P1/w25/v1/Q5",   # which property never changes when force acts (mass)
    ], "Mass & weight")

# Forces (stability, equilibrium, balanced forces)
add(["0625/P1/w20/v2/Q8",   # stand holds heavy mass, stable (centre of mass)
     "0625/P1/s22/v1/Q8",   # forces on four moving objects, which in equilibrium
     "0625/P1/w22/v1/Q6",   # only two forces on object, which is... (equilibrium/motion)
     "0625/P1/w22/v3/Q5",   # spanner to tighten nut (moments/turning effect)
     "0625/P1/w25/v2/Q6",   # person in lift moving downwards at constant speed (balanced forces)
    ], "Forces")

# Energy, work & power
add(["0625/P1/w20/v2/Q9",   # wind farms supply electrical energy (renewable)
     "0625/P1/w22/v3/Q9",   # unit of work (joule)
     "0625/P1/w25/v3/Q9",   # woman pushes mower, which quantities (force × distance = work)
    ], "Energy, work & power")

# Thermal properties (expansion, bimetallic strip, temperature scales)
add(["0625/P1/w20/v1/Q16",  # gap left between concrete slabs (thermal expansion)
     "0625/P1/w20/v2/Q16",  # bimetallic strip controls temperature (thermal expansion)
     "0625/P1/s21/v2/Q16",  # hole drilled in metal plate (thermal expansion - hole gets bigger)
     "0625/P1/w21/v1/Q15",  # flask filled with liquid X at room temperature (expansion of liquid)
     "0625/P1/w23/v1/Q14",  # bimetallic strip (thermal expansion)
     "0625/P1/w23/v3/Q14",  # what happens when metal block heated (thermal expansion)
     "0625/P1/m24/v2/Q11",  # volume and mass of mercury as heated
     "0625/P1/s24/v1/Q11",  # Celsius to Kelvin conversion
     "0625/P1/s24/v2/Q11",  # liquid fills flask to level X (expansion)
     "0625/P1/s24/v2/Q12",  # state of water at temperatures shown
     "0625/P1/w25/v3/Q12",  # temperature 37°C in Kelvin
    ], "Thermal properties & temperature")

# Transfer of thermal energy (evaporation, radiation, cup keeps coffee warm)
add(["0625/P1/w20/v2/Q15",  # wet clothes evaporate (cooling by evaporation)
    ], "Transfer of thermal energy")

# General wave properties (diffraction, refraction at depth)
add(["0625/P1/m20/v2/Q22",  # waves from deep to shallow water (refraction)
     "0625/P1/s21/v2/Q21",  # which diagram shows waves diffracting
     "0625/P1/s24/v1/Q18",  # which diagram shows waves diffracting
     "0625/P1/s24/v3/Q17",  # waves from deep to shallow water
    ], "General wave properties")

# Kinetic particle model (states of matter, Brownian motion)
add(["0625/P1/s21/v1/Q4",   # sealed bottle with hollow glass sphere (floating/density→ Kinetic)
     "0625/P1/s21/v2/Q4",   # same
     "0625/P1/s21/v3/Q4",   # same
     "0625/P1/m22/v2/Q14",  # properties a liquid has (shape, compressibility)
     "0625/P1/s24/v3/Q10",  # pollen grain in water under microscope (Brownian motion)
     "0625/P1/s25/v1/Q12",  # liquid changes to gas, which property remains (mass)
    ], "Kinetic particle model of matter")

# ── 0625 P2 ──────────────────────────────────────────────────────────────────
# Physical quantities & measurement
add(["0625/P2/m20/v2/Q1",   # area of metal sheet
     "0625/P2/s21/v3/Q1",   # plastic rod alongside ruler
     "0625/P2/w25/v1/Q1",   # diameter of metal ball (micrometer)
    ], "Physical quantities & measurement")

# Motion
add(["0625/P2/s20/v2/Q1",   # athletes finish times
     "0625/P2/s21/v3/Q3",   # cyclist 300m up slope
     "0625/P2/w21/v2/Q2",   # graph: constant speed
     "0625/P2/m22/v2/Q3",   # car joins road, accelerates (SUVAT)
     "0625/P2/s22/v1/Q2",   # train at 40 m/s (relative speed/distance)
     "0625/P2/s22/v2/Q2",   # same
     "0625/P2/s22/v3/Q2",   # same
     "0625/P2/w23/v2/Q2",   # average speed of cyclist
     "0625/P2/s24/v1/Q7",   # stone dropped from 50m tower
     "0625/P2/s24/v3/Q3",   # athlete runs 2.4 km in 12 min
     "0625/P2/w24/v1/Q2",   # rocket at 6 km/s for 2 minutes
     "0625/P2/w24/v2/Q2",   # boy cycles then walks (average speed)
    ], "Motion")

# Mass & weight
add(["0625/P2/s23/v2/Q4",   # mass or weight statement not correct
     "0625/P2/s24/v3/Q6",   # which property cannot be changed by applying forces (mass)
    ], "Mass & weight")

# Forces (stability, moments, hose nozzle momentum)
add(["0625/P2/s20/v1/Q4",   # effects of heavy load in car (stability)
     "0625/P2/s20/v2/Q4",   # same
     "0625/P2/s20/v3/Q4",   # same
     "0625/P2/w20/v2/Q8",   # stand holds heavy mass (stability → centre of mass)
     "0625/P2/w21/v1/Q5",   # 20m bridge, uniform, supported at each end (moments)
     "0625/P2/w21/v3/Q5",   # uniform bar resting on two supports (moments)
     "0625/P2/w22/v1/Q7",   # hose nozzle (momentum / force)
    ], "Forces")

# Thermal properties (expansion, bimetallic, temperature scale)
add(["0625/P2/w20/v1/Q16",  # gap between concrete slabs (thermal expansion)
     "0625/P2/w20/v2/Q16",  # bimetallic strip
     "0625/P2/s21/v2/Q16",  # hole drilled in plate (thermal expansion)
     "0625/P2/w23/v3/Q15",  # four containers of water, more water added (heat capacity)
    ], "Thermal properties & temperature")

# Transfer of thermal energy (evaporation, cup keeps coffee warm)
add(["0625/P2/w20/v1/Q15",  # student splashes water on face (evaporation cools)
     "0625/P2/w20/v2/Q15",  # same
     "0625/P2/w20/v3/Q15",  # same
     "0625/P2/w20/v1/Q20",  # cup keeps coffee warm (insulation/radiation)
     "0625/P2/s23/v2/Q16",  # cup keeps coffee warm
     "0625/P2/s24/v1/Q13",  # wet clothes evaporate (cooling)
     "0625/P2/w23/v3/Q14",  # student splashes water on face
    ], "Transfer of thermal energy")

# General wave properties (diffraction, deep-to-shallow waves)
add(["0625/P2/s24/v1/Q16",  # which statement about waves is correct (energy transfer)
    ], "General wave properties")

# Kinetic particle model (liquid properties, changes of state)
add(["0625/P2/m24/v2/Q5",   # data about four liquids (density/properties)
     "0625/P2/s25/v2/Q10",  # substance shape determined by container (liquid)
     "0625/P2/w25/v3/Q14",  # four labelled changes of state (solid→liquid etc.)
    ], "Kinetic particle model of matter")

# Density
add(["0625/P2/m24/v2/Q5",   # four liquids data (density comparison) — also Kinetic, override with Density
    ], "Density", confidence=0.88)

# Electronics (logic gates — old syllabus, 2020-2024 papers)
add(["0625/P2/s20/v1/Q32",  # OR gate symbol
     "0625/P2/s20/v2/Q33",  # NAND gate symbol
     "0625/P2/s20/v3/Q33",  # which gates have high output when both inputs high
     "0625/P2/s22/v2/Q34",  # truth table for logic gate
     "0625/P2/s22/v3/Q34",  # truth table for logic gate
     "0625/P2/w22/v1/Q33",  # network of logic gates
    ], "Electronics")

# ── Write results ─────────────────────────────────────────────────────────────
# Remove duplicates (last write wins — keep higher confidence)
by_id = {}
for r in results:
    existing = by_id.get(r["id"])
    if existing is None or r["confidence"] >= existing["confidence"]:
        by_id[r["id"]] = r

final = sorted(by_id.values(), key=lambda r: r["id"])

# Split by syllabus/paper
def write_supplement(syllabus, paper):
    rows = []
    for r in final:
        row = con.execute(
            "SELECT p.syllabus, p.paper FROM questions q JOIN papers p ON p.id=q.paper_id WHERE q.id=?",
            (r["id"],)
        ).fetchone()
        if row and row[0] == syllabus and row[1] == paper:
            rows.append(r)
    path = f"data/batches/{syllabus}_p{paper}_supplement.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print(f"  {syllabus} P{paper} supplement: {len(rows)} rows -> {path}")

for syl, pap in [("5054", 1), ("0625", 1), ("0625", 2)]:
    write_supplement(syl, pap)

con.close()
print(f"\nTotal manual supplement records: {len(final)}")
