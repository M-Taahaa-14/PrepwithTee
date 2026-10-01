"""static/calc-engine.js (the fx-991ES-style calculator), run under Node.

Answers are checked the way the calculator shows them: exact forms where a
Casio gives one (5/6, √2/2, 2−√3, π/4), decimals otherwise, the right error for
maths that has no answer, and the modes (SOLVE, EQN, STAT, BASE-N, ∫ d/dx Σ)."""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "website" / "static" / "calc-engine.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")


def run(js: str):
    """Run a snippet with E = the engine; it must print one JSON value."""
    src = f"const E = require({json.dumps(str(LIB))});\n{js}"
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


EXACT = [
    ("1/2+1/3", "5/6"), ("0.1+0.2", "3/10"), ("7÷3", "7/3"), ("1.5", "3/2"), ("2^10", "1024"),
    ("sin(30)", "1/2"), ("cos(45)", "√2/2"), ("tan(60)", "√3"), ("tan(15)", "2−√3"), ("tan(75)", "2+√3"),
    ("√(8)", "2√2"), ("√(50)", "5√2"), ("√(12)/3", "2√3/3"), ("1/√(2)", "√2/2"), ("(1+√(5))/2", "(1+√5)/2"),
    ("2√(3)+√(3)", "3√3"), ("√(2)×√(2)", "2"), ("π/4", "π/4"), ("2π", "2π"),
    ("−2²", "−4"), ("(−2)²", "4"), ("1÷2π", None), ("5nCr2", "10"), ("5nPr2", "20"), ("5!", "120"),
    ("log(1000)", "3"), ("GCD(12,18)", "6"), ("LCM(4,6)", "12"), ("Abs(−3)", "3"), ("2+3(4", "14"),
    ("Σ(X²,1,10)", "385"), ("3²+4²", "25"), ("10^(−2)", "1/100"), ("2^−1", "1/2"),
]


def test_exact_forms():
    got = run("console.log(JSON.stringify(" + json.dumps([e for e, _ in EXACT]) +
              ".map(s => E.calc(s).text)))")
    for (expr, want), have in zip(EXACT, got):
        assert have == want, f"{expr}: {have!r} != {want!r}"


def test_radians_give_pi_forms():
    got = run("console.log(JSON.stringify(['sin⁻¹(1)','cos⁻¹(−0.5)','tan⁻¹(1)','sin(π÷6)']"
              ".map(s => E.calc(s, {angle:'rad'}).text)))")
    assert got == ["π/2", "2π/3", "π/4", "1/2"]


DECIMAL = [
    ("1÷2π", 1 / (2 * math.pi)), ("sin(1)", math.sin(math.radians(1))), ("ln(2)", math.log(2)),
    ("∫(X²,0,3)", 9), ("d/dx(X³,2)", 12), ("(−8)^(1/3)", -2), ("root(3,27)", 3), ("e^2", math.e ** 2),
    ("3×10^8×2", 6e8), ("sinh(1)", math.sinh(1)), ("log(2,8)", 3), ("25%", 0.25),
]


def test_values():
    got = run("console.log(JSON.stringify(" + json.dumps([e for e, _ in DECIMAL]) + ".map(s => E.calc(s).v)))")
    for (expr, want), have in zip(DECIMAL, got):
        assert have == pytest.approx(want, rel=1e-9, abs=1e-12), expr


ERRORS = [("1/0", "Math ERROR"), ("√(−4)", "Math ERROR"), ("tan(90)", "Math ERROR"), ("ln(0)", "Math ERROR"),
          ("sin⁻¹(2)", "Math ERROR"), ("2+", "Syntax ERROR"), ("1..2", "Syntax ERROR"), ("(1+2))", "Syntax ERROR"),
          ("171!", "Math ERROR"), ("3nCr5", "Math ERROR")]


def test_errors_have_the_calculator_names_and_a_hint():
    got = run("console.log(JSON.stringify(" + json.dumps([e for e, _ in ERRORS]) +
              ".map(s => { try { E.calc(s); return null } catch (e) { return [e.kind, e.hint] } })))")
    for (expr, kind), have in zip(ERRORS, got):
        assert have and have[0] == kind and have[1], f"{expr}: {have}"


def test_solve_equations_and_expressions():
    got = run("""const s = (t, g) => E.solve(E.parse(E.fromText(t)), g, {});
      console.log(JSON.stringify([s('X²−2', 1).x, s('2X+3=11', 0).x, s('X³−X−1', 1).x, s('sin(X)=0.5', 10).x]))""")
    assert got[0] == pytest.approx(math.sqrt(2)) and got[1] == 4
    assert got[2] == pytest.approx(1.324717957244746) and got[3] == pytest.approx(30)


def test_equation_modes():
    got = run("""console.log(JSON.stringify({
      lin2: E.linear([[2,1,5],[1,-1,1]]), lin3: E.linear([[1,1,1,6],[0,2,5,-4],[2,5,-1,27]]),
      q: E.quadratic(1,-3,2), qc: E.quadratic(1,2,5).roots, c: E.cubic(1,-6,11,-6).roots,
      c2: E.cubic(1,0,0,1).roots }))""")
    assert got["lin2"] == [2, 1] and got["lin3"] == pytest.approx([5, 3, -2])
    assert [r["re"] for r in got["q"]["roots"]] == [2, 1] and got["q"]["vertex"] == {"x": 1.5, "y": -0.25}
    assert got["qc"] == [{"re": -1, "im": 2}, {"re": -1, "im": -2}]
    assert [r["re"] for r in got["c"]] == [3, 2, 1]
    assert got["c2"][0] == {"re": -1, "im": 0} and got["c2"][1]["im"] == pytest.approx(math.sqrt(3) / 2)


def test_parallel_lines_have_no_unique_solution():
    got = run("try { E.linear([[1,1,2],[2,2,5]]); console.log('null') } catch (e) { console.log(JSON.stringify(e.kind)) }")
    assert got == "No unique solution"


def test_statistics():
    got = run("""console.log(JSON.stringify({
      a: E.stats1([{x:1},{x:2},{x:3},{x:4},{x:10}]), f: E.stats1([{x:2,f:3},{x:5,f:1}]),
      r: E.stats2([{x:1,y:2},{x:2,y:4},{x:3,y:6}]) }))""")
    a = got["a"]
    assert (a["n"], a["mean"], a["median"], a["q1"], a["q3"], a["min"], a["max"]) == (5, 4, 3, 1.5, 7, 1, 10)
    assert a["sigma"] == pytest.approx(math.sqrt(10)) and a["s"] == pytest.approx(math.sqrt(12.5))
    assert got["f"]["n"] == 4 and got["f"]["mean"] == pytest.approx(2.75)
    r = got["r"]
    assert r["a"] == pytest.approx(0, abs=1e-12) and r["b"] == pytest.approx(2) and r["r"] == pytest.approx(1)


def test_base_n():
    got = run("""console.log(JSON.stringify([E.evalBase('1010+11','BIN'), E.toBase(E.evalBase('1010+11','BIN'),'BIN'),
      E.toBase(-1,'HEX'), E.evalBase('hFF and d15','DEC'), E.evalBase('FF+1','HEX'), E.evalBase('7÷2','DEC'),
      E.evalBase('Not(0)','DEC'), E.toBase(255,'OCT')]))""")
    assert got == [13, "1101", "FFFFFFFF", 15, 256, 3, -1, "377"]


def test_display_formats():
    got = run("""console.log(JSON.stringify([E.formatDecimal(123456789012,{}), E.formatDecimal(0.001234,{}),
      E.formatDecimal(2/3,{}), E.formatDecimal(3.14159,{fmt:'fix',digits:2}), E.formatDecimal(1234,{fmt:'sci',digits:3}),
      E.formatDecimal(0.001234,{fmt:'norm',digits:2}), E.formatEng(12345), E.formatEng(12345,1), E.dms(12.5125)]))""")
    assert got[0]["mant"] == "1.23456789" and got[0]["exp"] == 11
    assert got[1]["exp"] == -3 and got[2]["mant"] == "0.6666666667" and got[3]["mant"] == "3.14"
    assert got[4] == {"mant": "1.23", "exp": 3, "plain": "1.23e+3"} and got[5]["mant"] == "0.001234"
    assert (got[6]["mant"], got[6]["exp"]) == ("12.345", 3) and (got[7]["mant"], got[7]["exp"]) == ("0.012345", 6)
    assert got[8] == "12°30′45″"


def test_editor_templates_and_cursor():
    """2 then ■/□ puts 2 on top; ◀ ▶ walk in and out of boxes; DEL on an empty
    box removes it; the tree evaluates and writes back as text."""
    got = run("""const ed = new E.Editor();
      ed.insert('2'); ed.insertTemplate('frac', null, true); ed.insert('3'); ed.right(); ed.insert('+');
      ed.insertTemplate('sqrt'); ed.insert('8'); ed.right();
      const a = E.toText(ed.root), v = E.calc(ed.root).text;
      ed.left(); ed.left(); const inside = ed.cur.path.length;
      const e2 = new E.Editor(); e2.insertTemplate('frac'); e2.del();
      const e3 = new E.Editor(); e3.insert('5'); e3.insertTemplate('pow'); e3.insert('2'); e3.right(); e3.insert('+'); e3.insert('1');
      console.log(JSON.stringify([a, v, inside, e2.root.length, E.calc(e3.root).text, E.toText(e3.root)]))""")
    assert got[0] == "(2/3)+√(8)" and got[1] == "(2+6√2)/3"
    assert got[2] >= 1 and got[3] == 0 and got[4] == "26" and got[5] == "5^2+1"


def test_history_text_round_trips():
    """What goes into the history can be read back for ↺ edit."""
    got = run("""const src = ['(1/2)+(1/3)', '√(8)', 'sin(30)', 'log(2,8)', 'Σ(X²,1,10)', '5nCr2', '2×10^3', 'd/dx(X³,2)'];
      console.log(JSON.stringify(src.map(s => E.calc(E.toText(E.fromText(s))).v)))""")
    assert got == pytest.approx([5 / 6, math.sqrt(8), 0.5, 3, 385, 10, 2000, 12])
