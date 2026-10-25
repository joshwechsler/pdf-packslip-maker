"""Snap-to-align while dragging boxes in the layout editor."""

from packslip.snapping import snap_edge, snap_move, targets

HEADING = {"id": "h", "x": 432.0, "y": 40.0, "w": 324.0, "h": 14.0}
BOX = {"id": "b", "x": 100.0, "y": 300.0, "w": 200.0, "h": 50.0}


def test_targets_include_other_boxes_and_page_but_not_the_dragged_one():
    xs, ys = targets([HEADING, BOX], "b", 792, 612)
    assert {432.0, 756.0, 594.0} <= set(xs)                  # heading left, right, centre
    assert {36.0, 756.0, 396.0} <= set(xs)                   # page margins (0.5 in) and centre
    assert {40.0, 54.0, 47.0, 36.0, 576.0, 306.0} <= set(ys)
    assert 100.0 not in xs and 300.0 not in xs               # the box being dragged is not a target


def test_move_snaps_left_edge_under_the_heading():
    xs, ys = targets([HEADING, BOX], "b", 792, 612)
    x, y, gx, gy = snap_move(435.0, 120.0, 200.0, 50.0, xs, ys, tol=5)
    assert x == 432.0 and gx == 432.0                        # left edges line up, guide shown at 432
    assert y == 120.0 and gy is None                         # nothing close vertically: unchanged


def test_move_snaps_right_edge_and_centre_too():
    xs, ys = targets([HEADING], "b", 792, 612)
    x, _, gx, _ = snap_move(554.0, 200.0, 200.0, 50.0, xs, ys, tol=5)
    assert x + 200.0 == 756.0 and gx == 756.0               # right edges line up
    x, _, gx, _ = snap_move(497.0, 200.0, 200.0, 50.0, xs, ys, tol=5)
    assert x + 100.0 == 594.0 and gx == 594.0               # centres line up


def test_nothing_close_means_no_snap():
    xs, ys = targets([HEADING], "b", 792, 612)
    assert snap_move(470.0, 200.0, 50.0, 50.0, xs, ys, tol=5)[2] is None


def test_resize_edge_snaps():
    xs, _ = targets([HEADING], "b", 792, 612)
    assert snap_edge(753.0, xs, tol=5) == (756.0, 756.0)
    assert snap_edge(700.0, xs, tol=5) == (700.0, None)
