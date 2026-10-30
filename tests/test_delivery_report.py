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


FOLD_ROWS = [
    '2001,Ann Lee,4,InStorePickup,11/01/2026,Chapel Haven- RESIDENTS ONLY,Pie,4,,,,a@x.com,(203) 555-0101,\n',
    '2002,Bo Ray,5,ScheduledDelivery,11/01/2026,Main (West Haven),Pie,5,New Haven,06515,'
    '"1040 Whalley Ave, New Haven, CT 06515",b@x.com,(203) 555-0102,\n',
    '2003,Cy Fox,6,ScheduledDelivery,11/01/2026,,Pie,6,New Haven,06515,'
    '"Chapel Haven 1040 Whalley Avenue, Apt 304, New Haven, CT 06515",c@x.com,(203) 555-0103,\n',
    '2004,Dee Kim,2,ScheduledDelivery,11/01/2026,,Pie,2,Hamden,06514,'
    '"1040 Whalley Ave, Hamden, CT 06514",d@x.com,(203) 555-0104,\n',              # same street, other town
    '2005,Eve Day,3,ScheduledDelivery,11/01/2026,,Pie,3,New Haven,06511,'
    '"10400 Whalley Ave, New Haven, CT 06511",e@x.com,(203) 555-0105,\n',          # different number
]


def _fold_report(tmp_path, rows=FOLD_ROWS):
    p = tmp_path / "fold.csv"
    p.write_text(HEAD + "".join(rows))
    return build_report(load(p), DEFAULT_LOCATIONS)


def test_home_deliveries_to_a_drop_off_address_are_found(tmp_path):
    rep = _fold_report(tmp_path)
    assert rep.fold_candidates == {"Chapel Haven- RESIDENTS ONLY": ["2002", "2003"]}
    assert [r["Order"] or r["Customer"] for r in rep.rows] == ["Chapel Haven", "2002", "2003", "2004", "2005"]


def test_folding_into_the_drop_off(tmp_path):
    from packslip.delivery_report import fold_into_drops
    rep = _fold_report(tmp_path)
    fold_into_drops(rep, ["2002", "2003"])
    assert [r["Order"] or r["Customer"] for r in rep.rows] == ["Chapel Haven", "2004", "2005"]
    chapel = rep.rows[0]
    assert chapel["Total Items"] == str(4 + 5 + 6)
    assert (rep.audit["rows"], rep.audit["home"], rep.audit["combined"]) == (3, 2, 3)
    rep2 = _fold_report(tmp_path)
    fold_into_drops(rep2, ["2002"])                                   # one unticked: stays its own stop
    assert [r["Order"] or r["Customer"] for r in rep2.rows] == ["Chapel Haven", "2003", "2004", "2005"]


def test_folding_creates_the_drop_off_when_no_pickups_there(tmp_path):
    from packslip.delivery_report import fold_into_drops
    rep = _fold_report(tmp_path, FOLD_ROWS[1:3])                      # only home deliveries to Chapel Haven
    assert rep.fold_candidates == {"Chapel Haven- RESIDENTS ONLY": ["2002", "2003"]}
    fold_into_drops(rep, ["2002", "2003"])
    assert len(rep.rows) == 1 and rep.rows[0]["Customer"] == "Chapel Haven" and rep.rows[0]["Total Items"] == "11"
    assert rep.rows[0]["Full Address"].startswith("(Chapel Haven- RESIDENTS ONLY) 1040 Whalley Ave")
