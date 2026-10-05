"""Combining a separate route file with the orders."""

from packslip.drivers import make_plan
from packslip.routes import RouteColumns, guess_route_columns, join_routes, looks_like_route_file, norm_order
from packslip.spreadsheet import load


def _vals():
    return [
        {"order_number": "5704919", "customer_name": "Ann Lee", "address": "9 Oak St, Wallingford, CT 06492"},
        {"order_number": "5704920", "customer_name": "Bob Roe", "address": "5 Elm St, Meriden, CT 06450"},
        {"order_number": "5704921", "customer_name": "Bob Roe", "address": "5 Elm St, Meriden, CT 06450"},
        {"order_number": "", "customer_name": "Cat Diaz", "address": "1 Main St, West Haven, CT 06516"},
        {"order_number": "5704923", "customer_name": "Dan Fox", "address": "2 Pine Rd, Orange, CT 06477"},
        {"order_number": "5704924", "customer_name": "Eve Kim", "address": "7 Ash Ave, Milford, CT 06460"},
    ]


def _route_file(tmp_path, text):
    p = tmp_path / "routes.csv"
    p.write_text(text)
    return load(p)


def test_order_number_formats():
    assert norm_order("#05704919") == norm_order(" 5704919 ") == norm_order("5704919.0") == "5704919"


def test_guess_and_detect(tmp_path):
    s = _route_file(tmp_path, "Route,Stop,Order #,Customer Name\nR1,1,#5704919,Ann Lee\n")
    assert guess_route_columns(s.headers) == RouteColumns(order="Order #", customer="Customer Name",
                                                          driver="Route", stop="Stop")
    assert looks_like_route_file(s)
    orders = _route_file(tmp_path, "Order,Customer,Product,Quantity,Driver Instructions\n1,A,Oats,1,\n")
    assert not looks_like_route_file(orders)


def test_join_by_number_then_name_and_report_missing(tmp_path):
    s = _route_file(tmp_path, "Driver,Stop #,Order #,Customer Name\n"
                              "Mike,2,#5704919,Ann Lee\n"
                              "Mike,1,5704920,Bob Roe\n"      # Bob's other order (…921) is NOT in the file
                              "Sara,1,,cat  diaz\n"            # no order number: matched by name
                              "Sara,2,9999999,Dan Fox\n")      # wrong number: must not match Dan by name
    res = join_routes(s, guess_route_columns(s.headers), _vals())
    assert res.assignment == {0: "Mike", 1: "Mike", 3: "Sara"}
    assert res.stops == {0: 2, 1: 1, 3: 1}
    assert res.unmatched == [2, 4, 5] and res.by_name == 1


def test_route_stop_numbers_decide_the_order():
    vals = _vals()
    plan = make_plan(vals, {0: "Mike", 1: "Mike", 4: "Mike"}, ["Mike"], stops={0: 2, 1: 1})
    assert plan.routes[0] == ("Mike", [1, 0, 4])   # stops 1, 2, then the one without a stop number


def test_route_file_stop_numbers_are_printed_as_given():
    plan = make_plan(_vals(), {0: "Mike", 1: "Mike"}, ["Mike"], stops={0: 5, 1: 2})
    assert plan.stop_of() == {1: ("Mike", 2), 0: ("Mike", 5)}
