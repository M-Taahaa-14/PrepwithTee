"""Write the detailed parts of the class pages from one place.

    .venv\\Scripts\\python scripts\\class_pages.py          # rewrite the blocks
    .venv\\Scripts\\python scripts\\class_pages.py --check  # exit 1 if a page is stale

website/static/{maths,physics,cs}-classes.html carry two generated blocks:

    <!--CP:SHOW:START--> ... <!--CP:SHOW:END-->   how we teach (real screenshots),
                                                  parents / students, outcomes
    <!--CP:SYL:START-->  ... <!--CP:SYL:END-->    week-by-week plan per course

Everything else on those pages is hand-written. Edit the WEEKS / COURSES data
below (one line per week), run the script, done. Week 1 starts on Saturday
31 October 2026; weeks 1-13 are the syllabus (Nov-Jan), 14-26 past papers.
"""
from __future__ import annotations

import argparse
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

# page -> tabs: (key, tab label, heading, subtitle, weeks, papers key)
PAGES = {
    "maths-classes.html": [
        ("ol", "O Level &amp; IGCSE", "O Level &amp; IGCSE Mathematics", "4024 · 0580 Extended · from PKR 8,499/month", OL_MATHS, "ol-maths"),
        ("p1", "P1", "P1 · Pure Mathematics 1", "AS · separate course · from PKR 12,999/month", P1, "p1"),
        ("p3", "P3", "P3 · Pure Mathematics 3", "A2 · separate course · from PKR 12,999/month", P3, "p3"),
        ("m1", "M1", "M1 · Mechanics", "9709 Paper 4 · separate course · from PKR 12,999/month", M1, "m1"),
        ("s1", "S1", "S1 · Probability &amp; Statistics 1", "9709 Paper 5 · separate course · from PKR 12,999/month", S1, "s1"),
    ],
    "physics-classes.html": [
        ("ol", "O Level &amp; IGCSE", "O Level &amp; IGCSE Physics", "5054 · 0625 · from PKR 8,499/month", OL_PHYSICS, "ol-physics"),
        ("as", "AS Physics", "AS Physics", "9702 Papers 1, 2 &amp; 3 · separate course · from PKR 12,999/month", AS_PHYSICS, "as"),
        ("a2", "A2 Physics", "A2 Physics", "9702 Papers 4 &amp; 5 · separate course · from PKR 12,999/month", A2_PHYSICS, "a2"),
    ],
    "cs-classes.html": [
        ("ol", "O Level &amp; IGCSE", "O Level &amp; IGCSE Computer Science", "2210 · 0478 · from PKR 8,499/month", OL_CS, "ol-cs"),
        ("p1", "P1", "P1 · Theory Fundamentals", "AS · separate course · from PKR 12,999/month", CS_P1, "cs1"),
        ("p2", "P2", "P2 · Problem-solving &amp; Programming", "AS · separate course · from PKR 12,999/month", CS_P2, "cs2"),
        ("p3", "P3", "P3 · Advanced Theory", "A2 · separate course · from PKR 12,999/month", CS_P3, "cs3"),
        ("p4", "P4", "P4 · Practical", "A2 · separate course · from PKR 12,999/month", CS_P4, "cs4"),
    ],
}
SUBJECT = {"maths-classes.html": "Maths", "physics-classes.html": "Physics", "cs-classes.html": "Computer Science"}


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


def panel(key, label, title, sub, weeks, papers_key, first):
    assert len(weeks) == 13, (title, len(weeks))
    months = []
    for short, long_, rng in MONTHS:
        cards = []
        for n in rng:
            t, subs = weeks[n - 1]
            lis = "".join(f"<li>{esc(x)}</li>" for x in subs)
            cards.append(f'<li class="cp-wk"><div class="cp-wk-top"><span class="cp-wk-n">Week {n}</span>'
                         f'<span class="cp-wk-d">{week_dates(n)}</span></div><b>{esc(t)}</b><ul>{lis}</ul></li>')
        heads = " · ".join(weeks[n - 1][0] for n in rng)
        months.append(f'<details class="cp-month"{" open" if short == "Nov" else ""}><summary><span class="cp-mon">{long_}</span>'
                      f'<span class="cp-mon-t">{esc(heads)}</span><span class="cp-mon-n">{len(rng)} weeks</span></summary>'
                      f'<ol class="cp-wks">{"".join(cards)}</ol></details>')
    pp = "".join(f'<li><span class="cp-pp-w">Week {w}</span><b>{t}</b><p>{d}</p></li>' for w, t, d in past_paper_plan(PAPERS[papers_key]))
    return f'''      <div role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}"{"" if first else " hidden"}>
        <div class="mc-panel-head"><h3>{title}</h3><p>{sub}</p></div>
        <p class="cp-phase-lbl"><span>Phase 1</span> The whole syllabus, week by week · Nov – Jan</p>
        {"".join(months)}
        <p class="cp-phase-lbl is-pp"><span>Phase 2</span> Past paper sessions · Feb – Apr · {PAPERS[papers_key]}</p>
        <ol class="cp-pp">{pp}</ol>
      </div>
'''


def syllabus_block(page: str) -> str:
    tabs = PAGES[page]
    btns = "\n".join(f'        <button type="button" role="tab" id="tab-{k}" aria-controls="panel-{k}" aria-selected="{"true" if i == 0 else "false"}"'
                     f'{"" if i == 0 else " tabindex=\"-1\""}>{lab}</button>' for i, (k, lab, *_r) in enumerate(tabs))
    panels = "\n".join(panel(*t, first=(i == 0)) for i, t in enumerate(tabs))
    return f'''<!--CP:SYL:START - generated by scripts/class_pages.py, edit the data there -->
  <section class="mc-sec" id="syllabus">
    <div class="container">
      <p class="eyebrow">What each course covers</p>
      <h2 class="mc-h">Week by week, <em>course by course.</em></h2>
      <p class="mc-lede">Pick a course to see exactly what is taught each week. Every week ends with a test on that week's topics, and every chapter comes with its topical past papers as homework.</p>
      <div class="mc-tabs" role="tablist" aria-label="Course">
{btns}
      </div>

{panels}      <div class="cp-every">
        <b>Every single week, in every course</b>
        <ul><li>📖 4 live classes: concept first, then real past-paper questions</li><li>📝 Day 5: a timed test on the week's topics, marked to the mark scheme</li>
        <li>📚 Topical past-paper booklet for homework, official mark scheme after every question</li><li>💬 WhatsApp doubt support between classes</li></ul>
      </div>
    </div>
  </section>
<!--CP:SYL:END-->'''


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    stale = []
    for page in PAGES:
        p = STATIC / page
        src = p.read_text(encoding="utf-8")
        new = render(page, src)
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
