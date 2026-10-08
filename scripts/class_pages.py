"""Write the detailed parts of the class pages from one place.

    .venv\\Scripts\\python scripts\\class_pages.py          # rewrite the blocks
    .venv\\Scripts\\python scripts\\class_pages.py --check  # exit 1 if a page is stale

website/static/{maths,physics,cs}-classes.html carry two generated blocks
(and website/static/courses.html one, <!--CP:COURSES-->: every course, by level):

    <!--CP:SHOW:START--> ... <!--CP:SHOW:END-->   how we teach (real screenshots),
                                                  parents / students, outcomes
    <!--CP:SYL:START-->  ... <!--CP:SYL:END-->    week-by-week plan per course

Everything else on those pages is hand-written. Edit the WEEKS / COURSES data
below (one line per week), run the script, done.

Every "free demo" WhatsApp button carries data-demo="<key>" (DEMOS below), on
the class pages, courses.html, pricing.html and contact.html. The script writes
its href: a filled-in request (course, papers, batch date, fee, mode, exam
session, name, school, best time, the page it came from) so Tee knows exactly
what the demo is for (tutor, 2026-10-09). New demo button = add the attribute
and run the script. Week 1 starts on Saturday
31 October 2026; weeks 1-13 are the syllabus (Nov-Jan), 14-26 past papers.
"""
from __future__ import annotations

import argparse
from urllib.parse import quote
import html
import re
import sys
from datetime import date, timedelta
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "website" / "static"
START = date(2026, 10, 31)
MONTHS = [("Nov", "November", range(1, 6)), ("Dec", "December", range(6, 10)), ("Jan", "January", range(10, 14))]


def week_dates(n: int) -> str:
    a = START + timedelta(weeks=n - 1)
    b = a + timedelta(days=6)
    f = lambda d: f"{d.day} {d.strftime('%b')}"
    return f"{f(a)} – {f(b)}"


# ── the courses: (title, [subtopics]) per week, weeks 1-13 ───────────────────
OL_MATHS = [
    ("Number foundations", ["Types of number, primes, HCF & LCM", "Fractions, decimals & percentages", "Ordering, directed numbers", "Calculator & non-calculator methods"]),
    ("Percentages, ratio & money", ["Percentage change, reverse percentages", "Ratio & proportion, best buys", "Simple & compound interest", "Exponential growth & decay"]),
    ("Indices, standard form & surds", ["Laws of indices incl. negative & fractional", "Standard form calculations", "Surds: simplify, rationalise", "Bounds, estimation & accuracy"]),
    ("Algebraic manipulation", ["Expanding & factorising (incl. quadratics)", "Algebraic fractions", "Changing the subject", "Substitution"]),
    ("Equations & inequalities", ["Linear & simultaneous equations", "Quadratics: factorise, formula, completing the square", "Linear inequalities & regions", "Forming equations from words"]),
    ("Sequences, functions & variation", ["nth term: linear, quadratic, geometric", "Function notation, composite & inverse", "Direct & inverse variation"]),
    ("Graphs", ["Straight lines: gradient, y = mx + c", "Quadratic, cubic, reciprocal & exponential graphs", "Gradients & areas under graphs, kinematics", "Differentiation & turning points (0580)"]),
    ("Coordinates, angles & circles", ["Midpoint, length, parallel & perpendicular lines", "Angles in polygons & parallel lines", "Circle theorems with reasons"]),
    ("Mensuration & similarity", ["Arcs & sectors", "Surface area & volume: prisms, cylinders, cones, spheres", "Similar shapes: length, area & volume", "Congruence, ruler-and-compass constructions"]),
    ("Trigonometry", ["Pythagoras & SOH CAH TOA", "Bearings", "Sine & cosine rules, ½ab sin C"]),
    ("3D trigonometry & vectors", ["Angles between lines & planes", "Trig graphs & equations (0580)", "Column vectors, magnitude, vector geometry"]),
    ("Transformations & statistics", ["Reflection, rotation, enlargement, translation", "Averages, charts & scatter graphs", "Histograms, cumulative frequency & box plots"]),
    ("Probability & sets", ["Probability rules, tree diagrams", "Venn diagrams & set notation", "Mixed-topic exam questions"]),
]
P1 = [
    ("Quadratics", ["Completing the square, vertex", "Discriminant & nature of roots", "Quadratic inequalities"]),
    ("Quadratics in context", ["Equations in disguise (e.g. in x²)", "Line meets curve: simultaneous equations", "Tangency conditions"]),
    ("Functions", ["Domain & range", "Composite & inverse functions", "One-one functions, graphs of f and f⁻¹"]),
    ("Graph transformations", ["Translations, stretches & reflections", "Combining transformations"]),
    ("Coordinate geometry", ["Lines: gradient, parallel & perpendicular", "Midpoints, distances, perpendicular bisectors"]),
    ("Circles", ["Equation of a circle", "Tangents & normals to circles", "Line–circle intersections"]),
    ("Circular measure", ["Radians", "Arc length & sector area", "Segments & composite shapes"]),
    ("Trigonometry", ["Exact values, trig graphs", "Identities: tan = sin/cos, sin² + cos² = 1", "Solving trig equations in a range"]),
    ("Series", ["Binomial expansion of (a + b)ⁿ", "Arithmetic progressions", "Geometric progressions & sum to infinity"]),
    ("Differentiation", ["Power rule & chain rule", "Gradients, tangents & normals"]),
    ("Applications of differentiation", ["Stationary points & their nature", "Increasing / decreasing functions", "Connected rates of change"]),
    ("Integration", ["Integration as reverse differentiation", "Finding the curve from dy/dx", "Definite integrals & area under a curve"]),
    ("Integration: areas & volumes", ["Area between curves", "Volumes of revolution", "Mixed P1 test"]),
]
P3 = [
    ("Algebra", ["Modulus functions & inequalities", "Polynomial division", "Factor & remainder theorems"]),
    ("Partial fractions & binomial", ["Partial fractions (all three types)", "Binomial expansion for any rational n, validity"]),
    ("Logarithms & exponentials", ["Laws of logs, ln and eˣ", "Exponential equations", "Linearising with log graphs"]),
    ("Trigonometry I", ["sec, cosec, cot", "Compound angle formulae", "Double angle formulae"]),
    ("Trigonometry II", ["R cos(θ ± α) form", "Proving identities", "Harder trig equations"]),
    ("Differentiation", ["Product & quotient rules", "Derivatives of eˣ, ln x, trig functions"]),
    ("Implicit & parametric", ["Implicit differentiation", "Parametric differentiation", "Tangents & normals"]),
    ("Integration", ["Standard integrals incl. trig & exponential", "Substitution", "By parts, using partial fractions"]),
    ("Numerical methods", ["Locating roots by sign change", "Iteration xₙ₊₁ = F(xₙ)", "Convergence"]),
    ("Vectors", ["Vector equation of a line in 3D", "Intersections & skew lines", "Angles, perpendicular distance"]),
    ("Differential equations", ["Separating variables", "Forming equations from context", "Interpreting solutions"]),
    ("Complex numbers", ["Arithmetic, conjugates, solving equations", "Argand diagram, modulus & argument", "Square roots of complex numbers"]),
    ("Complex loci & review", ["Loci in the Argand diagram", "Mixed P3 test"]),
]
M1 = [
    ("Forces", ["Resolving forces into components", "Resultant forces"]),
    ("Equilibrium & friction", ["Equilibrium of a particle", "Friction, coefficient μ, limiting friction"]),
    ("Kinematics", ["Displacement, velocity, acceleration", "Constant acceleration (suvat)"]),
    ("Motion graphs", ["Displacement–time & velocity–time graphs", "Area & gradient in context"]),
    ("Variable acceleration", ["Calculus in kinematics", "Mechanics test: forces & motion"]),
    ("Newton's laws", ["F = ma", "Connected particles"]),
    ("Pulleys & slopes", ["Pulley systems", "Motion on inclined planes, with friction"]),
    ("Energy", ["Work done by a force", "Kinetic & gravitational potential energy"]),
    ("Work–energy & power", ["Work–energy principle", "Power, driving force & resistance"]),
    ("Momentum", ["Conservation of momentum", "Collisions & coalescence"]),
    ("Mixed problems I", ["Connected particles on slopes with friction"]),
    ("Mixed problems II", ["Energy and kinematics in one question"]),
    ("Mechanics review", ["Full P4 test"]),
]
S1 = [
    ("Representation of data", ["Stem-and-leaf, histograms", "Cumulative frequency graphs"]),
    ("Location & spread", ["Mean, median, quartiles, IQR", "Standard deviation, Σx & Σx², coding", "Box plots, comparing data"]),
    ("Permutations", ["Arrangements, repeated items", "Restrictions: together, apart, ends"]),
    ("Combinations", ["Selections", "Selections with conditions"]),
    ("Counting review", ["Mixed permutation & combination problems"]),
    ("Probability", ["Probability rules", "Venn & tree diagrams"]),
    ("Conditional probability", ["Conditional probability", "Independent & mutually exclusive events"]),
    ("Discrete random variables", ["Probability distributions", "Constructing tables from a situation"]),
    ("Expectation & variance", ["E(X) and Var(X)", "Exam-style DRV questions"]),
    ("Binomial distribution", ["B(n, p), conditions, probabilities", "Mean & variance"]),
    ("Geometric distribution", ["Geo(p), probabilities", "Mean"]),
    ("Normal distribution", ["Standardising, using tables", "Finding μ and σ"]),
    ("Normal approximation", ["Normal approximation to the binomial", "Mixed P5 test"]),
]
OL_PHYSICS = [
    ("Measurement & motion", ["Physical quantities, measuring techniques", "Speed, velocity, acceleration"]),
    ("Motion graphs, mass & density", ["Distance–time & speed–time graphs", "Mass & weight, density"]),
    ("Forces", ["Resultant force, F = ma", "Hooke's law, friction, circular motion", "Moments & centre of gravity"]),
    ("Momentum & energy", ["Momentum & impulse", "Energy stores, work, power, efficiency", "Energy resources"]),
    ("Pressure", ["Pressure in solids", "Pressure in liquids: p = ρgh", "Atmospheric pressure"]),
    ("Particles & gases", ["Kinetic particle model", "Gas pressure & volume", "Evaporation"]),
    ("Thermal physics", ["Thermal expansion", "Specific heat capacity, latent heat", "Conduction, convection, radiation"]),
    ("Waves & light", ["Wave properties", "Reflection, refraction, total internal reflection", "Lenses & ray diagrams"]),
    ("EM spectrum & sound", ["Electromagnetic spectrum & uses", "Sound: speed, echoes, ultrasound"]),
    ("Magnetism & electricity", ["Magnets & magnetic fields", "Charge, current, p.d., resistance"]),
    ("Circuits & safety", ["Series & parallel circuits, potential dividers", "Electrical safety & practical electricity", "Uses of an oscilloscope (5054)"]),
    ("Electromagnetic effects", ["Induction, generators, transformers", "Motor effect & d.c. motors"]),
    ("Nuclear & space", ["Nuclear model, radioactivity, half-life", "Earth & the Solar System", "Stars & the Universe"]),
]
AS_PHYSICS = [
    ("Quantities & units", ["SI units, homogeneity", "Uncertainties", "Scalars & vectors"]),
    ("Kinematics", ["Equations of motion", "Projectiles"]),
    ("Dynamics", ["Newton's laws", "Momentum & collisions"]),
    ("Forces & equilibrium", ["Moments & couples", "Equilibrium, centre of gravity"]),
    ("Density, pressure & upthrust", ["Density & pressure", "Upthrust", "Mechanics test"]),
    ("Work, energy & power", ["Work done, kinetic & potential energy", "Power & efficiency"]),
    ("Deformation of solids", ["Stress, strain, Young modulus", "Elastic & plastic behaviour, strain energy"]),
    ("Waves", ["Progressive waves, intensity", "Doppler effect, EM spectrum, polarisation"]),
    ("Superposition", ["Stationary waves", "Diffraction & interference", "Double slit & diffraction gratings"]),
    ("Electricity", ["Charge, current, p.d.", "Resistance & resistivity"]),
    ("D.C. circuits", ["Kirchhoff's laws", "Potential dividers", "e.m.f. & internal resistance"]),
    ("Particle physics", ["Atoms, nuclei, radioactive decay", "Quarks & leptons"]),
    ("Practical skills (Paper 3)", ["Taking measurements, uncertainty", "Tables, graphs, gradients", "Evaluating & improving experiments"]),
]
A2_PHYSICS = [
    ("Motion in a circle", ["Angular speed, centripetal acceleration & force"]),
    ("Gravitational fields", ["Field strength & potential", "Orbits, geostationary satellites"]),
    ("Temperature & ideal gases", ["Thermal equilibrium, temperature scales", "pV = nRT, kinetic theory"]),
    ("Thermodynamics", ["Internal energy", "First law of thermodynamics"]),
    ("Oscillations", ["Simple harmonic motion", "Damping & resonance"]),
    ("Electric fields", ["Coulomb's law", "Field strength & potential"]),
    ("Capacitance", ["Capacitors in circuits, energy stored", "Charging & discharging"]),
    ("Magnetic fields", ["Force on conductors & moving charges", "Hall effect"]),
    ("Induction & a.c.", ["Faraday's & Lenz's laws", "Alternating current, r.m.s., rectification"]),
    ("Quantum physics", ["Photons, photoelectric effect", "Wave–particle duality, energy levels"]),
    ("Nuclear physics", ["Mass defect & binding energy", "Radioactive decay, half-life"]),
    ("Medical physics & astronomy", ["Ultrasound, X-rays, PET", "Luminosity, Wien's law, Hubble's law"]),
    ("Paper 5: planning & analysis", ["Planning an experiment", "Analysis, conclusions & evaluation"]),
]
OL_CS = [
    ("Number systems", ["Binary, denary, hexadecimal conversions", "Binary addition & overflow", "Logical shifts, two's complement"]),
    ("Text, sound & images", ["Character sets", "Sound & image representation", "File sizes & compression"]),
    ("Data transmission", ["Packets & packet switching", "Serial / parallel, simplex / duplex, USB", "Error detection, encryption"]),
    ("The CPU", ["Von Neumann, fetch–decode–execute", "Cores, cache, clock speed", "Embedded systems, input & output devices"]),
    ("Storage & networks", ["Primary & secondary storage, virtual memory", "Cloud storage", "NIC, MAC & IP addresses, routers"]),
    ("Software", ["System vs application software, the OS", "Interrupts", "High / low-level languages, translators, IDEs"]),
    ("The internet & its uses", ["WWW, URLs, HTTP / HTTPS, browsers, cookies", "Digital currency", "Cyber security threats & defences"]),
    ("Automated & emerging tech", ["Sensors & automated systems", "Robotics", "Artificial intelligence"]),
    ("Algorithm design", ["Program development life cycle, decomposition", "Flowcharts & pseudocode", "Trace tables, validation & verification"]),
    ("Programming I", ["Variables, constants, data types", "Selection & iteration", "Totalling, counting, string handling"]),
    ("Programming II", ["Arrays (1D & 2D)", "Procedures & functions, file handling", "Linear search, bubble sort"]),
    ("Databases & Boolean logic", ["Single-table databases & SQL", "Logic gates, truth tables, logic expressions"]),
    ("The scenario question", ["Planning a full Paper 2 program", "Writing & testing it in pseudocode"]),
]
CS_P1 = [
    ("Information representation", ["Number bases, BCD, two's complement", "Character sets"]),
    ("Multimedia & compression", ["Bitmap & vector graphics", "Sound", "Lossy & lossless compression"]),
    ("Networks", ["LAN / WAN, topologies", "Client–server & peer-to-peer", "Cloud computing"]),
    ("The internet", ["Ethernet, CSMA/CD, wireless", "IP addressing, DNS, internet vs WWW"]),
    ("Hardware", ["Computer components, memory types", "Embedded systems", "Logic gates & circuits"]),
    ("Processor fundamentals", ["Von Neumann, registers, buses", "Fetch–execute cycle, interrupts"]),
    ("Assembly language", ["Instruction sets, addressing modes", "Bit manipulation"]),
    ("System software", ["Operating system functions, utilities", "Libraries, translators, IDEs"]),
    ("Security & data integrity", ["Threats, firewalls, encryption basics", "Validation & verification"]),
    ("Ethics & ownership", ["Professional ethics", "Copyright & software licences", "Ethics of AI"]),
    ("Databases I", ["Relational model, keys", "Normalisation 1NF–3NF, E-R diagrams"]),
    ("Databases II", ["DBMS features", "SQL: DDL & DML"]),
    ("AI & review", ["AI basics", "Mixed P1 test"]),
]
CS_P2 = [
    ("Computational thinking", ["Abstraction & decomposition", "Structured English, flowcharts, pseudocode"]),
    ("Pseudocode fluency", ["Selection & iteration", "Identifier tables, trace tables"]),
    ("Standard algorithms", ["Linear search", "Bubble sort"]),
    ("Program design", ["Stepwise refinement", "Structure charts"]),
    ("Data types & records", ["Primitive types", "Records (user-defined types)"]),
    ("Arrays", ["1D & 2D arrays", "Searching & processing arrays"]),
    ("Files", ["Reading & writing text files"]),
    ("Abstract data types", ["Stack, queue, linked list"]),
    ("ADT operations", ["Push / pop, enqueue / dequeue in pseudocode"]),
    ("Subroutines", ["Procedures & functions", "Parameters: by value / by reference", "Built-in & string functions"]),
    ("Programming", ["Turning pseudocode into Python / Java / VB"]),
    ("Software development", ["Development life cycle", "Testing, test data, types of error", "Maintenance"]),
    ("Scenario practice", ["Mixed P2 test"]),
]
CS_P3 = [
    ("Data representation", ["User-defined data types", "File organisation & access", "Floating-point numbers"]),
    ("Floating point", ["Normalisation", "Precision & range, rounding errors"]),
    ("Communication", ["Protocols, the TCP/IP stack", "Circuit vs packet switching"]),
    ("Hardware & virtual machines", ["RISC & CISC, pipelining", "Parallel processing, virtual machines"]),
    ("Boolean algebra", ["Boolean algebra, Karnaugh maps", "Flip-flops, adders"]),
    ("System software", ["OS purposes, process scheduling", "Memory management, paging"]),
    ("Translation software", ["Stages of compilation", "BNF, syntax diagrams, Reverse Polish"]),
    ("Encryption", ["Symmetric & asymmetric encryption", "Quantum cryptography"]),
    ("Certificates & protocols", ["Digital signatures & certificates", "SSL / TLS"]),
    ("Artificial intelligence", ["Graphs, Dijkstra's & A* algorithms", "Machine learning, neural networks"]),
    ("Computational thinking", ["Binary search, insertion sort", "ADT implementations, Big O"]),
    ("Programming paradigms", ["Low-level, imperative, OOP, declarative", "OOP concepts"]),
    ("Further programming", ["Recursion", "Exception handling, file processing", "Mixed P3 test"]),
]
CS_P4 = [
    ("The practical exam", ["Setting up Python / Java / VB", "Reading the task & evidence document"]),
    ("Arrays, records & strings", ["Implementing records & arrays", "String handling"]),
    ("Text files", ["Read, write, append"]),
    ("Stacks & queues", ["Array-based implementations"]),
    ("Linked lists", ["Insert, delete, traverse"]),
    ("Binary trees", ["Insert, search, traversals"]),
    ("Searching", ["Linear vs binary search", "Iterative & recursive versions"]),
    ("Sorting", ["Bubble sort", "Insertion sort"]),
    ("Recursion", ["Tracing & writing recursive functions"]),
    ("OOP I", ["Classes, objects, constructors", "Getters & setters"]),
    ("OOP II", ["Inheritance, polymorphism, encapsulation"]),
    ("Exceptions", ["Exception handling", "File-based OOP tasks"]),
    ("Full practical", ["Timed full P4 task"]),
]

PAPERS = {  # what the Feb-Apr past paper sessions use
    "ol-maths": "4024 Paper 1 + 2 / 0580 Paper 2 + 4", "p1": "9709 Paper 1", "p3": "9709 Paper 3",
    "m1": "9709 Paper 4", "s1": "9709 Paper 5", "ol-physics": "5054 Paper 2 / 0625 Paper 2 + 4 (+ ATP)",
    "as": "9702 Paper 1, 2 & 3", "a2": "9702 Paper 4 & 5", "ol-cs": "2210 / 0478 Paper 1 + 2",
    "cs1": "9618 Paper 1", "cs2": "9618 Paper 2", "cs3": "9618 Paper 3", "cs4": "9618 Paper 4",
}

OL_PRICE, AL_PRICE = "8,499", "12,999"
WA = "https://wa.me/923204884375?text="

# ── Free-demo WhatsApp messages ──────────────────────────────────────────────
# key -> (course, papers line or None, fee line or None). "Keep one" lists are
# for the student to trim before sending.
_OL_FEE = f"PKR {OL_PRICE}/month per subject"
_AL_FEE = f"from PKR {AL_PRICE}/month per paper course (ask about bundles)"
DEMOS = {
    "ol-maths": ("O Level / IGCSE Maths - 4024 or 0580 Extended (keep one)", None, _OL_FEE),
    "al-maths": ("A Level Maths 9709", "P1 / P3 / M1 / S1 (keep the ones you're sitting)", _AL_FEE),
    "maths": ("Maths - O Level 4024 / IGCSE 0580 / A Level 9709 (keep one)",
              "if A Level: P1 / P3 / M1 / S1", None),
    "ol-physics": ("O Level / IGCSE Physics - 5054 or 0625 (keep one)", None, _OL_FEE),
    "al-physics": ("A Level Physics 9702", "AS (Papers 1-3) / A2 (Papers 4-5) (keep what you're sitting)", _AL_FEE),
    "physics": ("Physics - O Level 5054 / IGCSE 0625 / A Level 9702 (keep one)",
                "if A Level: AS / A2", None),
    "ol-cs": ("O Level / IGCSE Computer Science - 2210 or 0478 (keep one)", None, _OL_FEE),
    "al-cs": ("A Level Computer Science 9618", "P1 / P2 / P3 / P4 (keep the ones you're sitting)", _AL_FEE),
    "cs": ("Computer Science - O Level 2210 / IGCSE 0478 / A Level 9618 (keep one)",
           "if A Level: P1 / P2 / P3 / P4", None),
    "any": ("Subject + board (e.g. O Level Physics 5054): ", None, None),
    "plan-1": ("1 subject - which one + board: ", None, "1-subject plan"),
    "plan-2": ("2 subjects - which ones + board: ", None, "2-subject plan"),
    "plan-3": ("3 subjects - which ones + board: ", None, "3-subject plan"),
}


def demo_text(key: str, page: str) -> str:
    course, papers, fee = DEMOS[key]
    lines = ["Hi Tee! I'd like to book a FREE DEMO class.", "",
             f"📚 Course: {course}"]
    if papers:
        lines.append(f"📝 Papers: {papers}")
    lines.append(f"📅 Batch: starts Saturday {START.day} {START.strftime('%B %Y')} (groups of 4-6)")
    if fee:
        lines.append(f"💰 Fee: {fee}")
    lines += ["📍 Online or in person in Lahore: ",
              "🎯 Exam session (e.g. May/June 2027): ",
              "👤 Student's name: ",
              "🏫 School & current grade/year: ",
              "🕒 Best days & time for the demo: ",
              "",
              f"(Sent from prepwithtee.com/{page})"]
    return "\n".join(lines)


def demo_href(key: str, page: str) -> str:
    return WA + quote(demo_text(key, page), safe="")


DEMO_A = re.compile(r'<a\b[^>]*\bdata-demo="([a-z0-9-]+)"[^>]*>')


def stamp_demos(page: str, s: str) -> str:
    """Write the detailed message into every <a data-demo="key"> on the page."""
    def one(m):
        tag, key = m.group(0), m.group(1)
        assert key in DEMOS, f"{page}: unknown data-demo={key!r}"
        new, n = re.subn(r'href="[^"]*"', lambda _: f'href="{html.escape(demo_href(key, page))}"', tag, count=1)
        assert n == 1, f"{page}: data-demo={key} has no href"
        return new
    return DEMO_A.sub(one, s)

# The catalogue: one entry per subject page, each with its courses. A course is
# (key, level, code, name, tag, weeks, papers key). level "ol" = O Level & IGCSE,
# "al" = A Level. Adding a subject or course here adds it to its page AND /courses.
SUBJECTS = [
    {"page": "maths-classes.html", "key": "maths", "name": "Maths", "icon": "📐", "tone": "lav",
     "ol_codes": "4024 · 0580 Extended", "al_code": "9709",
     "courses": [
         ("ol", "ol", "O Level &amp; IGCSE", "Mathematics", "4024 · 0580 Extended", OL_MATHS, "ol-maths"),
         ("p1", "al", "P1", "Pure Mathematics 1", "AS", P1, "p1"),
         ("p3", "al", "P3", "Pure Mathematics 3", "A2", P3, "p3"),
         ("m1", "al", "M1", "Mechanics", "Paper 4", M1, "m1"),
         ("s1", "al", "S1", "Probability &amp; Statistics 1", "Paper 5", S1, "s1"),
     ]},
    {"page": "physics-classes.html", "key": "physics", "name": "Physics", "icon": "⚛️", "tone": "green",
     "ol_codes": "5054 · 0625", "al_code": "9702",
     "courses": [
         ("ol", "ol", "O Level &amp; IGCSE", "Physics", "5054 · 0625", OL_PHYSICS, "ol-physics"),
         ("as", "al", "AS", "AS Physics", "Papers 1, 2 &amp; 3", AS_PHYSICS, "as"),
         ("a2", "al", "A2", "A2 Physics", "Papers 4 &amp; 5", A2_PHYSICS, "a2"),
     ]},
    {"page": "cs-classes.html", "key": "cs", "name": "Computer Science", "icon": "💻", "tone": "pink",
     "ol_codes": "2210 · 0478", "al_code": "9618",
     "courses": [
         ("ol", "ol", "O Level &amp; IGCSE", "Computer Science", "2210 · 0478", OL_CS, "ol-cs"),
         ("p1", "al", "P1", "Theory Fundamentals", "AS", CS_P1, "cs1"),
         ("p2", "al", "P2", "Problem-solving &amp; Programming", "AS", CS_P2, "cs2"),
         ("p3", "al", "P3", "Advanced Theory", "A2", CS_P3, "cs3"),
         ("p4", "al", "P4", "Practical", "A2", CS_P4, "cs4"),
     ]},
]
BY_PAGE = {s["page"]: s for s in SUBJECTS}
PAGES = BY_PAGE                                     # the subject pages this script rewrites
SUBJECT = {s["page"]: s["name"] for s in SUBJECTS}
MONTH_TONES = {"Nov": "lav", "Dec": "green", "Jan": "blue"}


def past_paper_plan(papers: str) -> list[tuple[str, str, str]]:
    return [
        ("14–15", "Paper technique", f"How each part of {papers} is marked; first papers worked through together with the tutor."),
        ("16–18", "Timed papers, older years", "Full papers under exam timing, then gone through question by question against the mark scheme."),
        ("19–21", "Timed papers, latest years", "The most recent sessions incl. Feb/March and every variant, timed and marked."),
        ("22", "Mock exam 1", "A full mock in exam conditions, marked with a grade from the official thresholds; report to parents."),
        ("23–24", "Weak-topic clinics", "Each student's lowest-scoring chapters from the mock re-taught and re-tested."),
        ("25", "Mock exam 2", "A second full mock: the jump in marks shows what the clinics fixed."),
        ("26", "Final revision", "Formulae, definitions, command words, common mistakes and an exam-day plan."),
    ]


def esc(s: str) -> str:
    return s  # data above is already HTML-safe (&amp; written out)


def month_titles(weeks, rng) -> list[str]:
    return [weeks[n - 1][0] for n in rng]


def panel(subj, course, first):
    key, level, code, name, tag, weeks, papers_key = course
    assert len(weeks) == 13, (name, len(weeks))
    months = []
    for short, long_, rng in MONTHS:
        cards = []
        for n in rng:
            t, subs = weeks[n - 1]
            lis = "".join(f"<li>{esc(x)}</li>" for x in subs)
            cards.append(f'<li class="cp-wk"><div class="cp-wk-top"><span class="cp-wk-n" aria-hidden="true">{n}</span>'
                         f'<div><span class="cp-wk-lbl">Week {n}</span><span class="cp-wk-d">{week_dates(n)}</span></div></div>'
                         f'<b>{esc(t)}</b><ul class="cp-wk-subs">{lis}</ul>'
                         f'<span class="cp-wk-test">📝 Day 5 test · 📚 topical homework</span></li>')
        chips = "".join(f"<span>{esc(x)}</span>" for x in month_titles(weeks, rng))
        first_w, last_w = rng[0], rng[-1]
        months.append(
            f'<details class="cp-month cp-m-{MONTH_TONES[short]}"{" open" if short == "Nov" else ""}>'
            f'<summary><span class="cp-mon"><b>{long_}</b><small>Weeks {first_w}–{last_w}</small></span>'
            f'<span class="cp-mon-chips">{chips}</span><span class="cp-mon-tog" aria-hidden="true"></span></summary>'
            f'<ol class="cp-wks">{"".join(cards)}</ol></details>')
    pp = "".join(f'<li><span class="cp-pp-w">Week {w}</span><b>{t}</b><p>{d}</p></li>' for w, t, d in past_paper_plan(PAPERS[papers_key]))
    lvl = "O Level &amp; IGCSE" if level == "ol" else f"A Level {subj['al_code']} · {tag}"
    title = f"{subj['name']} · {lvl}" if level == "ol" else f"{code} · {name}"
    price = f"PKR {OL_PRICE}/month" if level == "ol" else f"from PKR {AL_PRICE}/month · separate course"
    return f'''      <div class="cp-panel" role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}" data-level="{level}"{"" if first else " hidden"}>
        <div class="cp-panel-head"><div><p class="cp-panel-lvl">{"O Level &amp; IGCSE · " + subj["ol_codes"] if level == "ol" else "A Level " + subj["al_code"] + " · " + tag}</p><h3>{title}</h3></div><p class="cp-panel-price">{price}</p></div>
        <div class="cp-phase"><span class="cp-phase-n">1</span><div><b>The whole syllabus, week by week</b><small>November – January · 13 weeks</small></div></div>
        {"".join(months)}
        <div class="cp-phase is-pp"><span class="cp-phase-n">2</span><div><b>Past paper sessions</b><small>February – April · {PAPERS[papers_key]}</small></div></div>
        <ol class="cp-pp">{pp}</ol>
      </div>
'''


def syllabus_block(page: str) -> str:
    subj = BY_PAGE[page]
    ol = [c for c in subj["courses"] if c[1] == "ol"]
    al = [c for c in subj["courses"] if c[1] == "al"]
    al_btns = "\n".join(
        f'          <button type="button" role="tab" id="tab-{c[0]}" aria-controls="panel-{c[0]}" aria-selected="{"true" if i == 0 else "false"}"'
        f'{"" if i == 0 else " tabindex=\"-1\""}><b>{c[2]}</b><span>{c[3]}</span><small>{c[4]}</small></button>' for i, c in enumerate(al))
    panels = "\n".join(panel(subj, c, first=(c in ol)) for c in ol + al)
    al_names = " · ".join(c[2] for c in al)
    return f'''<!--CP:SYL:START - generated by scripts/class_pages.py, edit the data there -->
  <section class="mc-sec" id="syllabus">
    <div class="container">
      <p class="eyebrow">What each course covers</p>
      <h2 class="mc-h">Week by week, <em>course by course.</em></h2>
      <p class="mc-lede">First choose your level. Every week ends with a test on that week's topics, and every chapter comes with its topical past papers as homework.</p>
      <div class="cp-levels" role="group" aria-label="Level">
        <button type="button" class="cp-level" data-level="ol" aria-pressed="true"><span class="cp-level-ic" aria-hidden="true">🎓</span><span><b>O Level &amp; IGCSE</b><small>{subj["ol_codes"]} · PKR {OL_PRICE}/month</small></span></button>
        <button type="button" class="cp-level" data-level="al" aria-pressed="false"><span class="cp-level-ic" aria-hidden="true">🏛️</span><span><b>A Level {subj["al_code"]}</b><small>{len(al)} separate courses: {al_names} · from PKR {AL_PRICE}</small></span></button>
      </div>
      <div class="cp-al" hidden>
        <p class="cp-al-lbl">A Level {subj["al_code"]} is taught as {len(al)} separate courses. Pick the one you want to see:</p>
        <div class="cp-papers" role="tablist" aria-label="A Level course">
{al_btns}
        </div>
      </div>

{panels}      <div class="cp-every">
        <b>Every single week, in every course</b>
        <ul><li>📖 4 live classes: concept first, then real past-paper questions</li><li>📝 Day 5: a timed test on the week's topics, marked to the mark scheme</li>
        <li>📚 Topical past-paper booklet for homework, official mark scheme after every question</li><li>💬 WhatsApp doubt support between classes</li></ul>
      </div>
    </div>
  </section>
  <script>
  (function () {{  /* level switch + A Level course tabs (scripts/class_pages.py) */
    var sec = document.getElementById('syllabus');
    var levels = sec.querySelectorAll('.cp-level'), alBox = sec.querySelector('.cp-al');
    var tabs = sec.querySelectorAll('.cp-papers [role="tab"]'), panels = sec.querySelectorAll('.cp-panel');
    var alKey = tabs.length ? tabs[0].id.slice(4) : null;
    function showPanel(key) {{
      panels.forEach(function (p) {{ p.hidden = p.id !== 'panel-' + key; }});
      var lvl = key === 'ol' ? 'ol' : 'al';
      levels.forEach(function (b) {{ b.setAttribute('aria-pressed', String(b.dataset.level === lvl)); }});
      alBox.hidden = lvl !== 'al';
      if (lvl === 'al') {{
        alKey = key;
        tabs.forEach(function (t) {{ var on = t.id === 'tab-' + key; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; }});
      }}
    }}
    levels.forEach(function (b) {{ b.addEventListener('click', function () {{ showPanel(b.dataset.level === 'ol' ? 'ol' : alKey); }}); }});
    tabs.forEach(function (t, i) {{
      t.addEventListener('click', function () {{ showPanel(t.id.slice(4)); }});
      t.addEventListener('keydown', function (e) {{
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        var n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        showPanel(n.id.slice(4)); n.focus();
      }});
    }});
    document.querySelectorAll('[data-tab]').forEach(function (a) {{
      a.addEventListener('click', function () {{ showPanel(a.getAttribute('data-tab')); }});
    }});
    var h = location.hash.slice(1);
    if (h === 'alevel' && alKey) showPanel(alKey);
    else if (document.getElementById('panel-' + h)) {{ showPanel(h); sec.scrollIntoView(); }}
  }})();
  </script>
<!--CP:SYL:END-->'''


# ── /courses: every course, switched by level ────────────────────────────────
def courses_block() -> str:
    def months_summary(weeks):
        return "".join(f'<li><span>{short}</span>{" · ".join(month_titles(weeks, rng))}</li>' for short, _l, rng in MONTHS)

    ol_cards, al_groups = [], []
    for s in SUBJECTS:
        for key, level, code, name, tag, weeks, pk in s["courses"]:
            if level != "ol":
                continue
            ol_cards.append(f'''        <article class="cl-card cl-{s["tone"]}">
          <div class="cl-card-head"><span class="cl-ic" aria-hidden="true">{s["icon"]}</span><div><h3>{s["name"]}</h3><p>{s["ol_codes"]}</p></div></div>
          <div class="cl-price"><small>As low as PKR</small><b>{OL_PRICE}</b><span>/month</span></div>
          <ul class="cl-months">{months_summary(weeks)}<li><span>Feb–Apr</span>Past paper sessions: {PAPERS[pk]}</li></ul>
          <div class="cl-acts"><a class="cl-btn" href="/{s["page"]}#ol">Week-by-week plan →</a>
            <a class="cl-btn is-wa" data-demo="ol-{s["key"]}" href="#" target="_blank" rel="noopener">Free demo</a></div>
        </article>''')
        als = [c for c in s["courses"] if c[1] == "al"]
        cards = "".join(f'''
          <a class="cl-al-card" href="/{s["page"]}#{key}"><span class="cl-al-code">{code}</span><b>{name}</b><small>{tag}</small>
            <ul class="cl-months is-mini">{months_summary(weeks)}</ul><span class="cl-al-go">Week-by-week plan →</span></a>'''
                        for key, level, code, name, tag, weeks, pk in als)
        al_groups.append(f'''        <section class="cl-al-group cl-{s["tone"]}" aria-label="A Level {s["name"]}">
          <div class="cl-al-head"><span class="cl-ic" aria-hidden="true">{s["icon"]}</span><div><h3>{s["name"]} <span>{s["al_code"]}</span></h3><p>{len(als)} separate courses · from PKR {AL_PRICE}/month each</p></div>
            <a class="cl-btn is-wa" data-demo="al-{s["key"]}" href="#" target="_blank" rel="noopener">Free demo</a></div>
          <div class="cl-al-grid">{cards}
          </div>
        </section>''')
    return f'''<!--CP:COURSES:START - generated by scripts/class_pages.py, edit the data there -->
      <div class="cl-switch" role="group" aria-label="Level">
        <button type="button" class="cl-lvl" data-level="o-level" aria-pressed="true"><span aria-hidden="true">🎓</span><b>O Level &amp; IGCSE</b><small>PKR {OL_PRICE}/month per subject</small></button>
        <button type="button" class="cl-lvl" data-level="a-level" aria-pressed="false"><span aria-hidden="true">🏛️</span><b>A Level</b><small>Each paper its own course · from PKR {AL_PRICE}</small></button>
      </div>

      <div class="cl-view" data-view="o-level">
        <p class="cl-view-lede">One course per subject, covering the whole O Level / IGCSE syllabus by January, then three months of past papers.</p>
        <div class="cl-grid">
{chr(10).join(ol_cards)}
        </div>
      </div>

      <div class="cl-view" data-view="a-level" hidden>
        <p class="cl-view-lede">A Level is split into separate courses, one per paper (or AS / A2), so you only join what you're sitting. Taking two or more? Ask about bundle fees.</p>
{chr(10).join(al_groups)}
      </div>
<!--CP:COURSES:END-->'''


# ── how we teach (screenshots), parents & students, outcomes ─────────────────
SHOW = [
    ("board", "In class", "Taught live, on a shared board",
     "Every class is live with the tutor in a small group. Real exam diagrams go up on the PrepWithTee Board, where we draw, annotate and work through them together with a ruler, protractor, compass and graph paper. Nobody hides at the back of a group of six.",
     ["Concept first, then straight into exam questions", "Every student answers, every answer gets checked", "Board notes saved for revision"]),
    ("question", "Homework", "Topical past papers on what was just taught",
     "After each chapter, students get a booklet of real Cambridge questions on exactly that chapter, from every recent session and variant. Original papers, not retyped, so diagrams and answer lines look just like the exam.",
     ["Every recent question on the chapter, newest first", "Official mark scheme straight after each question", "Annotate on screen or print it"]),
    ("explain", "Stuck at 11 pm?", "Mark schemes, explained step by step",
     "Next to every question is the official mark scheme and a worked explanation that shows where each mark comes from, plus hints when a student only wants a nudge. Anything still unclear goes to the tutor on WhatsApp.",
     ["See why an answer gets the marks", "Hints before the full solution", "WhatsApp the tutor for anything else"]),
    ("test", "Day 5, every week", "A weekly test built from past papers",
     "Each Day 5 test is built from past-paper questions on that week's chapters: multiple choice first, then structured questions, with its own mark scheme. It's timed like the real exam.",
     ["Covers exactly what was taught that week", "Timed, then marked to the official scheme", "Scores shared with parents"]),
    ("marks", "Results", "Marks and a grade, not just a tick",
     "Students record their marks against the official grade thresholds for that exact paper, so everyone can see the grade a score would have earned, and how close the next grade is.",
     ["Real grade thresholds for every paper", "Progress across past papers", "Know what A* actually takes"]),
    ("progress", "For parents", "Progress you can actually see",
     "Every chapter shows where a student stands, from 'not started' to 'exam ready'. With weekly test scores and the mock reports, parents always know how things are going, not just in May.",
     ["Chapter-by-chapter progress", "Weekly test scores and mock reports", "Streaks show steady work"]),
]

PARENTS = ["A clear plan from October to the exam, with no last-minute panic",
           "Small groups of 4–6: your child can't hide, and won't be lost in a crowd",
           "A test every week, with the score shared with you",
           "Mock exams with a grade and a written report",
           "A tutor you can message on WhatsApp",
           "A free demo class first, and a full refund if the first paid class isn't right"]
STUDENTS = ["Understand it, don't just memorise it, then practise until it sticks",
            "Real past-paper questions from the very first week",
            "Learn how marks are actually given and how to word answers to earn them",
            "Help when you're stuck, even late at night",
            "Every topic finished by January, so Feb–Apr is calm practice, not cramming",
            "Everything in one place: papers, mark schemes, notes, tests, progress"]
OUTCOMES = [("📚", "Every topic, done", "The whole syllabus finished by the end of January"),
            ("📝", "Dozens of full papers", "Recent sessions and variants, timed and marked"),
            ("🎯", "Exam technique", "Command words, method marks and how to set out answers"),
            ("📈", "A predicted grade", "From two full mocks marked to real thresholds"),
            ("🧠", "Weak spots fixed", "Clinics on each student's lowest-scoring chapters"),
            ("😌", "Calm in May", "Exam-day plan, final revision, no surprises")]


def show_block(page: str) -> str:
    rows = []
    for i, (img, kicker, title, text, points) in enumerate(SHOW):
        lis = "".join(f"<li>{p}</li>" for p in points)
        rows.append(f'''      <div class="cp-row{" is-flip" if i % 2 else ""}">
        <figure class="cp-shot"><div class="cp-frame"><span></span><span></span><span></span></div>
          <img src="/images/classes/{img}.jpg" alt="{html.escape(title)} - PrepWithTee screenshot" width="1280" height="{860 if img in ("board", "test") else 800}" loading="lazy" decoding="async"></figure>
        <div class="cp-copy"><p class="cp-kick">{kicker}</p><h3>{title}</h3><p>{text}</p><ul>{lis}</ul></div>
      </div>''')
    par = "".join(f"<li>{x}</li>" for x in PARENTS)
    stu = "".join(f"<li>{x}</li>" for x in STUDENTS)
    out = "".join(f'<li><span aria-hidden="true">{e}</span><b>{t}</b><small>{d}</small></li>' for e, t, d in OUTCOMES)
    return f'''<!--CP:SHOW:START - generated by scripts/class_pages.py, edit the data there -->
  <section class="mc-sec" id="how-we-teach">
    <div class="container">
      <p class="eyebrow">How we teach · what you get</p>
      <h2 class="mc-h">See exactly how a week <em>works.</em></h2>
      <p class="mc-lede">These are real screens from PrepWithTee, the platform every {SUBJECT[page]} student uses alongside the live classes. It's included in the fee, with nothing extra to buy.</p>
{chr(10).join(rows)}
    </div>
  </section>

  <section class="mc-sec is-band" id="for-you">
    <div class="container">
      <p class="eyebrow">Built around what families ask for</p>
      <h2 class="mc-h">What parents get, <em>what students get.</em></h2>
      <div class="cp-two">
        <div class="cp-who is-parents"><h3>👪 For parents</h3><ul>{par}</ul></div>
        <div class="cp-who is-students"><h3>🎒 For students</h3><ul>{stu}</ul></div>
      </div>
      <h3 class="cp-out-h">By May, every student will have</h3>
      <ul class="cp-out">{out}</ul>
    </div>
  </section>
<!--CP:SHOW:END-->'''


SYL_RE = re.compile(r"<!--CP:SYL:START.*?<!--CP:SYL:END-->|  <section class=\"mc-sec\" id=\"syllabus\">.*?</section>", re.S)
SHOW_RE = re.compile(r"\n?<!--CP:SHOW:START.*?<!--CP:SHOW:END-->\n?", re.S)
PLAN_END = re.compile(r'(  <section class="mc-sec is-band" id="plan">.*?</section>\n)', re.S)


def render(page: str, s: str) -> str:
    s = SYL_RE.sub(lambda _: syllabus_block(page), s, count=1)
    s = SHOW_RE.sub("", s)
    s, n = PLAN_END.subn(lambda m: m.group(1) + "\n" + show_block(page) + "\n", s, count=1)
    assert n == 1, f"{page}: plan section not found"
    return s


COURSES_RE = re.compile(r"<!--CP:COURSES:START.*?<!--CP:COURSES:END-->", re.S)


def render_courses(s: str) -> str:
    s, n = COURSES_RE.subn(lambda _: courses_block(), s, count=1)
    assert n == 1, "courses.html: CP:COURSES markers not found"
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    stale = []
    for page in [*PAGES, "courses.html", "pricing.html", "contact.html"]:
        p = STATIC / page
        src = p.read_text(encoding="utf-8")
        new = (render_courses(src) if page == "courses.html" else
               src if page in ("pricing.html", "contact.html") else render(page, src))
        new = stamp_demos(page, new)
        if new != src:
            stale.append(page)
            if not a.check:
                p.write_text(new, encoding="utf-8")
    if a.check:
        print("stale: " + ", ".join(stale) if stale else "class pages up to date")
        return 1 if stale else 0
    print("updated: " + (", ".join(stale) or "nothing"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
