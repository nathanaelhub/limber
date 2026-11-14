"""Feature 019 slice 1 (T004, FR-011, FR-012): server-drawn charts with a description and a table."""

from src.clinic import charts


def test_a_line_chart_describes_itself_and_lists_its_numbers():
    c = charts.line_chart("Range of motion, degrees", [("14 Oct", 70), ("21 Oct", 78), ("28 Oct", 85)],
                          unit="°", goal=110)
    assert c.svg.startswith('<svg viewBox="0 0 480 170" role="img" aria-label="Line chart of Range of motion')
    assert "14 Oct: 70°" in c.description and "Goal 110°" in c.description
    assert c.rows == [("14 Oct", "70°"), ("21 Oct", "78°"), ("28 Oct", "85°"), ("Goal", "110°")]
    assert c.svg.count('class="pt"') == 3 and 'class="goal"' in c.svg


def test_a_missing_value_is_a_gap_not_a_zero():
    c = charts.line_chart("Pain", [("Mon", 3), ("Tue", None), ("Wed", 4), ("Thu", 5)])
    assert c.svg.count('class="s1"') == 1                       # Mon stands alone; Wed-Thu is one line
    assert c.svg.count('class="pt"') == 3
    assert ("Tue", "none") in c.rows
    bars = charts.bar_chart("Pain", [("Mon", 3), ("Tue", None)])
    assert bars.svg.count('class="bar') == 1 and ">none</text>" in bars.svg


def test_bars_start_at_zero_and_can_mark_low_values():
    c = charts.bar_chart("Reps", [("Mon", 10), ("Tue", 4)], low_below=5)
    assert 'class="bar low"' in c.svg and c.svg.count('class="bar"') == 1
    assert '>0</text>' in c.svg


def test_no_values_yet():
    c = charts.line_chart("Pain", [])
    assert "No values yet" in c.description


def test_labels_are_escaped_and_the_figure_has_a_table():
    html = charts.render(charts.bar_chart("A <b>", [("<x>", 1)]))
    assert "A &lt;b&gt;" in html and "A <b>" not in html
    assert "&lt;x&gt;" in html and "<x>" not in html
    assert '<details class="astable"><summary>Show as table</summary>' in html


def test_axis_labels_are_round_numbers():
    import re
    c = charts.line_chart("Form", [("a", 85.9), ("b", 87.2), ("c", 84.3)])
    labels = re.findall(r'text-anchor="end">([0-9.]+)</text>', c.svg)
    assert labels and all(float(x) == int(float(x)) for x in labels), labels


def test_many_points_keep_their_labels_apart():
    c = charts.bar_chart("Form", [(str(i), 70) for i in range(1, 31)])
    assert c.svg.count('y="162"') <= 13 and ">30</text>" in c.svg
    assert ">70</text>" not in c.svg and len(c.rows) == 30                   # no crowded numbers; the table has them


def test_the_last_label_never_sits_on_top_of_the_one_before():
    """16 points thin to every 2nd label; the last (index 15) used to land beside index 14 ("11 Nov12 Nov")."""
    c = charts.line_chart("ROM", [(f"d{i}", 60 + i) for i in range(16)])
    shown = [int(x) for x in __import__("re").findall(r'y="162" text-anchor="middle">d(\d+)<', c.svg)]
    assert shown[-1] == 15 and shown[0] == 0
    assert all(b - a >= 2 for a, b in zip(shown, shown[1:]))
