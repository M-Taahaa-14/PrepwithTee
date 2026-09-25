"""static/math-expr.js (the graph plotter's parser), run under Node.

Every expression is evaluated at x = 2 (y = 3 where used) and compared with
the value a student would expect, including each bug the old regex-and-eval
plotter had: -x^2, sin x, x(x+1), 2^-1, |x|, sin^2(x), log_2(x)."""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "website" / "static" / "math-expr.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")

x = 2.0
CASES = [
    # the old plotter's bugs
    ("-x^2", -4), ("sin x", math.sin(2)), ("x(x+1)", 6), ("2^-1", 0.5), ("|x|", 2), ("|-x|", 2),
    ("sin^2(x)", math.sin(2) ** 2), ("sin^2 x", math.sin(2) ** 2), ("log_2(x)", 1), ("log_2 8", 3),
    ("log_{10}(100)", 2), ("√x", math.sqrt(2)), ("π", math.pi), ("e", math.e),
    # implicit multiplication
    ("2x", 4), ("3(x+1)", 9), ("(x+1)(x-1)", 3), ("2pi", 2 * math.pi), ("2πx", 4 * math.pi),
    ("xsin(x)", 2 * math.sin(2)), ("2sin x", 2 * math.sin(2)), ("x2", None), ("3x^2", 12),
    ("2(x)(3)", 12), ("x|x-3|", 2), ("2|x|+1", 5), ("|x||x|", 4),
    # functions without brackets
    ("sin 2x", math.sin(4)), ("sin x cos x", math.sin(2) * math.cos(2)), ("sin x/2", math.sin(2) / 2),
    ("sin x^2", math.sin(4)), ("sin -x", math.sin(-2)), ("ln x", math.log(2)), ("cos x + 1", math.cos(2) + 1),
    ("sin^-1(0.5)", math.asin(0.5)), ("tan^-1 1", math.atan(1)),
    # precedence
    ("1+2*3", 7), ("2^3^2", 512), ("-2^2", -4), ("(-2)^2", 4), ("2*-x", -4), ("-x+3", 1),
    ("x^2y", None), ("6/2(1+2)", 9), ("2^x+1", 5), ("-3x", -6), ("x^-1", 0.5), ("x²+x³", 12),
    ("10−x", 8), ("6÷x", 3), ("3×x", 6), ("x**3", 8), ("4!", 24), ("x!", 2),
    # functions + constants
    ("sqrt(x^2+5)", 3), ("abs(1-x)", 1), ("e^x", math.exp(2)), ("exp(x)", math.exp(2)), ("log(1000)", 3),
    ("min(x, 5, -1)", -1), ("max(x,3)", 3), ("floor(2.7)", 2), ("sec(x)", 1 / math.cos(2)),
    ("cosec(x)", 1 / math.sin(2)), ("cot x", 1 / math.tan(2)), ("(-8)^(1/3)", -2), ("∛(-27)", -3),
    ("sinh(0)", 0), ("[x+1]*2", 6), ("{x}", 2),
]

ERRORS = [
    ("", "Type an expression"), ("sin(", "Missing ')' to close 'sin('"), ("(x+1", "Missing ')'"),
    ("x+", "ends too early"), ("x)", "no '('"), ("q", "use x"), ("foo(x)", "don't know 'foo'"),
    ("2^", "needs a power"), ("sin", "needs something after it"), ("|x", "Missing '|'"),
    ("()", "Empty brackets"), ("sin()", "needs something inside"), ("x,y", "min(…) or max(…)"),
    ("3 $ 4", "can't read '$'"),
]

RELATIONS = [
    ("x^2-4", "explicit", 0), ("y=2x+1", "explicit", 5), ("f(x) = x^2", "explicit", 4), ("2x+1=y", "explicit", 5),
    ("x=3", "vertical", 3), ("x = 2pi", "vertical", 2 * math.pi), ("x^2+y^2=25", "implicit", 4 + 9 - 25),
    ("x=y^2", "implicit", 2 - 9), ("y^2 = x", "implicit", 9 - 2),
]
REL_ERRORS = [("y<x", "coming soon"), ("x=y=2", "Only one '='"), ("x+y", "add '= …'"), ("=x", "missing before"),
              ("3=4", "Put x or y")]

RUNNER = r"""
const M = require(process.argv[2]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {values: [], errors: [], rel: [], relErr: []};
for (const [src] of input.cases) {
  try { out.values.push(M.evaluate(src, {x: 2, y: 3})); } catch (e) { out.values.push('ERR ' + e.message); }
}
for (const [src] of input.errors) {
  try { M.compile(src); out.errors.push('no error'); } catch (e) { out.errors.push(e.name + ': ' + e.message); }
}
for (const [src] of input.rel) {
  try {
    const r = M.relation(src);
    out.rel.push([r.kind, r.kind === 'explicit' ? r.f(2) : r.kind === 'vertical' ? r.x : r.F(2, 3)]);
  } catch (e) { out.rel.push(['ERR', e.message]); }
}
for (const [src] of input.relErr) {
  try { M.relation(src); out.relErr.push('no error'); } catch (e) { out.relErr.push(e.message); }
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    runner = tmp_path_factory.mktemp("js") / "run.js"
    runner.write_text(RUNNER, encoding="utf-8")
    payload = json.dumps({"cases": CASES, "errors": ERRORS, "rel": RELATIONS, "relErr": REL_ERRORS})
    r = subprocess.run(["node", str(runner), str(LIB)], input=payload, capture_output=True,
                       text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.parametrize("i", range(len(CASES)), ids=[c[0] or "empty" for c in CASES])
def test_value_at_x_equals_2(results, i):
    src, want = CASES[i]
    got = results["values"][i]
    if want is None:                       # x2 = x·2 and x^2y = (x^2)·y, both fine
        want = {"x2": 4, "x^2y": 12}[src]
    assert isinstance(got, (int, float)), f"{src!r} -> {got}"
    assert got == pytest.approx(want, rel=1e-9, abs=1e-12), src


@pytest.mark.parametrize("i", range(len(ERRORS)), ids=[e[0] or "empty" for e in ERRORS])
def test_friendly_errors(results, i):
    src, words = ERRORS[i]
    got = results["errors"][i]
    assert got.startswith("MathError: ") and words in got, f"{src!r} -> {got}"


@pytest.mark.parametrize("i", range(len(RELATIONS)), ids=[r[0] for r in RELATIONS])
def test_relations(results, i):
    src, kind, value = RELATIONS[i]
    got_kind, got = results["rel"][i]
    assert got_kind == kind, f"{src!r} -> {got_kind} {got}"
    assert got == pytest.approx(value), src


@pytest.mark.parametrize("i", range(len(REL_ERRORS)), ids=[r[0] for r in REL_ERRORS])
def test_relation_errors(results, i):
    src, words = REL_ERRORS[i]
    assert words in results["relErr"][i], f"{src!r} -> {results['relErr'][i]}"


def test_no_eval_or_function_constructor():
    code = LIB.read_text(encoding="utf-8")
    assert "new Function" not in code and "eval(" not in code
