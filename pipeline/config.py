"""Central configuration: paths, source-site endpoints, paper scope."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CROPS_DIR = DATA_DIR / "crops"
DEBUG_DIR = DATA_DIR / "debug"
BATCHES_DIR = DATA_DIR / "batches"
DB_PATH = DATA_DIR / "index.db"
MANIFEST_PATH = DATA_DIR / "manifest.json"
TAXONOMY_DIR = ROOT / "taxonomy"
OUTPUT_DIR = DATA_DIR / "output"

# Branding for composed PDFs (PrepWithTee). Colours are sampled from the logo.
# Kept under website/static so it ships with every deploy (deploy/sync.sh sends
# website/ but not the repo root -- a root-level logo went missing on Oracle and
# the covers silently fell back to text).
LOGO_PATH = ROOT / "website" / "static" / "prepwithtee-logo.png"
# The owl inside the 1200x1200 logo, excluding the wordmark beneath it
# (measured from the artwork). Used for the cover watermark.
LOGO_OWL_CLIP = (414, 252, 786, 834)
BRAND_NAME = "PrepWithTee"
BRAND_TAGLINE = "Expert Cambridge Tutoring · Lahore"
BRAND_WEBSITE = "prepwithtee.com"
BRAND_WEBSITE_URL = "https://prepwithtee.com"
BRAND_WHATSAPP = "03204884375"
BRAND_WHATSAPP_URL = "https://wa.me/923204884375"
BRAND_PHONE = "+92 320 488 4375"
BRAND_CREAM = (0.984, 0.953, 0.851)   # #FBF3D9 - the logo's own background
BRAND_NAVY = (0.161, 0.208, 0.329)    # #293554
BRAND_GOLD = (0.957, 0.651, 0.196)    # #F4A632

API_BASE = "https://papers.fastpapers.uk"
BUCKET_API = API_BASE + "/api/bucket"
PDF_API = API_BASE + "/api/pdf"
REQUEST_DELAY_S = 2.0
USER_AGENT = "nexgen-topicals/0.1 (internal tutoring tool)"

# Verified bucket folder per syllabus (2026-07-15). Names are inconsistent on
# the server -- always look up here, never construct from the subject title.
SUBJECT_FOLDERS = {
    "5054": "Cambridge/O Level/Physics (5054) O Level",
    "0625": "Cambridge/IGCSE/Physics 0625 IGCSE",
    "4024": "Cambridge/O Level/Mathematics (Syllabus D) - 4024",
    "0580": "Cambridge/IGCSE/Mathematics 0580 IGCSE",
    "2210": "Cambridge/O Level/Computer Science - 2210",
    "0478": "Cambridge/IGCSE/Computer Science - 0478",
    "5070": "Cambridge/O Level/Chemistry (5070) O Level",
    "0620": "Cambridge/IGCSE/Chemistry 0620",
    "9709": "Cambridge/A level/Mathematics - 9709",
    "9702": "Cambridge/A level/Physics 9702",
    "9618": "Cambridge/A level/Computer Science - 9618",
    # Not on fastpapers.uk — downloaded via pipeline/fetch_alt.py from papacambridge
    "2058": None,   # O Level Islamiyat — papers placed in data/raw/2058/ manually
    "2059": None,   # O Level Pakistan Studies — papers placed in data/raw/2059/ manually
}

# Structured papers in scope per syllabus. Paper number = first digit of the
# two-digit code in the filename (qp_22 -> paper 2, variant 2).
# 9709: P1=Pure1, P3=Pure3, P4=Mechanics, P5=Statistics1
# 9702: P1=MCQ, P2=AS Structured, P4=A2 Structured, P5=Planning&Analysis
PAPER_MATRIX = {
    "5054": (1, 2),          # P1 multiple choice (added 2026-07), P2 theory
    "0625": (1, 2, 4),       # P1/P2 multiple choice (core/extended), P4 theory
    "4024": (1, 2),
    "0580": (2, 4),
    "2210": (1, 2),          # O Level CS; 0478 (IGCSE) is the same papers -> skip
    "0478": (1, 2),          # kept for reference; not processed (== 2210)
    "5070": (1, 2),          # Chemistry O Level: P1 MCQ, P2 theory
    "0620": (1, 2, 3, 4),    # Chemistry IGCSE: P1/P2 MCQ, P3/P4 structured theory
    "9709": (1, 3, 4, 5),
    "9702": (1, 2, 4, 5),
    "9618": (1, 2, 3, 4),    # A Level Computer Science
    "2058": (1, 2),          # O Level Islamiyat: P1 Quran/Hadith, P2 History
    "2059": (1, 2),          # O Level Pakistan Studies: P1 History/Culture, P2 Geography
}

# Multiple-choice papers. Their mark scheme is a Question/Answer/Marks table,
# not prose, so composing a per-question mark-scheme crop under each question
# would both look wrong and spoil the answer. compose/testgen instead collect
# the letters into an answer grid at the back and print a fill-in bubble sheet.
MCQ_PAPERS = {
    ("9702", 1),
    ("5054", 1),             # Physics O Level multiple choice
    ("0625", 1), ("0625", 2),  # Physics IGCSE core/extended multiple choice
    ("5070", 1),             # Chemistry O Level multiple choice
    ("0620", 1), ("0620", 2),  # Chemistry IGCSE core/extended multiple choice
}


def is_mcq(syllabus: str, paper: int | None) -> bool:
    return (syllabus, paper) in MCQ_PAPERS


YEAR_MIN = 2010
YEAR_MAX = 2026

GT_DIR = DATA_DIR / "grade_thresholds"   # downloaded gt PDFs
ER_DIR = DATA_DIR / "examiner_reports"   # downloaded er PDFs

SESSION_CODES = ("s", "w", "m")


def folder_to_session(folder_name: str) -> str | None:
    """Map a session folder name like 'May-Jun' or '2023 May-Jun' to s/w/m."""
    import re
    n = re.sub(r"^\d{4}\s+", "", folder_name.strip().lower())
    if n.startswith("may"):
        return "s"
    if n.startswith("oct"):
        return "w"
    if n.startswith(("feb", "mar")):
        return "m"
    return None


def session_display(session: str) -> str:
    """Session code -> the form used in Cambridge source references."""
    return {"s": "M/J", "w": "O/N", "m": "F/M"}[session]


def paper_key(syllabus: str, session: str, year: int, code: str) -> str:
    """Stable id used in file paths, e.g. ('5054','s',2025,'22') -> '5054_s25_22'."""
    return f"{syllabus}_{session}{year % 100:02d}_{code}"


def source_ref(syllabus: str, code: str, session: str, year: int,
               number: int, sub_part: str = "") -> str:
    """Human source reference, e.g. '5054/22/M/J/25 Q6' or '2059/01/M/J/25 Q3(b)'."""
    suffix = f"({sub_part})" if sub_part else ""
    return f"{syllabus}/{code}/{session_display(session)}/{year % 100:02d} Q{number}{suffix}"
