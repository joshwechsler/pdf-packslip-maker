"""Delivery report for the delivery software: deterministic transformation of the orders file."""

import csv

from packslip.delivery_report import (COLUMNS, DEFAULT_LOCATIONS, PickupLocation, build_report, fix_zip,
                                      match_location, split_first_last, write_report)
from packslip.routes import guess_route_columns
from packslip.spreadsheet import load

HEAD = ("Order,Customer,Total Items,Fulfillment Type,Fulfillment Date,Location,Product,Quantity,City,Zip Code,"
        "Full Address,Customer Email,Customer Phone,Driver Instructions\n")
ROWS = [
    # home delivery, two item rows, 4-digit ZIP
    '1001,Sarah Marie Johnson,3,ScheduledDelivery,11/01/2026,Main (West Haven),Oats,2,Branford,6405,'
    '"23 Wilford Ave, Branford, CT 6405",s@x.com,(203) 555-0101,Side door\n',
    '1001,Sarah Marie Johnson,3,ScheduledDelivery,11/01/2026,Main (West Haven),Chili,1,Branford,6405,'
    '"23 Wilford Ave, Branford, CT 6405",s@x.com,(203) 555-0101,Side door\n',
    # pickups at the kitchen: left off
    '1002,Ann Lee,2,InStorePickup,11/01/2026,Main (West Haven),Pie,2,,,,a@x.com,(203) 555-0102,\n',
    # Chapel Haven pickups: one drop for all
    '1003,Bo Ray,4,InStorePickup,11/01/2026,Chapel Haven- RESIDENTS ONLY,Pie,4,,,,b@x.com,(203) 555-0103,\n',
    '1004,Cy Fox,6,InStorePickup,11/01/2026,Chapel Haven- RESIDENTS ONLY,Pie,6,,,,c@x.com,(203) 555-0104,\n',
    # another pickup location, with the store's "(Town)" suffix
    '1005,Dee Kim,5,InStorePickup,11/01/2026,Crossfit Milford (Milford),Pie,5,,,,d@x.com,(203) 555-0105,\n',
    # unknown pickup location
    '1006,Eve Day,1,InStorePickup,11/01/2026,Nowhere Gym,Pie,1,,,,e@x.com,(203) 555-0106,\n',
    # home delivery missing email
    '1007,Flo Rida,2,ScheduledDelivery,11/01/2026,,Pie,2,Orange,06477,"5 Elm St, Orange, CT 06477",,(203) 555-0107,\n',
]


def _report(tmp_path):
    p = tmp_path / "orders.csv"
    p.write_text(HEAD + "".join(ROWS))
    return build_report(load(p), DEFAULT_LOCATIONS)


def test_helpers():
    assert split_first_last("Sarah Marie Johnson") == ("Sarah", "Marie Johnson")
    assert split_first_last("Cher") == ("Cher", "")
    assert [fix_zip(z) for z in ("6405", "06516", "06405-1234", " ")] == ["06405", "06516", "064051234", ""]
    locs = DEFAULT_LOCATIONS
    assert match_location("chapel haven-  residents only", locs).name == "Chapel Haven- RESIDENTS ONLY"  # case/spaces
    assert match_location("Crossfit Milford (Milford)", locs).name == "Crossfit Milford"                 # "(town)" dropped
    assert match_location("Main (West Haven)", locs).name == "Main"
    assert match_location("BackEast CrossFit", locs).name == "Back East Crossfit"                        # other spelling
    assert match_location("Market 10-24- Private members only", locs) is None                             # skipped for now
    assert match_location("Crossfit", locs) is None                                                       # no weak matches


def test_report_rows(tmp_path):
    rep = _report(tmp_path)
    assert not rep.errors
    rows = {r["Order"] or r["Customer"]: r for r in rep.rows}
    assert list(rows) == ["1001", "Chapel Haven", "1005", "1006", "1007"]          # file order; 1002 left off
    home = rows["1001"]
    assert (home["Customer"], home["Customer First Name"], home["Customer Last Name"]) == (
        "Sarah Marie Johnson", "Sarah", "Marie Johnson")
    assert home["Full Address"] == "23 Wilford Ave, Branford, CT 06405" and home["City"] == "Branford"
    assert (home["Shipper"], home["Goods"], home["Total Items"], home["Route#"]) == ("Honeyplate", "Meals", "3", "")
    assert (home["Customer Email"], home["Customer Phone"], home["Driver Instructions"]) == (
        "s@x.com", "(203) 555-0101", "Side door")
    chapel = rows["Chapel Haven"]                                                    # one drop, 4 + 6 items
    assert chapel["Total Items"] == "10" and chapel["Customer Email"] == "" and chapel["Customer Phone"] == ""
    assert chapel["Full Address"] == "(Chapel Haven- RESIDENTS ONLY) 1040 Whalley Ave, New Haven, CT 06516"
    assert chapel["City"] == "New Haven" and chapel["Order"] == ""
    milford = rows["1005"]
    assert milford["Full Address"] == "(Crossfit Milford) 333 Quarry Rd, Milford, CT 06460"
    assert milford["City"] == "Milford" and milford["Customer Email"] == "d@x.com"
    assert rows["1006"]["Full Address"] == ""                                       # unknown: not guessed
    a = rep.audit
    assert (a["orders"], a["rows"], a["home"], a["pickups_listed"], a["left_off"], a["combined"]) == (7, 5, 2, 2, 1, 2)
    text = " ".join(rep.warnings)
    assert "1006" in text and "Nowhere Gym" in text and "1007" in text and "email" in text.lower()


def test_csv_written_exactly(tmp_path):
    rep = _report(tmp_path)
    out = tmp_path / "report.csv"
    write_report(out, rep.rows)
    with open(out, encoding="utf-8", newline="") as f:
        lines = list(csv.reader(f))
    assert lines[0] == COLUMNS and len(lines[0]) == 15 and len(lines) == 1 + len(rep.rows)
    assert lines[1][COLUMNS.index("Full Address")].endswith("CT 06405")
    assert guess_route_columns(lines[0]).driver == "Route#"          # the filled-in file works as the driver list


def test_missing_columns_block(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Order,Customer\n1,Ann\n")
    rep = build_report(load(p), DEFAULT_LOCATIONS)
    assert rep.errors and "Full Address" in rep.errors[0]


def test_locations_round_trip():
    from packslip.delivery_report import load_locations, save_locations
    locs = load_locations()
    assert any(loc.name == "Carozza Fitness" and "Crescent" in loc.address for loc in locs)
    locs.append(PickupLocation(name="New Gym", address="1 Main St, Hamden, CT 06514"))
    save_locations(locs)
    again = load_locations()
    new = next(loc for loc in again if loc.name == "New Gym")
    assert new.full_address() == "(New Gym) 1 Main St, Hamden, CT 06514" and new.mode == "each"
