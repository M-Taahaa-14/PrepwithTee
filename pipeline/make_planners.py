#!/usr/bin/env python3
"""
make_planners.py — Generate Cambridge syllabus study planners (.xlsx).

Creates one Excel workbook per syllabus with pastel-coloured topic groups,
sub-topic rows, paper component labels, and dropdown status/confidence tracking.

Usage:
  python -m pipeline.make_planners
  python -m pipeline.make_planners --syllabuses 5054 4024
"""

import argparse
import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).parent.parent
OUT_ROOT = ROOT / "data" / "resources" / "Study Planners"

# ─── PASTEL PALETTE ──────────────────────────────────────────────────────────
# (row_fill_hex, header_fill_hex)
PALETTE = [
    ("D6EAF8", "AED6F1"),   # blue
    ("D5F5E3", "A9DFBF"),   # green
    ("FEF9E7", "FAD7A0"),   # yellow/gold
    ("F4ECF7", "D7BDE2"),   # purple
    ("FDEDEC", "F5B7B1"),   # rose
    ("FEF5E7", "F8C471"),   # orange
    ("E8F8F5", "A2D9CE"),   # teal
    ("FDF2F8", "D98EAE"),   # pink
    ("EAF2FF", "BDD7EE"),   # sky
    ("E8F6F3", "A3E4D7"),   # mint
    ("F9EBEA", "E59866"),   # coral
    ("F0F3FF", "BFC9E8"),   # periwinkle
]

TITLE_BG   = "1B2631"
SUBHD_BG   = "2E4057"
COL_HDR_BG = "1A5276"


# ─── SYLLABUS DATA ────────────────────────────────────────────────────────────

def _load_taxonomy(code: str) -> dict:
    path = ROOT / "taxonomy" / f"{code}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def syllabus_5054() -> dict:
    return {
        "code": "5054",
        "subject": "Physics",
        "level": "O Level",
        "name": "5054 O Level Physics — Cambridge Study Planner",
        "papers": {
            "P1": "Multiple Choice (40 marks, 45 min)",
            "P2": "Theory (80 marks, 1 h 45 min)",
            "P3": "Practical (40 marks, 1 h 15 min)",
        },
        "subfolder": "O Level",
        "topics": [
            {
                "name": "1. Physical Quantities & Measurement",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("SI units — base units and prefixes (kilo, milli, micro, nano)", "P1, P2"),
                    ("Scalars vs vectors — examples and difference", "P1, P2"),
                    ("Measuring length — ruler, Vernier caliper, micrometer", "P1, P2, P3"),
                    ("Measuring area and volume — regular and irregular objects", "P1, P2, P3"),
                    ("Measuring mass — beam balance and electronic balance", "P1, P2, P3"),
                    ("Measuring time — stopwatch and pendulum period", "P1, P2, P3"),
                    ("Precision, accuracy and parallax error", "P1, P2, P3"),
                ],
            },
            {
                "name": "2. Motion",
                "papers": "P1, P2",
                "subtopics": [
                    ("Speed, velocity and acceleration — definitions and units", "P1, P2"),
                    ("Distance–time graphs — gradient = speed; rest; constant speed", "P1, P2"),
                    ("Velocity–time graphs — gradient = acceleration; area = distance", "P1, P2"),
                    ("Equations of uniform motion (v=u+at; s=ut+½at²; v²=u²+2as)", "P2"),
                    ("Free fall and acceleration of gravity (g = 10 m/s²)", "P1, P2"),
                    ("Terminal velocity — forces balanced, no further acceleration", "P1, P2"),
                ],
            },
            {
                "name": "3. Mass & Weight",
                "papers": "P1, P2",
                "subtopics": [
                    ("Mass — definition; measured in kg; a scalar", "P1, P2"),
                    ("Weight — gravitational force; W = mg", "P1, P2"),
                    ("Gravitational field strength g — N/kg on Earth ≈ 10 N/kg", "P1, P2"),
                    ("Difference between mass and weight", "P1, P2"),
                    ("Inertia — resistance to change in motion (Newton's 1st Law)", "P1, P2"),
                ],
            },
            {
                "name": "4. Density",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Density formula ρ = m/V; units kg/m³ and g/cm³", "P1, P2"),
                    ("Measuring density of a regular solid", "P1, P2, P3"),
                    ("Measuring density of an irregular solid (displacement)", "P1, P2, P3"),
                    ("Measuring density of a liquid", "P1, P2, P3"),
                    ("Floating and sinking — comparing densities", "P1, P2"),
                ],
            },
            {
                "name": "5. Forces",
                "papers": "P1, P2",
                "subtopics": [
                    ("Types of forces — contact, friction, air resistance, tension, gravity", "P1, P2"),
                    ("Newton's First Law — object at rest or uniform motion unless acted on", "P1, P2"),
                    ("Newton's Second Law — F = ma (resultant force)", "P1, P2"),
                    ("Newton's Third Law — equal and opposite reaction forces", "P1, P2"),
                    ("Friction — causes, effects, reducing friction", "P1, P2"),
                    ("Hooke's Law — F = ke; limit of proportionality", "P1, P2"),
                    ("Moment of a force — moment = force × perpendicular distance", "P1, P2"),
                    ("Principle of moments — sum of CW moments = sum of ACW moments", "P1, P2"),
                    ("Centre of gravity — definition, finding by experiment", "P1, P2"),
                    ("Stability — stable, unstable, neutral equilibrium", "P1, P2"),
                    ("Circular motion — centripetal force direction", "P1, P2"),
                ],
            },
            {
                "name": "6. Momentum",
                "papers": "P1, P2",
                "subtopics": [
                    ("Momentum — p = mv; units kg m/s", "P1, P2"),
                    ("Impulse — F × t = change in momentum", "P1, P2"),
                    ("Conservation of momentum — isolated system", "P1, P2"),
                    ("Collisions and explosions — applying conservation", "P1, P2"),
                ],
            },
            {
                "name": "7. Energy, Work & Power",
                "papers": "P1, P2",
                "subtopics": [
                    ("Work done — W = Fd (force parallel to displacement)", "P1, P2"),
                    ("Kinetic energy — KE = ½mv²", "P1, P2"),
                    ("Gravitational potential energy — GPE = mgh", "P1, P2"),
                    ("Conservation of energy — KE ↔ GPE; energy never created or destroyed", "P1, P2"),
                    ("Power — P = W/t = Fv; units watts", "P1, P2"),
                    ("Efficiency = useful output energy / total input energy × 100%", "P1, P2"),
                    ("Energy resources — renewable (solar, wind, hydro) vs fossil fuels", "P1, P2"),
                    ("Sankey diagrams — representing energy transfers", "P1, P2"),
                ],
            },
            {
                "name": "8. Pressure",
                "papers": "P1, P2",
                "subtopics": [
                    ("Pressure in solids — P = F/A; units Pa (N/m²)", "P1, P2"),
                    ("Pressure in liquids — P = hρg; increases with depth", "P1, P2"),
                    ("Atmospheric pressure — ~100 000 Pa; shown by experiments", "P1, P2"),
                    ("Manometer — measuring gas pressure differences", "P1, P2"),
                    ("Hydraulic systems — pressure transmitted in liquids", "P1, P2"),
                ],
            },
            {
                "name": "9. Kinetic Particle Model of Matter",
                "papers": "P1, P2",
                "subtopics": [
                    ("States of matter — solid, liquid, gas; properties explained by particles", "P1, P2"),
                    ("Changes of state — melting, boiling, condensing, freezing, sublimation", "P1, P2"),
                    ("Brownian motion — evidence for random particle movement", "P1, P2"),
                    ("Diffusion — particles spreading from high to low concentration", "P1, P2"),
                    ("Gas pressure — due to particle collisions with walls", "P1, P2"),
                    ("Effect of temperature on gas pressure and volume", "P1, P2"),
                ],
            },
            {
                "name": "10. Thermal Properties & Temperature",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Thermal expansion — solids, liquids, gases; practical applications", "P1, P2"),
                    ("Liquid-in-glass thermometer — fixed points, calibration", "P1, P2"),
                    ("Specific heat capacity — Q = mcΔT; units J/(kg·°C)", "P1, P2, P3"),
                    ("Specific latent heat of fusion — Q = mLf", "P1, P2"),
                    ("Specific latent heat of vaporisation — Q = mLv", "P1, P2"),
                    ("Heating and cooling curves — plateau at phase changes", "P1, P2"),
                    ("Evaporation vs boiling — comparison of conditions", "P1, P2"),
                ],
            },
            {
                "name": "11. Transfer of Thermal Energy",
                "papers": "P1, P2",
                "subtopics": [
                    ("Conduction — mechanism via particles/electrons; conductors vs insulators", "P1, P2"),
                    ("Convection — fluid movement due to density differences", "P1, P2"),
                    ("Radiation — infrared; emission and absorption; black vs shiny surfaces", "P1, P2"),
                    ("Vacuum flask — how it reduces all three types of heat transfer", "P1, P2"),
                    ("Applications — house insulation, greenhouse effect, sea breeze", "P1, P2"),
                ],
            },
            {
                "name": "12. General Wave Properties",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Wave terminology — wavelength (λ), frequency (f), amplitude, period (T)", "P1, P2"),
                    ("Wave equation — v = fλ; calculations", "P1, P2"),
                    ("Transverse waves — oscillation perpendicular to direction of travel", "P1, P2"),
                    ("Longitudinal waves — oscillation parallel to direction of travel", "P1, P2"),
                    ("Reflection — angle of incidence = angle of reflection", "P1, P2"),
                    ("Refraction — change of speed causes change of direction", "P1, P2"),
                    ("Diffraction — spreading of waves through gaps/around obstacles", "P1, P2"),
                ],
            },
            {
                "name": "13. Light",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Reflection of light — plane mirror, laws of reflection", "P1, P2"),
                    ("Refraction — Snell's law; n = sin i / sin r", "P1, P2"),
                    ("Total internal reflection — critical angle; sin C = 1/n", "P1, P2"),
                    ("Optical fibres — TIR application in communications", "P1, P2"),
                    ("Converging lens — focal point, focal length, ray diagrams", "P1, P2"),
                    ("Diverging lens — ray diagrams; virtual upright diminished image", "P1, P2"),
                    ("Magnifying glass — object inside focal length; virtual magnified image", "P1, P2"),
                    ("Real vs virtual images — can/cannot be projected on a screen", "P1, P2"),
                ],
            },
            {
                "name": "14. Electromagnetic Spectrum",
                "papers": "P1, P2",
                "subtopics": [
                    ("EM spectrum — order: radio, micro, IR, visible, UV, X-ray, gamma", "P1, P2"),
                    ("All EM waves — travel at c = 3×10⁸ m/s in a vacuum", "P1, P2"),
                    ("Radio waves — communications (TV, radio)", "P1, P2"),
                    ("Microwaves — mobile phones, cooking", "P1, P2"),
                    ("Infrared — remote controls, thermal imaging, night vision", "P1, P2"),
                    ("Ultraviolet — fluorescence, sunburn, sterilisation", "P1, P2"),
                    ("X-rays — medical imaging, airport security; dangers", "P1, P2"),
                    ("Gamma rays — cancer treatment, sterilisation; most penetrating", "P1, P2"),
                ],
            },
            {
                "name": "15. Sound",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Sound as longitudinal waves — compressions and rarefactions", "P1, P2"),
                    ("Sound needs a medium — cannot travel through vacuum", "P1, P2"),
                    ("Speed of sound (~340 m/s in air) vs speed of light", "P1, P2"),
                    ("Pitch — related to frequency; higher frequency = higher pitch", "P1, P2"),
                    ("Loudness — related to amplitude", "P1, P2"),
                    ("Echo — reflection of sound; calculating distances", "P1, P2"),
                    ("Ultrasound (> 20 000 Hz) — medical scanning, sonar, cleaning", "P1, P2"),
                    ("Oscilloscope — reading waveforms for amplitude and frequency", "P1, P2"),
                ],
            },
            {
                "name": "16. Simple Magnetism & Magnetic Fields",
                "papers": "P1, P2",
                "subtopics": [
                    ("Magnetic materials — iron, steel, nickel, cobalt", "P1, P2"),
                    ("Poles — like poles repel, unlike poles attract", "P1, P2"),
                    ("Magnetic field lines — direction and properties", "P1, P2"),
                    ("Induced magnetism — temporary in soft iron", "P1, P2"),
                    ("Making and demagnetising magnets", "P1, P2"),
                    ("Earth's magnetic field — compass always points north", "P1, P2"),
                ],
            },
            {
                "name": "17. Electrical Quantities",
                "papers": "P1, P2",
                "subtopics": [
                    ("Electric charge — positive/negative; unit coulomb (C)", "P1, P2"),
                    ("Electrostatics — charging by friction; attraction/repulsion", "P1, P2"),
                    ("Electric field lines — direction and shape for point charges", "P1, P2"),
                    ("Current — rate of flow of charge; I = Q/t; unit ampere (A)", "P1, P2"),
                    ("Potential difference (voltage) — energy per unit charge; unit volt (V)", "P1, P2"),
                    ("Resistance — opposition to current; unit ohm (Ω)", "P1, P2"),
                    ("Ohm's Law — V = IR (for Ohmic conductors)", "P1, P2"),
                    ("I–V characteristics — Ohmic conductor, filament lamp, diode", "P1, P2, P3"),
                ],
            },
            {
                "name": "18. Electric Circuits",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Series circuits — same current; voltages add; combined R = R1+R2", "P1, P2"),
                    ("Parallel circuits — same voltage; currents add; 1/R = 1/R1+1/R2", "P1, P2"),
                    ("Thermistor (NTC) — resistance decreases as temperature increases", "P1, P2"),
                    ("LDR — resistance decreases as light intensity increases", "P1, P2"),
                    ("Diode — allows current in one direction only", "P1, P2"),
                    ("Potential divider — voltage split proportional to resistance", "P1, P2"),
                    ("EMF vs terminal PD — difference due to internal resistance", "P1, P2"),
                    ("Power in circuits — P = IV = I²R = V²/R", "P1, P2"),
                    ("Energy — E = Pt = IVt; kilowatt-hour (kWh) unit", "P1, P2"),
                ],
            },
            {
                "name": "19. Practical Electricity",
                "papers": "P1, P2",
                "subtopics": [
                    ("Mains supply — live, neutral, earth wires; colour codes", "P1, P2"),
                    ("Fuse — correct rating; melts if current too high", "P1, P2"),
                    ("Circuit breaker (MCB/RCD) — advantages over fuse", "P1, P2"),
                    ("Earth wire and earthing — safety for metal appliances", "P1, P2"),
                    ("Double insulation — no earth wire needed; symbol", "P1, P2"),
                    ("Electrical hazards — frayed cables, overloaded sockets, damp", "P1, P2"),
                    ("Calculating electricity cost — E (kWh) × tariff rate (per unit)", "P1, P2"),
                ],
            },
            {
                "name": "20. Electromagnetic Effects",
                "papers": "P1, P2",
                "subtopics": [
                    ("Magnetic effect of current — field around a wire, solenoid", "P1, P2"),
                    ("Force on current in a field — F = BIL; left-hand rule (Fleming's)", "P1, P2"),
                    ("DC motor — coil in field; split-ring commutator; applications", "P1, P2"),
                    ("Electromagnetic induction — Faraday's law; changing flux", "P1, P2"),
                    ("Induced EMF — factors affecting magnitude (speed, turns, field strength)", "P1, P2"),
                    ("AC generator — slip rings; sinusoidal output", "P1, P2"),
                    ("Transformer — turns ratio Vs/Vp = Ns/Np; step-up and step-down", "P1, P2"),
                    ("Transformer efficiency — 100% ideal; Ip/Is = Ns/Np", "P1, P2"),
                    ("National grid — why high voltage / low current for transmission", "P1, P2"),
                ],
            },
            {
                "name": "21. Uses of an Oscilloscope",
                "papers": "P1, P2",
                "subtopics": [
                    ("Oscilloscope controls — Y-gain (V/div), time-base (ms/div)", "P1, P2"),
                    ("Reading peak voltage and frequency from a trace", "P1, P2"),
                    ("Comparing AC and DC traces", "P1, P2"),
                ],
            },
            {
                "name": "22. Nuclear Model of the Atom",
                "papers": "P1, P2",
                "subtopics": [
                    ("Atomic structure — protons, neutrons, electrons; sizes", "P1, P2"),
                    ("Atomic number (Z), mass number (A), neutron number (N = A−Z)", "P1, P2"),
                    ("Isotopes — same Z, different A; same chemical properties", "P1, P2"),
                    ("Nuclide notation — AₓX notation", "P1, P2"),
                    ("Rutherford scattering experiment — evidence for nucleus", "P1, P2"),
                ],
            },
            {
                "name": "23. Radioactivity",
                "papers": "P1, P2",
                "subtopics": [
                    ("Alpha particles (α) — helium nucleus; ⁴₂He; range ~5 cm in air", "P1, P2"),
                    ("Beta particles (β) — fast electron; range ~1 m in air", "P1, P2"),
                    ("Gamma rays (γ) — EM radiation; no charge; reduced by thick lead", "P1, P2"),
                    ("Penetrating power and ionising ability — inverse relationship", "P1, P2"),
                    ("Background radiation — sources (radon, cosmic, medical, food)", "P1, P2"),
                    ("Half-life — time for activity to halve; calculations with tables/graphs", "P1, P2"),
                    ("Radioactive decay equations — balancing A and Z", "P1, P2"),
                    ("Uses of radioactivity — medical tracers, cancer treatment, dating", "P1, P2"),
                    ("Safety precautions — distance, shielding, handling, storage", "P1, P2"),
                    ("Nuclear fission — splitting heavy nucleus; chain reaction", "P1, P2"),
                    ("Nuclear fusion — joining light nuclei; energy of stars", "P1, P2"),
                ],
            },
            {
                "name": "24. Earth, Solar System & the Universe",
                "papers": "P1, P2",
                "subtopics": [
                    ("Solar system — planets, moons, comets, asteroids", "P1, P2"),
                    ("Gravitational orbits — planets orbit sun; satellites orbit planets", "P1, P2"),
                    ("Orbital period and radius relationship", "P1, P2"),
                    ("Stars — lifecycle: nebula → main sequence → red giant → white dwarf/neutron/BH", "P1, P2"),
                    ("The Universe — galaxies; Milky Way; light-years", "P1, P2"),
                    ("Big Bang — redshift evidence; universe expanding; CMBR", "P1, P2"),
                ],
            },
        ],
    }


def syllabus_4024() -> dict:
    tax = _load_taxonomy("4024")
    topics = []
    for t in tax.get("topics", []):
        subs = []
        for st in t.get("subtopics", []):
            subs.append((st["name"], "P1, P2"))
        if not subs:
            subs = [(t["name"] + " — exam practice", "P1, P2")]
        topics.append({
            "name": t["name"],
            "papers": "P1, P2",
            "subtopics": subs,
        })
    return {
        "code": "4024",
        "subject": "Mathematics",
        "level": "O Level",
        "name": "4024 O Level Mathematics — Cambridge Study Planner",
        "papers": {
            "P1": "Short questions, no calculator (80 marks, 2 h)",
            "P2": "Long questions, calculator allowed (100 marks, 2 h 30 min)",
        },
        "subfolder": "O Level",
        "topics": topics,
    }


def syllabus_5070() -> dict:
    return {
        "code": "5070",
        "subject": "Chemistry",
        "level": "O Level",
        "name": "5070 O Level Chemistry — Cambridge Study Planner",
        "papers": {
            "P1": "Multiple Choice (40 marks, 45 min)",
            "P2": "Theory (80 marks, 1 h 45 min)",
            "P3": "Practical (40 marks, 1 h 15 min)",
        },
        "subfolder": "O Level",
        "topics": [
            {
                "name": "1. Particulate Nature of Matter",
                "papers": "P1, P2",
                "subtopics": [
                    ("Particle model — solids, liquids, gases; properties explained by particles", "P1, P2"),
                    ("Changes of state — melting, boiling, condensing, freezing, sublimation", "P1, P2"),
                    ("Diffusion — movement from high to low concentration; rate factors", "P1, P2"),
                    ("Separating mixtures — filtration, evaporation, crystallisation", "P1, P2"),
                    ("Distillation — simple and fractional; separating liquids by boiling point", "P1, P2"),
                    ("Paper chromatography — Rf value; interpreting chromatograms", "P1, P2, P3"),
                    ("Pure substances — melting/boiling points as purity tests", "P1, P2, P3"),
                ],
            },
            {
                "name": "2. Atomic Structure",
                "papers": "P1, P2",
                "subtopics": [
                    ("Sub-atomic particles — proton (+1, ~1 u), neutron (0, ~1 u), electron (−1, ~0)", "P1, P2"),
                    ("Atomic number (Z) and mass number (A)", "P1, P2"),
                    ("Isotopes — same Z, different A; same chemical properties; examples ¹²C/¹³C/¹⁴C", "P1, P2"),
                    ("Electron configuration — shells (2, 8, 8, …); drawing diagrams", "P1, P2"),
                    ("Periodic Table position — period = number of shells; group = outer electrons", "P1, P2"),
                ],
            },
            {
                "name": "3. Chemical Bonding",
                "papers": "P1, P2",
                "subtopics": [
                    ("Ionic bonding — electron transfer; forming ions; giant ionic lattice", "P1, P2"),
                    ("Properties of ionic compounds — high mp/bp, conduct when molten/dissolved", "P1, P2"),
                    ("Covalent bonding — electron sharing; dot-and-cross diagrams", "P1, P2"),
                    ("Simple molecular structures — low mp/bp; non-conductors (e.g. H₂O, CO₂)", "P1, P2"),
                    ("Giant covalent structures — very high mp/bp; diamond, graphite, SiO₂", "P1, P2"),
                    ("Metallic bonding — positive ions in sea of delocalised electrons", "P1, P2"),
                    ("Properties of metals — malleable, ductile, conduct heat/electricity", "P1, P2"),
                ],
            },
            {
                "name": "4. Stoichiometry (Chemical Calculations)",
                "papers": "P1, P2",
                "subtopics": [
                    ("Relative atomic mass (Ar) and relative molecular mass (Mr)", "P1, P2"),
                    ("Mole concept — n = mass / Mr; Avogadro constant", "P1, P2"),
                    ("Empirical and molecular formulae — from percentage composition", "P1, P2"),
                    ("Molar volume of gases — 24 dm³/mol at r.t.p.", "P1, P2"),
                    ("Concentration — mol/dm³; c = n/V", "P1, P2"),
                    ("Reacting masses — using mole ratios from balanced equations", "P1, P2"),
                    ("Percentage yield and limiting reagent", "P1, P2"),
                ],
            },
            {
                "name": "5. Electricity and Chemistry (Electrolysis)",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Electrolytes vs non-electrolytes — ionic vs covalent", "P1, P2"),
                    ("Electrolysis setup — electrolyte, electrodes (anode/cathode), cell", "P1, P2"),
                    ("Products at electrodes — selective discharge; half-equations", "P1, P2"),
                    ("Electrolysis of dilute H₂SO₄ — H₂ at cathode, O₂ at anode", "P1, P2"),
                    ("Electrolysis of CuSO₄ — copper at cathode, oxygen at anode", "P1, P2, P3"),
                    ("Electrolysis of concentrated brine — H₂, Cl₂, NaOH products", "P1, P2"),
                    ("Electroplating — object as cathode; plating metal as anode", "P1, P2"),
                    ("Industrial electrolysis — aluminium extraction, chlor-alkali industry", "P1, P2"),
                ],
            },
            {
                "name": "6. Chemical Energetics",
                "papers": "P1, P2",
                "subtopics": [
                    ("Exothermic reactions — ΔH negative; heat released to surroundings", "P1, P2"),
                    ("Endothermic reactions — ΔH positive; heat absorbed from surroundings", "P1, P2"),
                    ("Bond breaking (endothermic) and bond making (exothermic)", "P1, P2"),
                    ("Energy level diagrams — reactants, products, activation energy", "P1, P2"),
                    ("Calculating ΔH from bond energies", "P1, P2"),
                    ("Combustion of fuels — measuring enthalpy change", "P1, P2, P3"),
                ],
            },
            {
                "name": "7. Chemical Reactions (Rates of Reaction)",
                "papers": "P1, P2",
                "subtopics": [
                    ("Rate of reaction — definition; measuring by loss of mass or gas volume", "P1, P2, P3"),
                    ("Temperature effect — higher T → more frequent high-energy collisions", "P1, P2"),
                    ("Concentration effect — more particles in volume → more frequent collisions", "P1, P2"),
                    ("Surface area effect — more particles exposed → faster rate", "P1, P2"),
                    ("Catalyst — lowers activation energy; not used up; specificity", "P1, P2"),
                    ("Collision theory explanation — minimum energy (Ea) required", "P1, P2"),
                    ("Interpreting rate graphs — gradient as rate; comparing conditions", "P1, P2, P3"),
                ],
            },
            {
                "name": "8. Acids, Bases and Salts",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Acids — pH < 7; H⁺ ions in solution; examples HCl, H₂SO₄, HNO₃", "P1, P2"),
                    ("Alkalis — pH > 7; OH⁻ ions; examples NaOH, Ca(OH)₂, NH₃", "P1, P2"),
                    ("pH scale — 0–14; indicators (litmus, universal indicator, phenolphthalein)", "P1, P2, P3"),
                    ("Reactions of acids — with metals, bases, carbonates (equations)", "P1, P2"),
                    ("Neutralisation — acid + alkali → salt + water; H⁺ + OH⁻ → H₂O", "P1, P2"),
                    ("Preparing soluble salts — acid + metal / base / carbonate", "P1, P2, P3"),
                    ("Preparing insoluble salts — precipitation (mixing two solutions)", "P1, P2, P3"),
                    ("Titration — procedure, concordant results, calculations", "P1, P2, P3"),
                    ("Ammonium salts — acid + ammonia; fertiliser applications", "P1, P2"),
                ],
            },
            {
                "name": "9. The Periodic Table",
                "papers": "P1, P2",
                "subtopics": [
                    ("Structure — periods (rows) and groups (columns); metals vs non-metals", "P1, P2"),
                    ("Group I — alkali metals; reactivity increases down group; reactions with water", "P1, P2"),
                    ("Group VII — halogens; reactivity decreases down group; displacement reactions", "P1, P2"),
                    ("Halogen reactions — with metals and hydrogen; products and conditions", "P1, P2"),
                    ("Group 0 — noble gases; inert; uses (argon in bulbs, helium in balloons)", "P1, P2"),
                    ("Transition metals — variable oxidation state, form coloured compounds, catalysts", "P1, P2"),
                    ("Trends across Period 3 — metallic → non-metallic character", "P1, P2"),
                ],
            },
            {
                "name": "10. Metals",
                "papers": "P1, P2",
                "subtopics": [
                    ("Reactivity series — K, Na, Ca, Mg, Al, Zn, Fe, Sn, Pb, Cu, Ag, Au", "P1, P2"),
                    ("Reactions with water — Na/K vigorous; Mg/Fe slow; Cu not at all", "P1, P2"),
                    ("Reactions with dilute acids — H₂ produced; writing equations", "P1, P2"),
                    ("Displacement reactions — more reactive displaces less reactive metal", "P1, P2"),
                    ("Extraction of metals — carbon reduction (Fe, Zn); electrolysis (Al)", "P1, P2"),
                    ("Iron and steel production — blast furnace; limestone, coke, iron ore", "P1, P2"),
                    ("Rusting — conditions (water + oxygen); prevention methods", "P1, P2"),
                    ("Aluminium — extraction by electrolysis of bauxite; Hall-Héroult process", "P1, P2"),
                ],
            },
            {
                "name": "11. Air and Water",
                "papers": "P1, P2, P3",
                "subtopics": [
                    ("Composition of air — 78% N₂, 21% O₂, ~1% Ar, 0.04% CO₂", "P1, P2"),
                    ("Tests for gases — O₂ (relights glowing splint), H₂ (squeaky pop), CO₂ (cloudy limewater)", "P1, P2, P3"),
                    ("Test for water — anhydrous CuSO₄ turns blue; cobalt chloride turns pink", "P1, P2, P3"),
                    ("Combustion — complete (CO₂ + H₂O) vs incomplete (CO + soot)", "P1, P2"),
                    ("Pollution — CO, SO₂, NOₓ, particulates; causes and effects", "P1, P2"),
                    ("Water treatment — filtration, sedimentation, chlorination, pH adjustment", "P1, P2"),
                    ("Water hardness — causes (Ca²⁺/Mg²⁺ ions); removing hardness", "P1, P2"),
                    ("Nitrogen cycle — fixation, nitrification, denitrification", "P1, P2"),
                    ("Haber process — N₂ + 3H₂ ⇌ 2NH₃; conditions and economics", "P1, P2"),
                    ("Contact process — manufacture of H₂SO₄; SO₂ → SO₃ → H₂SO₄", "P1, P2"),
                ],
            },
            {
                "name": "12. Organic Chemistry",
                "papers": "P1, P2",
                "subtopics": [
                    ("Homologous series — same functional group; same general formula; trends", "P1, P2"),
                    ("Alkanes — CₙH₂ₙ₊₂; methane to butane; properties; combustion", "P1, P2"),
                    ("Crude oil and fractional distillation — fractions and their uses", "P1, P2"),
                    ("Cracking — breaking large hydrocarbons; conditions; products (alkenes)", "P1, P2"),
                    ("Alkenes — CₙH₂ₙ; double bond; ethene, propene; addition reactions", "P1, P2"),
                    ("Test for alkenes — bromine water decolourises", "P1, P2"),
                    ("Addition polymerisation — monomer → polymer; poly(ethene), PVC", "P1, P2"),
                    ("Ethanol (alcohol) — fermentation (yeast + glucose); industrial synthesis", "P1, P2"),
                    ("Carboxylic acids — ethanoic acid; reactions with metals, carbonates, alcohols", "P1, P2"),
                    ("Esters — esterification (acid + alcohol); fragrances and food flavourings", "P1, P2"),
                    ("Nylon and proteins — condensation polymerisation; peptide/amide bond", "P1, P2"),
                ],
            },
        ],
    }


def syllabus_0625() -> dict:
    return {
        "code": "0625",
        "subject": "Physics",
        "level": "IGCSE",
        "name": "0625 IGCSE Physics — Cambridge Study Planner",
        "papers": {
            "P1": "Multiple Choice Core (30 marks, 45 min)",
            "P2": "Core Theory (80 marks, 1 h 30 min)",
            "P4": "Extended Theory (80 marks, 1 h 30 min)",
            "P5": "Core Practical (40 marks, 1 h 15 min)",
            "P6": "Alternative to Practical (40 marks, 1 h)",
        },
        "subfolder": "IGCSE",
        "topics": [
            {
                "name": "1. Motion, Forces and Energy",
                "papers": "P1, P2, P4",
                "subtopics": [
                    ("Speed and velocity — definitions; v = d/t", "P1, P2, P4"),
                    ("Acceleration — a = Δv/t; units m/s²", "P1, P2, P4"),
                    ("Distance–time graphs — gradient = speed", "P1, P2, P4"),
                    ("Velocity–time graphs — gradient = acceleration; area = distance", "P1, P2, P4"),
                    ("Free fall — g = 10 m/s²; terminal velocity in air", "P1, P2, P4"),
                    ("Newton's First Law — inertia; balanced forces", "P1, P2, P4"),
                    ("Newton's Second Law — F = ma (resultant force)", "P1, P2, P4"),
                    ("Newton's Third Law — action–reaction pairs on different objects", "P1, P2, P4"),
                    ("Weight — W = mg; mass vs weight distinction", "P1, P2, P4"),
                    ("Friction — causes; static and kinetic friction; reducing friction", "P1, P2, P4"),
                    ("Moments — principle of moments; balanced beams", "P1, P2, P4"),
                    ("Centre of gravity — stability and conditions", "P1, P2, P4"),
                    ("Momentum — p = mv; conservation in collisions (Extended)", "P4"),
                    ("Work done — W = Fd; energy forms", "P1, P2, P4"),
                    ("Kinetic and potential energy (KE = ½mv²; GPE = mgh)", "P1, P2, P4"),
                    ("Conservation of energy; efficiency calculations", "P1, P2, P4"),
                    ("Power — P = W/t; unit watt (W)", "P1, P2, P4"),
                    ("Pressure — P = F/A; in fluids P = hρg", "P1, P2, P4"),
                ],
            },
            {
                "name": "2. Thermal Physics",
                "papers": "P1, P2, P4",
                "subtopics": [
                    ("Kinetic particle model — states of matter; Brownian motion; diffusion", "P1, P2, P4"),
                    ("Changes of state — melting, boiling, condensing, freezing", "P1, P2, P4"),
                    ("Thermal expansion — solids, liquids, gases; applications and problems", "P1, P2, P4"),
                    ("Thermometers — liquid-in-glass; fixed points and calibration", "P1, P2, P4"),
                    ("Specific heat capacity — Q = mcΔT; calculations", "P1, P2, P4, P5"),
                    ("Specific latent heat — Q = mL; heating/cooling curve plateau", "P1, P2, P4"),
                    ("Evaporation — factors affecting rate; difference from boiling", "P1, P2, P4"),
                    ("Conduction — through solids; good vs poor conductors", "P1, P2, P4"),
                    ("Convection — in fluids; convection currents; applications", "P1, P2, P4"),
                    ("Radiation — infrared emission/absorption; black vs shiny surfaces", "P1, P2, P4"),
                    ("Vacuum flask — reducing all three heat transfer types", "P1, P2, P4"),
                ],
            },
            {
                "name": "3. Waves and the Electromagnetic Spectrum",
                "papers": "P1, P2, P4",
                "subtopics": [
                    ("Wave properties — wavelength, frequency, amplitude, period; v = fλ", "P1, P2, P4"),
                    ("Transverse and longitudinal waves — examples of each", "P1, P2, P4"),
                    ("Reflection — laws of reflection; plane mirror images", "P1, P2, P4"),
                    ("Refraction — Snell's law; n = sin i / sin r; real and apparent depth", "P1, P2, P4"),
                    ("Total internal reflection — critical angle; optical fibres", "P1, P2, P4"),
                    ("Lenses — converging and diverging; ray diagrams; magnification", "P1, P2, P4"),
                    ("Dispersion — white light splitting into spectrum by prism", "P1, P2, P4"),
                    ("EM spectrum — order, properties (all travel at c), uses and dangers", "P1, P2, P4"),
                    ("Sound — longitudinal; needs medium; pitch, loudness; echo; ultrasound", "P1, P2, P4"),
                    ("Speed of sound (~340 m/s); comparing to light speed", "P1, P2, P4"),
                    ("Oscilloscope — reading frequency, amplitude, period from trace", "P1, P2, P4, P5"),
                ],
            },
            {
                "name": "4. Electricity and Magnetism",
                "papers": "P1, P2, P4",
                "subtopics": [
                    ("Electrostatics — charging, electric field lines, uses and dangers", "P1, P2, P4"),
                    ("Current — I = Q/t; conventional current vs electron flow", "P1, P2, P4"),
                    ("Voltage — EMF and PD; energy per unit charge", "P1, P2, P4"),
                    ("Resistance — Ohm's law V = IR; non-ohmic conductors", "P1, P2, P4"),
                    ("I–V characteristics — resistor, lamp, diode", "P1, P2, P4, P5"),
                    ("Series circuits — current same; voltage divides", "P1, P2, P4"),
                    ("Parallel circuits — voltage same; current divides", "P1, P2, P4"),
                    ("Power and energy — P = IV; kWh calculations; electricity bills", "P1, P2, P4"),
                    ("Practical electricity — fuse, earth wire, circuit breaker; safety", "P1, P2, P4"),
                    ("Magnetism — field lines; poles; induced magnetism", "P1, P2, P4"),
                    ("Electromagnets — solenoid; uses (relay, motor, loudspeaker)", "P1, P2, P4"),
                    ("Motor effect — F on current in field; left-hand rule", "P1, P2, P4"),
                    ("DC motor — how it works; commutator; applications", "P1, P2, P4"),
                    ("Electromagnetic induction — Faraday's law; factors affecting EMF", "P1, P2, P4"),
                    ("AC generator — slip rings; alternating output", "P1, P2, P4"),
                    ("Transformer — turns ratio; efficiency; national grid (Extended)", "P4"),
                ],
            },
            {
                "name": "5. Nuclear Physics",
                "papers": "P1, P2, P4",
                "subtopics": [
                    ("Atomic structure — protons, neutrons, electrons; nucleus", "P1, P2, P4"),
                    ("Nuclide notation — mass number, atomic number, isotopes", "P1, P2, P4"),
                    ("Nuclear radiation — alpha, beta, gamma; properties comparison", "P1, P2, P4"),
                    ("Penetrating power and ionisation ability", "P1, P2, P4"),
                    ("Background radiation — sources; correcting measurements", "P1, P2, P4"),
                    ("Half-life — definition; calculations from data and graphs", "P1, P2, P4"),
                    ("Uses of radioactivity — medical, industrial, carbon dating", "P1, P2, P4"),
                    ("Safety precautions when handling radioactive materials", "P1, P2, P4"),
                    ("Nuclear fission and fusion — energy release; stars; reactors (Extended)", "P4"),
                ],
            },
        ],
    }


def syllabus_0580() -> dict:
    tax = _load_taxonomy("0580")
    # 0580 has same structure as 4024 taxonomy; use it directly
    topics = []
    for t in tax.get("topics", []):
        subs = []
        for st in t.get("subtopics", []):
            subs.append((st["name"], "P2, P4"))
        if not subs:
            subs = [(t["name"] + " — exam practice", "P2, P4")]
        topics.append({
            "name": t["name"],
            "papers": "P2, P4",
            "subtopics": subs,
        })
    return {
        "code": "0580",
        "subject": "Mathematics",
        "level": "IGCSE",
        "name": "0580 IGCSE Mathematics (Extended) — Cambridge Study Planner",
        "papers": {
            "P2": "Extended Short (70 marks, 1 h 30 min)",
            "P4": "Extended Long (130 marks, 2 h 30 min)",
        },
        "subfolder": "IGCSE",
        "topics": topics,
    }


def syllabus_0620() -> dict:
    return {
        "code": "0620",
        "subject": "Chemistry",
        "level": "IGCSE",
        "name": "0620 IGCSE Chemistry — Cambridge Study Planner",
        "papers": {
            "P1": "Multiple Choice Core (40 marks, 45 min)",
            "P2": "Core Theory (80 marks, 1 h 30 min)",
            "P4": "Extended Theory (80 marks, 1 h 30 min)",
            "P5": "Core Practical (40 marks, 1 h 15 min)",
            "P6": "Alternative to Practical (40 marks, 1 h)",
        },
        "subfolder": "IGCSE",
        "topics": [
            {"name": "1. The Particulate Nature of Matter",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("States of matter — properties; particle diagrams", "P1, P2, P4"),
                 ("Changes of state — names and energy changes", "P1, P2, P4"),
                 ("Kinetic particle theory — Brownian motion; diffusion", "P1, P2, P4"),
                 ("Separating mixtures — filtration, crystallisation, distillation, chromatography", "P1, P2, P4, P5, P6"),
                 ("Rf values — paper/thin-layer chromatography", "P1, P2, P4, P5, P6"),
             ]},
            {"name": "2. Experimental Techniques",
             "papers": "P1, P2, P4, P5, P6",
             "subtopics": [
                 ("Apparatus — test tube, beaker, burette, pipette, volumetric flask", "P5, P6"),
                 ("Measuring — mass, volume, temperature accurately", "P5, P6"),
                 ("Planning experiments — identifying variables, fair test", "P5, P6"),
                 ("Hazards and safety — COSHH symbols; safe handling", "P5, P6"),
                 ("Titration technique — concordant results; reading burette", "P5, P6"),
             ]},
            {"name": "3. Atoms, Elements and Compounds",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Atomic structure — protons, neutrons, electrons; atomic/mass number", "P1, P2, P4"),
                 ("Isotopes — same element, different neutrons; examples", "P1, P2, P4"),
                 ("Electron configuration — shells (2,8,8…); linking to Periodic Table", "P1, P2, P4"),
                 ("Ionic bonding — electron transfer; forming ions; lattice energy", "P1, P2, P4"),
                 ("Ionic properties — high mp/bp; conducts when molten/dissolved", "P1, P2, P4"),
                 ("Covalent bonding — electron sharing; dot-and-cross; polarity (Ext)", "P1, P2, P4"),
                 ("Simple molecular vs giant covalent — properties and examples", "P1, P2, P4"),
                 ("Metallic bonding and metallic properties", "P1, P2, P4"),
             ]},
            {"name": "4. Stoichiometry",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Relative atomic/molecular mass (Ar, Mr)", "P1, P2, P4"),
                 ("Mole concept — n = mass/Mr; Avogadro constant", "P1, P2, P4"),
                 ("Empirical and molecular formulae — from combustion analysis", "P1, P2, P4"),
                 ("Molar gas volume — 24 dm³/mol at r.t.p.", "P1, P2, P4"),
                 ("Concentration — mol/dm³; dilution calculations", "P1, P2, P4"),
                 ("Reacting masses — mole ratios from balanced equations", "P1, P2, P4"),
                 ("Percentage yield and limiting reagent (Extended)", "P4"),
             ]},
            {"name": "5. Electricity and Chemistry",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Electrolytes — ionic compounds conduct when molten or in solution", "P1, P2, P4"),
                 ("Electrolysis — setup; anode/cathode; direction of ion movement", "P1, P2, P4"),
                 ("Electrolysis of molten compounds — simple binary electrolytes", "P1, P2, P4"),
                 ("Electrolysis of solutions — selective discharge; ion concentration effects", "P1, P2, P4"),
                 ("Products from brine, dilute H₂SO₄, CuSO₄ solution", "P1, P2, P4"),
                 ("Electroplating and its applications", "P1, P2, P4"),
                 ("Industrial uses — aluminium extraction; purification of copper", "P1, P2, P4"),
             ]},
            {"name": "6. Chemical Energetics",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Exothermic reactions — temperature rise; examples", "P1, P2, P4"),
                 ("Endothermic reactions — temperature fall; examples", "P1, P2, P4"),
                 ("Bond breaking/making — endothermic/exothermic; net ΔH", "P1, P2, P4"),
                 ("Energy level diagrams — labelling Ea, ΔH, reactants, products", "P1, P2, P4"),
                 ("Bond energy calculations — Hess's law extension (Extended)", "P4"),
             ]},
            {"name": "7. Chemical Reactions",
             "papers": "P1, P2, P4, P5, P6",
             "subtopics": [
                 ("Rate of reaction — definition; measuring methods (gas, mass, colour)", "P1, P2, P4, P5, P6"),
                 ("Effect of temperature on rate — collision theory; Ea", "P1, P2, P4"),
                 ("Effect of concentration on rate — collision frequency", "P1, P2, P4"),
                 ("Effect of surface area on rate — powder vs lumps", "P1, P2, P4"),
                 ("Catalysts — mode of action; industrial examples; enzymes", "P1, P2, P4"),
                 ("Reversible reactions and equilibrium (Extended)", "P4"),
                 ("Le Chatelier's principle — effect of T, P, concentration on equilibrium (Ext)", "P4"),
             ]},
            {"name": "8. Acids, Bases and Salts",
             "papers": "P1, P2, P4, P5, P6",
             "subtopics": [
                 ("Acids — H⁺ ions; strong vs weak; pH scale; common acids", "P1, P2, P4"),
                 ("Bases and alkalis — OH⁻ ions; strong vs weak (Extended)", "P1, P2, P4"),
                 ("Indicators — litmus, universal, phenolphthalein, methyl orange", "P1, P2, P4, P5, P6"),
                 ("Acid reactions — with metals, metal oxides, carbonates (equations)", "P1, P2, P4"),
                 ("Neutralisation and salt preparation (soluble salts)", "P1, P2, P4, P5, P6"),
                 ("Insoluble salt preparation — precipitation method", "P1, P2, P4, P5, P6"),
                 ("Titration calculations — finding concentration", "P1, P2, P4, P5, P6"),
                 ("Ammonium salts and NH₃ (base without hydroxide) (Ext)", "P4"),
             ]},
            {"name": "9. The Periodic Table",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Arrangement — periods, groups, metals/non-metals/metalloids", "P1, P2, P4"),
                 ("Group I alkali metals — increasing reactivity; reaction with water", "P1, P2, P4"),
                 ("Group VII halogens — decreasing reactivity; displacement reactions", "P1, P2, P4"),
                 ("Halide test — silver nitrate; colours of precipitates", "P1, P2, P4"),
                 ("Group 0 noble gases — inert; uses; electronic configuration reason", "P1, P2, P4"),
                 ("Transition metals — properties; coloured compounds; catalytic use", "P1, P2, P4"),
                 ("Trends in Period 3 — metallic to non-metallic character (Ext)", "P4"),
             ]},
            {"name": "10. Metals",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Reactivity series — order; predicting reactions", "P1, P2, P4"),
                 ("Metal reactions — water, steam, dilute acids; writing equations", "P1, P2, P4"),
                 ("Displacement reactions — metal + salt solution; examples", "P1, P2, P4"),
                 ("Extraction of metals — by electrolysis (reactive) vs carbon (less reactive)", "P1, P2, P4"),
                 ("Blast furnace — iron production; role of each material", "P1, P2, P4"),
                 ("Rusting — requirements; prevention (painting, galvanising, sacrificial)", "P1, P2, P4"),
                 ("Aluminium — properties; extraction by electrolysis", "P1, P2, P4"),
                 ("Alloys — steel, bronze, brass; properties vs pure metals (Ext)", "P4"),
             ]},
            {"name": "11. Air and Water",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Composition of air — percentages of N₂, O₂, Ar, CO₂", "P1, P2, P4"),
                 ("Testing gases — O₂, H₂, CO₂, NH₃, Cl₂; reagents and results", "P1, P2, P4, P5, P6"),
                 ("Combustion — complete vs incomplete; products", "P1, P2, P4"),
                 ("Air pollution — CO, SO₂, NOₓ; acid rain; global warming", "P1, P2, P4"),
                 ("Water — purification process; chlorination; fluoridation", "P1, P2, P4"),
                 ("Fertilisers — Haber process (NH₃); Ostwald process (HNO₃)", "P1, P2, P4"),
                 ("Greenhouse effect — CO₂, CH₄; consequences; reducing emissions", "P1, P2, P4"),
             ]},
            {"name": "12. Organic Chemistry",
             "papers": "P1, P2, P4",
             "subtopics": [
                 ("Homologous series — definition; general formula; gradual change in properties", "P1, P2, P4"),
                 ("Alkanes — naming; combustion reactions; substitution (Ext)", "P1, P2, P4"),
                 ("Crude oil — fractional distillation; fraction names and uses", "P1, P2, P4"),
                 ("Cracking — thermal cracking; products; why done industrially", "P1, P2, P4"),
                 ("Alkenes — double bond; addition reactions (H₂, Br₂, HBr, H₂O)", "P1, P2, P4"),
                 ("Test for alkenes — bromine water; conditions", "P1, P2, P4"),
                 ("Addition polymerisation — poly(ethene), PVC; structure of polymers", "P1, P2, P4"),
                 ("Alcohols — ethanol; fermentation; industrial production; combustion", "P1, P2, P4"),
                 ("Carboxylic acids — ethanoic acid; esterification reaction", "P1, P2, P4"),
                 ("Esters — preparation; uses as fragrances and plasticisers", "P1, P2, P4"),
                 ("Condensation polymerisation — nylon; polyesters; peptide bonds (Ext)", "P4"),
                 ("Natural polymers — proteins, starch, DNA (Ext)", "P4"),
             ]},
        ],
    }


def syllabus_9618() -> dict:
    tax = _load_taxonomy("9618")
    topics = []
    for t in tax.get("topics", []):
        papers_str = ", ".join(f"P{p}" for p in t.get("papers", [1]))
        subs = [(kw.capitalize() + " — theory and exam questions", papers_str)
                for kw in (t.get("keywords", [])[:8])]
        if not subs:
            subs = [(t["name"] + " — exam practice", papers_str)]
        topics.append({
            "name": t["name"],
            "papers": papers_str,
            "subtopics": subs,
        })
    return {
        "code": "9618",
        "subject": "Computer Science",
        "level": "A Level",
        "name": "9618 A Level Computer Science — Cambridge Study Planner",
        "papers": {
            "P1": "Theory (75 marks, 1 h 30 min) — AS",
            "P2": "Written Algorithms (75 marks, 2 h) — AS",
            "P3": "Advanced Theory (75 marks, 1 h 30 min) — A2",
            "P4": "Practical Programming (75 marks, 2 h 30 min) — A2",
        },
        "subfolder": "A Level",
        "topics": topics,
    }


def syllabus_9702() -> dict:
    return {
        "code": "9702",
        "subject": "Physics",
        "level": "A Level",
        "name": "9702 A Level Physics — Cambridge Study Planner",
        "papers": {
            "P1": "Multiple Choice AS (30 marks, 1 h)",
            "P2": "AS Structured (60 marks, 1 h 15 min)",
            "P3": "AS Practical (40 marks, 2 h)",
            "P4": "A2 Structured (100 marks, 2 h)",
            "P5": "A2 Planning & Analysis (30 marks, 1 h 15 min)",
        },
        "subfolder": "A Level",
        "topics": [
            {"name": "1. Physical Quantities and Units", "papers": "P1, P2",
             "subtopics": [
                 ("SI base units — kg, m, s, A, K, mol, cd; derived units", "P1, P2"),
                 ("Homogeneity of equations — checking using base units", "P1, P2"),
                 ("Scalars and vectors — addition; resolving components", "P1, P2"),
                 ("Significant figures, precision, accuracy and uncertainty", "P1, P2, P3"),
                 ("Systematic vs random errors; reducing uncertainty", "P1, P2, P3"),
                 ("Percentage uncertainty; combining uncertainties (add in quadrature)", "P1, P2, P3"),
                 ("Graphs — best-fit line; gradient; y-intercept; log-log/ln graphs", "P2, P3, P5"),
             ]},
            {"name": "2. Kinematics", "papers": "P1, P2",
             "subtopics": [
                 ("Displacement, velocity, acceleration — definitions and equations", "P1, P2"),
                 ("Equations of uniform acceleration (SUVAT)", "P1, P2"),
                 ("Velocity–time and displacement–time graphs", "P1, P2"),
                 ("Free fall — g = 9.81 m/s²; measuring g by free fall experiment", "P1, P2, P3"),
                 ("Projectile motion — horizontal and vertical components independent", "P1, P2"),
             ]},
            {"name": "3. Dynamics", "papers": "P1, P2",
             "subtopics": [
                 ("Newton's Laws — first, second (F = ma), third", "P1, P2"),
                 ("Linear momentum — p = mv; conservation in closed system", "P1, P2"),
                 ("Impulse — Ft = Δp; area under F–t graph", "P1, P2"),
                 ("Elastic vs inelastic collisions — KE conservation", "P1, P2"),
             ]},
            {"name": "4. Forces, Density and Pressure", "papers": "P1, P2",
             "subtopics": [
                 ("Types of forces — weight, normal, tension, friction, upthrust", "P1, P2"),
                 ("Turning effect of a force — moment = Fd; principle of moments", "P1, P2"),
                 ("Couple — two equal opposite non-collinear forces; torque = Fd", "P1, P2"),
                 ("Centre of gravity — equilibrium conditions", "P1, P2"),
                 ("Density — ρ = m/V; measuring density of solids and liquids", "P1, P2, P3"),
                 ("Pressure — P = F/A; in fluids P = hρg", "P1, P2"),
                 ("Upthrust — Archimedes' principle; floating conditions", "P1, P2"),
             ]},
            {"name": "5. Work, Energy and Power", "papers": "P1, P2",
             "subtopics": [
                 ("Work — W = Fd cosθ; unit joule", "P1, P2"),
                 ("Gravitational PE (ΔEp = mgh) and KE (Ek = ½mv²)", "P1, P2"),
                 ("Conservation of energy; energy conversions", "P1, P2"),
                 ("Power — P = W/t = Fv; unit watt", "P1, P2"),
                 ("Efficiency — useful output/input; improving machines", "P1, P2"),
             ]},
            {"name": "6. Deformation of Solids", "papers": "P1, P2",
             "subtopics": [
                 ("Tensile force; extension and Hooke's law (F = ke)", "P1, P2"),
                 ("Limit of proportionality and elastic limit", "P1, P2"),
                 ("Elastic vs plastic deformation", "P1, P2"),
                 ("Stress, strain and Young modulus (E = stress/strain)", "P1, P2"),
                 ("Stress–strain graph — features: proportional, elastic, plastic, breaking", "P1, P2"),
                 ("Energy stored in stretched spring — E = ½Fe = ½ke²", "P1, P2"),
             ]},
            {"name": "7. Waves", "papers": "P1, P2",
             "subtopics": [
                 ("Progressive waves — λ, f, T, v = fλ; phase difference", "P1, P2"),
                 ("Transverse and longitudinal waves — examples; polarisation of transverse", "P1, P2"),
                 ("Intensity — I = P/A; I ∝ (amplitude)² ; I ∝ 1/r²", "P1, P2"),
                 ("Electromagnetic waves — properties; c = 3×10⁸ m/s", "P1, P2"),
                 ("Reflection and refraction — laws; total internal reflection", "P1, P2"),
                 ("Diffraction — condition λ ≈ gap size; Huygens' principle", "P1, P2"),
             ]},
            {"name": "8. Superposition", "papers": "P1, P2",
             "subtopics": [
                 ("Principle of superposition — resultant displacement", "P1, P2"),
                 ("Interference — constructive and destructive; path difference conditions", "P1, P2"),
                 ("Two-source interference — Young's double slit; λ = ax/D", "P1, P2"),
                 ("Diffraction grating — d sinθ = nλ; maxima pattern", "P1, P2"),
                 ("Stationary waves — nodes and antinodes; formation; equation λ = 2L/n", "P1, P2"),
                 ("Measuring speed of sound using resonance tube experiment", "P1, P2, P3"),
             ]},
            {"name": "9. Electricity", "papers": "P1, P2",
             "subtopics": [
                 ("Charge — Q; electron charge e = 1.6×10⁻¹⁹ C", "P1, P2"),
                 ("Current — I = ΔQ/Δt; conventional current direction", "P1, P2"),
                 ("Potential difference and EMF — energy per unit charge", "P1, P2"),
                 ("Resistance — Ohm's law; I–V characteristics (ohmic and non-ohmic)", "P1, P2, P3"),
                 ("Resistivity — ρ = RA/L; measuring by experiment", "P1, P2, P3"),
                 ("Power — P = IV = I²R = V²/R", "P1, P2"),
             ]},
            {"name": "10. D.C. Circuits", "papers": "P1, P2",
             "subtopics": [
                 ("Kirchhoff's first law — ΣI = 0 at a junction", "P1, P2"),
                 ("Kirchhoff's second law — ΣE = ΣIR around a loop", "P1, P2"),
                 ("Series and parallel combinations — total R; V and I relationships", "P1, P2"),
                 ("EMF and internal resistance — terminal PD = E − Ir", "P1, P2"),
                 ("Potential divider — voltage divider calculations; potentiometer", "P1, P2"),
             ]},
            {"name": "11. Particle Physics (AS)", "papers": "P1, P2",
             "subtopics": [
                 ("Atomic structure — nucleus, protons, neutrons; electrons in shells", "P1, P2"),
                 ("Specific charge of particles — q/m for proton and electron", "P1, P2"),
                 ("Isotopes — same Z, different A; radioactive isotopes", "P1, P2"),
                 ("Nuclear emissions — α, β⁻, β⁺, γ; properties; decay equations", "P1, P2"),
                 ("Photoelectric effect — evidence for photon model; hf = Φ + Ek(max)", "P1, P2"),
                 ("Electron energy levels — photon emission/absorption; line spectra", "P1, P2"),
                 ("Wave-particle duality — de Broglie wavelength λ = h/mv", "P1, P2"),
             ]},
            {"name": "12. Motion in a Circle (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Angular velocity ω = v/r = 2πf; period T = 2π/ω", "P1, P4"),
                 ("Centripetal acceleration a = v²/r = ω²r", "P1, P4"),
                 ("Centripetal force F = mv²/r = mω²r; direction always inward", "P1, P4"),
                 ("Applications — banked roads, satellites, vertical circles", "P4"),
             ]},
            {"name": "13. Gravitational Fields (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Gravitational field strength g = F/m; unit N/kg", "P1, P4"),
                 ("Newton's law of gravitation — F = Gm₁m₂/r²", "P1, P4"),
                 ("Gravitational field of a sphere — g = GM/r²", "P1, P4"),
                 ("Gravitational potential φ = −GM/r; equipotentials", "P1, P4"),
                 ("Satellite orbits — geostationary; orbital speed and period", "P1, P4"),
                 ("Escape velocity — v = √(2GM/r)", "P4"),
             ]},
            {"name": "14. Oscillations / SHM (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("SHM definition — a = −ω²x; restoring force proportional to displacement", "P1, P4"),
                 ("Equations — x = x₀sinωt; v = v₀cosωt; v = ω√(x₀²−x²)", "P1, P4"),
                 ("Energy in SHM — KE + PE = constant; graphs", "P1, P4"),
                 ("Damping — light, heavy, critical; overdamped vs underdamped", "P1, P4"),
                 ("Resonance — natural frequency; driving frequency; applications", "P4"),
                 ("Simple pendulum — T = 2π√(L/g); measuring g experiment", "P1, P4, P3"),
             ]},
            {"name": "15. Temperature and Ideal Gases (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Thermal equilibrium; absolute zero (0 K = −273 °C)", "P1, P4"),
                 ("Kelvin and Celsius — T(K) = T(°C) + 273", "P1, P4"),
                 ("Ideal gas laws — Boyle's, Charles', Pressure–Temperature", "P1, P4"),
                 ("Ideal gas equation — pV = nRT = NkT", "P1, P4"),
                 ("Assumptions of an ideal gas — kinetic theory", "P1, P4"),
                 ("Mean kinetic energy — Ek = 3/2 kT; mean square speed", "P1, P4"),
             ]},
            {"name": "16. Thermodynamics (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Internal energy — sum of KE and PE of molecules", "P1, P4"),
                 ("First law of thermodynamics — ΔU = q + w", "P1, P4"),
                 ("Specific heat capacity — Q = mcΔT", "P1, P4"),
                 ("Specific latent heat — Q = mL", "P1, P4"),
             ]},
            {"name": "17. Electric Fields (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Electric force — Coulomb's law F = kQ₁Q₂/r²", "P1, P4"),
                 ("Electric field strength E = F/Q; E = kQ/r² for point charge", "P1, P4"),
                 ("Uniform electric field — E = V/d; field between plates", "P1, P4"),
                 ("Electric potential V = kQ/r; work done W = QΔV", "P1, P4"),
                 ("Motion of charges in electric fields — deflection in CRT", "P4"),
             ]},
            {"name": "18. Capacitance (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Capacitance — C = Q/V; unit farad (F)", "P1, P4"),
                 ("Parallel plate capacitor — C = ε₀εrA/d", "P1, P4"),
                 ("Series and parallel combinations of capacitors", "P1, P4"),
                 ("Energy stored — W = ½CV² = ½QV = Q²/2C", "P1, P4"),
                 ("Charging and discharging — Q = Q₀e^(−t/RC); time constant τ = RC", "P1, P4"),
             ]},
            {"name": "19. Magnetic Fields (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Magnetic flux density B; unit tesla (T)", "P1, P4"),
                 ("Force on current in field — F = BIL sinθ; left-hand rule", "P1, P4"),
                 ("Force on moving charge — F = BQv; circular motion in field", "P1, P4"),
                 ("Magnetic field due to current — in wire, solenoid", "P1, P4"),
             ]},
            {"name": "20. Electromagnetic Induction (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Magnetic flux Φ = BA cosθ; flux linkage NΦ", "P1, P4"),
                 ("Faraday's law — EMF = −d(NΦ)/dt", "P1, P4"),
                 ("Lenz's law — induced current opposes change in flux", "P1, P4"),
                 ("Applications — generator, transformer, back-EMF in motor", "P1, P4"),
             ]},
            {"name": "21. Alternating Currents (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("AC characteristics — peak value, rms value (Vrms = V₀/√2)", "P1, P4"),
                 ("Transformers — turns ratio; efficiency; transmission of electricity", "P1, P4"),
                 ("Rectification — half-wave, full-wave; smoothing with capacitor", "P4"),
             ]},
            {"name": "22. Quantum Physics (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Photoelectric effect — stopping potential; threshold frequency; work function", "P1, P4"),
                 ("Photon energy — E = hf; intensity and number of photons", "P1, P4"),
                 ("Energy levels in atoms — emission and absorption spectra", "P1, P4"),
                 ("Wave-particle duality — electron diffraction; de Broglie λ = h/p", "P1, P4"),
                 ("Uncertainty principle — Δp·Δx ≥ h/4π (qualitative)", "P4"),
             ]},
            {"name": "23. Nuclear Physics (A2)", "papers": "P1, P4",
             "subtopics": [
                 ("Nuclear structure — nuclide notation; proton and neutron numbers", "P1, P4"),
                 ("Mass defect and binding energy — E = mc²", "P1, P4"),
                 ("Nuclear fission — chain reaction; critical mass; energy release", "P1, P4"),
                 ("Nuclear fusion — conditions; energy release; stars", "P1, P4"),
                 ("Radioactive decay — α, β⁻, β⁺, electron capture, γ; decay equations", "P1, P4"),
                 ("Activity and decay law — A = λN; N = N₀e^(−λt); half-life T½ = ln2/λ", "P1, P4"),
             ]},
        ],
    }


# ─── EXCEL BUILDER ────────────────────────────────────────────────────────────

def _thin():
    s = Side(style="thin", color="D0D0D0")
    return Border(left=s, right=s, top=s, bottom=s)

def _fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def _font(bold=False, size=11, color="1C1C1C", italic=False):
    return Font(name="Calibri", bold=bold, size=size, color=color, italic=italic)

def _align(h="left", v="center", wrap=True):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def build_workbook(syl: dict) -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Study Planner"

    # Column widths
    widths = {"A": 5, "B": 50, "C": 16, "D": 22, "E": 16, "F": 14, "G": 35}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    row = 1

    # ── Title ────────────────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:G{row}")
    ws.row_dimensions[row].height = 52
    c = ws.cell(row, 1, syl["name"])
    c.font = Font(name="Calibri", bold=True, size=22, color="FFFFFF")
    c.fill = _fill(TITLE_BG)
    c.alignment = _align("center", "center")
    row += 1

    # ── Paper sub-header ─────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:G{row}")
    ws.row_dimensions[row].height = 28
    subtitle = "   ·   ".join(f"{k}: {v}" for k, v in syl["papers"].items())
    c = ws.cell(row, 1, subtitle)
    c.font = Font(name="Calibri", size=9, color="E0E0E0", italic=True)
    c.fill = _fill(SUBHD_BG)
    c.alignment = _align("center", "center", wrap=False)
    row += 1

    # ── How to use ───────────────────────────────────────────────────────────
    ws.merge_cells(f"A{row}:G{row}")
    ws.row_dimensions[row].height = 24
    c = ws.cell(row, 1,
        "How to use:  Update the STATUS column as you study.  Rate your CONFIDENCE (1 = shaky · 5 = mastered).  "
        "Add study dates and personal notes.  Aim for all rows ✓ Done before your exam.")
    c.font = Font(name="Calibri", size=9, color="4A4A4A", italic=True)
    c.fill = _fill("F8F8F0")
    c.alignment = _align("left", "center", wrap=False)
    row += 1

    # ── Column headers ────────────────────────────────────────────────────────
    ws.row_dimensions[row].height = 34
    for col_i, header in enumerate(
        ["#", "Sub-Topic / Learning Objective", "Paper(s)", "Status", "Confidence (1–5)", "Date Studied", "Notes"],
        start=1,
    ):
        c = ws.cell(row, col_i, header)
        c.font = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
        c.fill = _fill(COL_HDR_BG)
        c.alignment = _align("center", "center", wrap=False)
        c.border = _thin()
    row += 1

    # ── Data validation ──────────────────────────────────────────────────────
    status_dv = DataValidation(
        type="list",
        formula1='"Not Started,In Progress,Done ✓,Needs Review ⚠"',
        showDropDown=False, showErrorMessage=False,
    )
    ws.add_data_validation(status_dv)
    conf_dv = DataValidation(type="list", formula1='"1,2,3,4,5"',
                             showDropDown=False, showErrorMessage=False)
    ws.add_data_validation(conf_dv)

    # ── Topics ────────────────────────────────────────────────────────────────
    sub_n = 1
    for t_idx, topic in enumerate(syl["topics"]):
        row_hex, hdr_hex = PALETTE[t_idx % len(PALETTE)]

        # Topic group header
        ws.merge_cells(f"A{row}:G{row}")
        ws.row_dimensions[row].height = 30
        c = ws.cell(row, 1, f"  {topic['name']}   ·   {topic['papers']}")
        c.font = Font(name="Calibri", bold=True, size=12, color="1C2833")
        c.fill = _fill(hdr_hex)
        c.alignment = _align("left", "center", wrap=False)
        c.border = _thin()
        row += 1

        for sub_name, papers_str in topic["subtopics"]:
            ws.row_dimensions[row].height = 22
            row_data = [
                (1, str(sub_n)),
                (2, sub_name),
                (3, papers_str),
                (4, "Not Started"),
                (5, ""),
                (6, ""),
                (7, ""),
            ]
            for col_i, val in row_data:
                c = ws.cell(row, col_i, val)
                c.fill = _fill(row_hex)
                c.font = _font(size=10 if col_i == 2 else 11)
                c.border = _thin()
                c.alignment = _align(
                    h="center" if col_i in (1, 3, 4, 5, 6) else "left",
                    v="center",
                    wrap=(col_i in (2, 7)),
                )
            status_dv.add(ws.cell(row, 4))
            conf_dv.add(ws.cell(row, 5))
            sub_n += 1
            row += 1

    # ── Footer ────────────────────────────────────────────────────────────────
    row += 1
    ws.merge_cells(f"A{row}:G{row}")
    ws.row_dimensions[row].height = 20
    c = ws.cell(row, 1,
        f"© PrepWithTee · Cambridge {syl['level']} {syl['subject']} ({syl['code']}) · prepwithtee.com  ·  "
        f"Total sub-topics: {sub_n - 1}")
    c.font = Font(name="Calibri", size=9, color="AAAAAA", italic=True)
    c.alignment = _align("center", "center", wrap=False)

    # Freeze top 4 rows (title + subtitle + howto + headers)
    ws.freeze_panes = ws.cell(5, 1)

    return wb


# ─── MAIN ─────────────────────────────────────────────────────────────────────

ALL_SYLLABUSES = {
    "5054": syllabus_5054,
    "4024": syllabus_4024,
    "5070": syllabus_5070,
    "0625": syllabus_0625,
    "0580": syllabus_0580,
    "0620": syllabus_0620,
    "9618": syllabus_9618,
    "9702": syllabus_9702,
}


def main():
    parser = argparse.ArgumentParser(description="Generate Cambridge study planner Excel files")
    parser.add_argument("--syllabuses", nargs="*",
                        default=list(ALL_SYLLABUSES.keys()),
                        help="Space-separated list of syllabuses to generate (default: all)")
    args = parser.parse_args()

    for code in args.syllabuses:
        if code not in ALL_SYLLABUSES:
            print(f"  [skip] Unknown syllabus: {code}", file=sys.stderr)
            continue

        syl = ALL_SYLLABUSES[code]()
        subfolder = OUT_ROOT / syl["subfolder"]
        subfolder.mkdir(parents=True, exist_ok=True)

        fname = f"{code} {syl['subject']} Study Planner.xlsx"
        out_path = subfolder / fname

        wb = build_workbook(syl)
        wb.save(out_path)
        print(f"  [ok] {syl['level']} — {out_path.relative_to(ROOT)}")

    print(f"\nDone. Files written to: {OUT_ROOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
