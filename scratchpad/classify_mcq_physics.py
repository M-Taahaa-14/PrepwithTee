"""
Session classify for 5054 P1, 0625 P1, 0625 P2 MCQ questions.

Reads questions JSON, applies refined keyword rules for Physics MCQ,
and writes results files ready for `pipeline.classify --backend session --ingest`.

Only reclassifies questions where heuristic confidence < 0.8 OR no classification.
"""
import json, re, sqlite3

# ── Physics topic rules ──────────────────────────────────────────────────────
# Each rule: (patterns_in_text, topic). Matched in order; first hit wins.
# Patterns are substrings (lowercased).

RULES_5054 = [
    # Physical quantities & measurement
    (["micrometer","vernier","stopwatch","stop-watch","stop watch","parallax",
      "zero error","precision","accuracy","significant figure","base unit",
      "scalar","vector quantity","resultant","magnitude","direction",
      "centre of mass","centre of gravity","vectors add","which quantity is a vector",
      "which quantity is not a vector","vector and scalar","which is a scalar",
      "which is a vector","3.0 n force and a 4.0 n","angle between the","not possible",
      "rule or","ruler or","metre rule","measuring cylinder","spring balance",
      "reading on the", "parallax","timing","difference in time","stop-watches show",
      "decimal places","significant"],
     "Physical quantities & measurement"),

    # Motion
    (["speed–time graph","velocity–time graph","distance–time graph",
      "speed-time","velocity-time","distance-time","uniform velocity",
      "constant velocity","uniform acceleration","suvat",
      "deceleration","displacement","v = u","v² = u²","v^2","s = ut",
      "projectile","free fall","terminal velocity","drag force",
      "what is the greatest speed","what is the speed","what is the velocity",
      "accelerates from rest","decelerates to rest","uniform deceleration"],
     "Motion"),

    # Forces
    (["newton's third law","newton's first law","newton's second law",
      "resultant force","unbalanced force","balanced force",
      "friction acts","friction on","direction does friction",
      "force causes him to turn","centripetal","circular motion",
      "motorcyclist","banked","in equilibrium","moment","turning effect",
      "principle of moments","sum of clockwise","anticlockwise",
      "resolution of force","horizontal component","vertical component",
      "what is the force opposing","action and reaction","pair of forces",
      "a man with an open parachute","parachute falls","newton's law pair",
      "weight of the car","constant speed along","driving force",
      "elastic cord","hooke's law","limit of proportionality",
      "the force opposing","a 3.0 n force and a 4.0 n",
      "resultant r of","resultant of two","add two forces","resultant of a",
      "object in equilibrium","centre of mass below","model toy","balances on"],
     "Forces"),

    # Momentum
    (["momentum","impulse","conservation of momentum","collision","collide",
      "a ball strikes","strikes the wall","crumple zone","before and after collision",
      "the total momentum","change in momentum","force = change","impulse =",
      "elastic collision","inelastic collision"],
     "Momentum"),

    # Energy, work & power
    (["gravitational potential energy","kinetic energy","work done","work is done",
      "watt","kilowatt","power output","useful energy","efficiency","wasted energy",
      "energy transfer","energy stored","elastic potential","strain energy",
      "conservation of energy","energy is converted","what is the power",
      "average power","a weightlifter","lifts a mass","work done by force",
      "work done against","what is the work","how much work","gain in",
      "gravitational pe","g.p.e","gpe","nuclear energy","solar energy",
      "renewable energy","non-renewable","fossil fuel","wind turbine",
      "hydroelectric","coal-fired power","power station","turbine turns",
      "generator","electromagnetic induction produces electrical",
      "the battery of an electric car","energy is transferred to the battery",
      "useable energy","charged with a current","the efficiency of",
      "energy released by","how much energy"],
     "Energy, work & power"),

    # Pressure
    (["pressure","pascal","manometer","barometer","mercury column",
      "atmospheric pressure","hydraulic","boyle's law","gas law",
      "pressure of the gas","volume of the gas","piston","cylinder contains",
      "pressure on the fish","total pressure on","pressure at a depth",
      "density of the water","depth of","immersed in","submerged in",
      "pressure in the syringe","syringe","the pressure inside",
      "pressure acts","gas at pressure","height of mercury",
      "a fish is swimming","lake","supports a column"],
     "Pressure"),

    # Density
    (["density","mass per unit volume","measuring cylinder","measuring glass",
      "rise to","reading on the measuring","what is the density",
      "piece of copper is heated","mass of the metal","volume of",
      "upthrust","archimedes","floating","sinks","floats",
      "equal volumes","same volume","different densities"],
     "Density"),

    # Kinetic particle model
    (["kinetic model","kinetic theory","particle model","molecule","molecules",
      "brownian motion","diffusion","random motion","forces between",
      "separation of molecules","particle moves","bombardment",
      "gas molecules","intermolecular","liquid has a fixed volume",
      "does not have a fixed shape","vibrate at fixed","free to move within",
      "change of state","evaporation","boiling","condensation",
      "latent heat","specific latent","melting point","melts",
      "melt wax","solid at its melting","thermal energy is used to turn",
      "water at 100","steam at 100","forces between the molecules decrease",
      "separation of the molecules increases","mass of molecules",
      "molecules collide with the walls","molecules per unit volume",
      "the air is heated","speed of the molecules"],
     "Kinetic particle model of matter"),

    # Thermal properties
    (["thermometer","specific heat capacity","heat capacity",
      "thermal capacity","thermal energy","temperature increases by",
      "temperature of a body","clinical thermometer","laboratory thermometer",
      "capillary tube","constriction","sensitivity","range of temperature",
      "temperature change","change in temperature","how much wax melts",
      "specific latent heat of the wax","latent heat of fusion",
      "latent heat of vaporisation","what temperature","boiling point",
      "freezing point","melting point of","cooling curve","heating curve",
      "temperature–time graph","the temperature of the body",
      "internal energy","the temperature increases",
      "mass of warm water","evaporates","what is the furthest temperature"],
     "Thermal properties & temperature"),

    # Transfer of thermal energy
    (["conduction","convection","radiation","infrared","emit","absorb","reflect",
      "black surface","white surface","dull","shiny","conductor","insulator",
      "thermal conductor","good absorber","poor emitter","good emitter",
      "rate of cooling","cool the fastest","radiation from the sun",
      "vacuum flask","double glazing","cavity wall","lagging","foam",
      "painted black","painted white","cool faster","radiate heat"],
     "Transfer of thermal energy"),

    # General wave properties
    (["amplitude","wavelength","frequency","period","transverse","longitudinal",
      "wave speed","wavefront","crest","trough","in phase","coherent",
      "wave equation","v = f","c = f","hertz","Hz","what is the amplitude",
      "what is the frequency","wave on the surface","rope transmitting",
      "vibrator produces","wavelengths on","spacing between crests",
      "what is the speed of the wave","12 wavelengths","first crest","third crest"],
     "General wave properties"),

    # Light
    (["light","refraction","reflection","total internal reflection","critical angle",
      "refractive index","snell's law","converging lens","diverging lens",
      "focal point","focal length","principal axis","real image","virtual image",
      "angle of incidence","angle of refraction","normal","optical fibre",
      "prism","dispersion","colour","spectrum","white light","rainbow",
      "swimming pool","underwater light","ray of light","passes along the surface",
      "plane mirror","concave mirror","convex mirror","optical","lens equation",
      "illuminated object","magnification","what is the correct path",
      "sin i","sin r","refractive index","glass block","two mediums",
      "angle y is equal to the critical"],
     "Light"),

    # Electromagnetic spectrum
    (["electromagnetic spectrum","radio wave","microwave","x-ray","gamma ray",
      "ultraviolet","infrared wave","visible light spectrum",
      "speed of light","all electromagnetic","longest wavelength","shortest wavelength",
      "frequency of electromagnetic","wavelength of electromagnetic",
      "which electromagnetic","red light","violet light","lower frequency",
      "feature of red light","prism deviates","speed in a vacuum",
      "what is the ratio","audible","human ear","20 hz","20 khz",
      "ultrasound","pre-natal scanning","sunbed","infra-red","uv","uva"],
     "Electromagnetic spectrum"),

    # Sound
    (["sound","ultrasound","echo","sonar","hearing","audible",
      "frequency of sound","sound wave","pitch","loudness",
      "longitudinal wave","compression","rarefaction","sound travels",
      "speed of sound","medium for sound","vacuum","sound cannot travel",
      "the frequency of a note","musical instrument","string vibrates",
      "vibrating","loudspeaker","microphone","oscilloscope trace"],
     "Sound"),

    # Electrical quantities
    (["charge","coulomb","current","ampere","voltage","volt",
      "potential difference","e.m.f","electromotive force","emf",
      "resistance","ohm","ohm's law","resistor","i–v characteristic",
      "i-v graph","ammeter","voltmeter","galvanometer",
      "electric field","electrostatic","negative charge","positive charge",
      "charge on","unit of charge","unit of current","what is the charge",
      "what is the resistance","what is the current","what is the voltage",
      "electrons","flow of charge","rate of flow","coulombs per second",
      "two insulated","uncharged metal spheres","charged rod",
      "electric force","direction of the electric field",
      "e.m.f. of the battery equal","j / c","n / v"],
     "Electrical quantities"),

    # Electric circuits
    (["circuit","series","parallel","lamps in series","lamps in parallel",
      "cells in series","cells in parallel","the total resistance",
      "equivalent resistance","combined resistance","battery",
      "the reading on","the ammeter reads","the voltmeter reads",
      "junction","node","kirchhoff","short circuit","open circuit",
      "the bulb","the lamp","which lamp","which bulb",
      "circuit diagram","complete the circuit","which circuit",
      "in the circuit","when the switch","switch is closed","switch is open",
      "connect in","connected in","wired in"],
     "Electric circuits"),

    # Practical electricity
    (["fuse","fuse wire","fuse blows","circuit breaker","earth wire",
      "neutral wire","live wire","three-pin plug","double insulation",
      "mains supply","240 v","230 v","mains voltage","ac supply",
      "direct current","alternating current","d.c.","a.c.",
      "kilowatt-hour","electricity bill","energy meter","household",
      "kettle","heater","toaster","iron","electric oven",
      "plug","wiring","cable","insulation","overheating",
      "nail","replace the fuse","overloads the wiring","causing a fire"],
     "Practical electricity"),

    # Electromagnetic effects
    (["electromagnetic induction","generator","dynamo","transformer",
      "step-up","step-down","turns ratio","coil","solenoid",
      "induced e.m.f","induced current","lenz's law","faraday",
      "secondary coil","primary coil","alternating","transmission",
      "national grid","high voltage transmission","the turbine turns",
      "coal-fired power station","steam turns","in which situation is there no transfer",
      "car moving at constant speed","no energy transfer","spacecraft orbiting"],
     "Electromagnetic effects"),

    # Magnetism
    (["magnet","magnetic field","magnetic pole","north pole","south pole",
      "attract","repel","magnetic material","iron filings","field line",
      "magnetic compass","permanent magnet","electromagnet","soft iron",
      "demagnetise","induced magnet","bar magnet","horseshoe",
      "the loudspeaker","coil of the loudspeaker","vibrating cone",
      "what is vibrating to produce the sound","non-magnetic","copper","aluminium"],
     "Simple magnetism and magnetic fields"),

    # Nuclear model
    (["nucleus","proton","neutron","electron","atomic number","mass number",
      "nuclide","isotope","ion","nuclear model","rutherford","bohr",
      "how many neutrons","how many protons","charge of a proton",
      "relative mass","relative charge","the nuclei","nuclear fission",
      "nuclear fusion","fission","fusion","chain reaction","moderator",
      "control rod","nuclear reactor","the nuclide notation",
      "a – z","how many neutrons are there in","neutrons in a nucleus"],
     "Nuclear model of the atom"),

    # Radioactivity
    (["radioactive","radioactivity","alpha","beta","gamma","half-life",
      "decay","radiation","ionising","geiger","count rate","background",
      "penetrating","absorbed by","stopped by","deflected","magnetic field",
      "radioactive isotope","carbon dating","radio-carbon","c-14","c14",
      "half life","activity","becquerel","nuclear equation",
      "which activity never uses radioactivity",
      "hospital","diagnos","sterilising","treating","cooking meals",
      "bone that is found to have only","natural proportion","old is a bone",
      "fusion of hydrogen nuclei to form helium","energy is released by"],
     "Radioactivity"),

    # Earth & Solar System
    (["solar system","planet","orbit","gravitational","gravity","sun",
      "moon","earth","satellite","geostationary","gravitational field strength",
      "gravitational force","which type of force causes the earth to orbit",
      "orbital","period of orbit"],
     "Earth & the Solar System"),

    # Stars & Universe
    (["star","universe","galaxy","red shift","hubble","big bang",
      "nebula","supernova","white dwarf","black hole","light year",
      "expanding universe","cosmic","milky way"],
     "Stars & the Universe"),

    # Mass & weight
    (["mass and weight","mass of object on","weight on","gravitational field strength is",
      "weighs on earth","taken to a planet","mass stays the same","weight changes",
      "mass / kg","weight / n","g = 10 n / kg","g = 10 m / s",
      "object weighs","which object is on the planet",
      "smallest gravitational field strength","four objects of different masses"],
     "Mass & weight"),
]

# 0625 has same topic structure except different topic names for a few
# Map from 5054 topic name to 0625 topic name where different
TOPIC_REMAP_0625 = {
    "Simple magnetism and magnetic fields": "Simple phenomena of magnetism",
    "Practical electricity": "Electrical safety",
    # "Earth & the Solar System" is the same in both 5054 and 0625 — no remap needed
}

RULES_0625 = []
for patterns, topic in RULES_5054:
    topic_0625 = TOPIC_REMAP_0625.get(topic, topic)
    RULES_0625.append((patterns, topic_0625))


def classify_question(text: str, rules: list) -> tuple[str | None, float, str]:
    """Return (topic, confidence, rationale) for one question."""
    txt = text.lower()
    hits = []
    for patterns, topic in rules:
        matched = [p for p in patterns if p in txt]
        if matched:
            hits.append((len(matched), topic, matched))
    if not hits:
        return None, 0.0, "no keyword match"
    hits.sort(key=lambda h: h[0], reverse=True)
    best_count, best_topic, best_patterns = hits[0]
    # confidence: 0.9 for 2+ matches, 0.85 for 1
    conf = 0.90 if best_count >= 2 else 0.85
    rationale = f"MCQ session: {', '.join(best_patterns[:3])}"
    return best_topic, conf, rationale


def process(syllabus: str, paper: int):
    rules = RULES_0625 if syllabus == "0625" else RULES_5054

    with open(f"data/batches/{syllabus}_p{paper}_questions.json", encoding="utf-8") as f:
        questions = json.load(f)

    con = sqlite3.connect("data/index.db")
    con.row_factory = sqlite3.Row

    # Load existing classification confidence from DB
    existing = {}
    for row in con.execute(
        "SELECT question_id, confidence, backend, topic FROM classifications"
    ).fetchall():
        existing[row["question_id"]] = (row["confidence"], row["backend"], row["topic"])

    results = []
    unchanged = 0
    reclassified = 0
    newly_classified = 0
    unresolved = 0

    for q in questions:
        qid = q["id"]
        old_conf, old_backend, old_topic = existing.get(qid, (None, None, None))

        # Keep heuristic-confident (>=0.8) classifications unchanged
        if old_backend == "heuristic" and old_conf is not None and old_conf >= 0.8:
            unchanged += 1
            continue

        # Classify with improved rules
        new_topic, new_conf, rationale = classify_question(q["text"], rules)

        if new_topic is None:
            # Still no match — keep heuristic result if it exists
            if old_topic is not None:
                unchanged += 1  # keep heuristic even if low-conf
            else:
                unresolved += 1
                print(f"  UNRESOLVED: {q['ref']} | {q['text'][:80]}")
            continue

        results.append({
            "id": qid,
            "topic": new_topic,
            "secondary_topic": None,
            "difficulty": None,
            "confidence": new_conf,
            "rationale": rationale,
        })
        if old_topic is None:
            newly_classified += 1
        else:
            reclassified += 1

    con.close()

    out_path = f"data/batches/{syllabus}_p{paper}_session_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)

    print(f"\n{syllabus} P{paper}:")
    print(f"  Kept heuristic-confident:  {unchanged}")
    print(f"  Reclassified (was heuristic low-conf): {reclassified}")
    print(f"  Newly classified (was none): {newly_classified}")
    print(f"  Still unresolved: {unresolved}")
    print(f"  Written {len(results)} new session results -> {out_path}")


if __name__ == "__main__":
    process("5054", 1)
    process("0625", 1)
    process("0625", 2)
