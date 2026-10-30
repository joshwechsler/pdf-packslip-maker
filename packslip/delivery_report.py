"""Delivery report: the orders file turned into the delivery software's 15-column upload CSV.

Deterministic, following the Operator's written spec (no guessing):
- one row per order (the orders file has one row per item, grouped by Order);
- home deliveries keep the customer's address (ZIP fixed: 6405 -> 06405);
- pickup orders go to their pickup location's address, looked up in the pickup-location list
  (exact name or another spelling, case and spaces ignored; then once more without a trailing
  "(Town)"). Each location says how its orders go on the list:
      each      every order is its own stop at the location's address
      one_drop  all of its orders are one stop, named after the location (no phone or email)
      off       not on the delivery list (e.g. the kitchen)
- Route# is left blank; the delivery software fills it in, and the returned file works as the driver list.
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import storage
from .spreadsheet import Sheet

COLUMNS = ["Route#", "Order", "Customer", "Customer First Name", "Customer Last Name", "Fulfillment Date",
           "Location", "City", "Full Address", "Customer Email", "Customer Phone", "Driver Instructions",
           "Shipper", "Goods", "Total Items"]
SHIPPER, GOODS = "Honeyplate", "Meals"
REQUIRED = ["Order", "Customer", "Total Items", "Fulfillment Type", "Fulfillment Date", "Location", "City",
            "Full Address", "Customer Email", "Customer Phone", "Driver Instructions"]
MODES = {"each": "Each order is a stop", "one_drop": "One drop-off for all its orders", "off": "Not on the list"}


@dataclass
class PickupLocation:
    name: str
    address: str
    address_format: str = ""        # e.g. "(Shelton Athletics) 750 Bridgeport Ave, ..."; built when blank
    aliases: list[str] = field(default_factory=list)   # other spellings
    mode: str = "each"
    drop_name: str = ""             # one_drop: the name its stop goes under (default: the location's name)

    def full_address(self) -> str:
        text = self.address_format or f"({self.name}) {self.address}"
        return " ".join(text.split())

    def city(self) -> str:
        return city_from_address(self.address)


# The Operator's pickup-location sheet (fixed: Chapel Haven's "CT", Carozza's "Crescent"; Market 10-24 skipped).
DEFAULT_LOCATIONS = [
    PickupLocation("Main", "867 Jones Hill Road, West Haven, CT 06516", mode="off"),
    PickupLocation("Shelton Athletics", "750 Bridgeport Ave, Shelton, CT 06484"),
    PickupLocation("F45 Shelton", "391 Bridgeport Ave., Shelton, CT 06484"),
    PickupLocation("Savin Rock Athletics", "705 Campbell Avenue, West Haven, CT 06516"),
    PickupLocation("The LAB", "522 State St, New Haven, CT 06511"),
    PickupLocation("Back East Crossfit", "146 Dividend Rd, Rocky Hill, CT 06067", aliases=["BackEast CrossFit"]),
    PickupLocation("Branford CrossFit", "131 Commercial Pkwy Building 3, Branford, CT 06405"),
    PickupLocation("Resilient Training Lab", "87 Washington Ave, North Haven, CT 06473"),
    PickupLocation("Chapel Haven- RESIDENTS ONLY", "1040 Whalley Ave, New Haven, CT 06516", mode="one_drop",
                   drop_name="Chapel Haven"),
    PickupLocation("Market 24- Private members only", "211 Spring st, Naugatuck, CT 06770"),
    PickupLocation("Middletown CrossFit", "180 Johnson St., Middletown, CT 06457"),
    PickupLocation("Carozza Fitness", "55 Crescent St., Stamford, CT 06906"),
    PickupLocation("Crossfit Milford", "333 Quarry Rd, Milford, CT 06460"),
    PickupLocation("Max Challenge South Windsor", "1735 Ellington Rd, South Windsor, CT 06074",
                   address_format="(Max Challenge) 1735 Ellington Rd, South Windsor, CT 06074"),
]


def _path() -> Path:
    return storage.data_dir() / "pickup_locations.json"


def load_locations() -> list[PickupLocation]:
    data = storage.read_json(_path(), None)
    if not isinstance(data, list):
        return [PickupLocation(**asdict(loc)) for loc in DEFAULT_LOCATIONS]
    out = []
    for d in data:
        if isinstance(d, dict) and d.get("name"):
            out.append(PickupLocation(name=d["name"], address=d.get("address", ""),
                                      address_format=d.get("address_format", ""),
                                      aliases=list(d.get("aliases") or []),
                                      mode=d.get("mode") if d.get("mode") in MODES else "each",
                                      drop_name=d.get("drop_name", "")))
    return out


def save_locations(locations: list[PickupLocation]) -> None:
    storage.write_json(_path(), [asdict(loc) for loc in locations])


# -- small rules from the spec -------------------------------------------------
def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def split_first_last(full: str) -> tuple[str, str]:
    """At the first space: 'Sarah Marie Johnson' -> ('Sarah', 'Marie Johnson')."""
    first, _, rest = " ".join((full or "").split()).partition(" ")
    return first, rest


def fix_zip(z: str) -> str:
    """Digits only, and a leading zero back on 4-digit ZIPs: '6405' -> '06405', '06405-1234' -> '064051234'."""
    digits = re.sub(r"\D", "", z or "")
    return "0" + digits if len(digits) == 4 else digits


def fix_zip_in_address(address: str) -> str:
    """A 4-digit ZIP at the end of an address gets its leading zero: '..., CT 6405' -> '..., CT 06405'."""
    return re.sub(r"(?<!\d)(\d{4})\s*$", lambda m: "0" + m.group(1), " ".join((address or "").split()))


def city_from_address(address: str) -> str:
    """'750 Bridgeport Ave, Shelton, CT 06484' -> 'Shelton'."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    return parts[-2] if len(parts) >= 3 else ""


def is_pickup(fulfillment_type: str) -> bool:
    return bool(re.search(r"pick\s*up", fulfillment_type or "", re.I))


def match_location(name: str, locations: list[PickupLocation]) -> PickupLocation | None:
    """Exact name or another spelling (case and spaces ignored); then again without a trailing '(Town)'."""
    def find(n):
        n = _norm(n)
        return next((loc for loc in locations if n and n in {_norm(loc.name), *map(_norm, loc.aliases)}), None)
    return find(name) or find(re.sub(r"\s*\([^()]*\)\s*$", "", name or ""))


# -- the report ----------------------------------------------------------------
@dataclass
class Report:
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)      # these block the export
    audit: dict = field(default_factory=dict)
    # Home deliveries whose address is a one-drop-off location's address: {location name: [order numbers]}.
    # The Operator reviews them; fold_into_drops() moves the chosen ones into that drop-off.
    fold_candidates: dict[str, list[str]] = field(default_factory=dict)
    drop_locations: dict[str, PickupLocation] = field(default_factory=dict)


def build_report(sheet: Sheet, locations: list[PickupLocation]) -> Report:
    rep = Report()
    missing = [c for c in REQUIRED if c not in sheet.headers]
    if missing:
        rep.errors.append("The orders file is missing these columns: " + ", ".join(missing) +
                          ". Use the store's fulfillment export (the one you drop on Orders CSV).")
        return rep

    orders: dict[str, dict] = {}
    names: dict[str, set] = {}
    for row in sheet.rows:
        key = (row.get("Order") or "").strip()
        if not key:
            continue
        orders.setdefault(key, row)
        names.setdefault(key, set()).add(" ".join((row.get("Customer") or "").split()))
    for key, n in names.items():
        if len(n) > 1:
            rep.warnings.append(f"Order {key} appears with different customers ({', '.join(sorted(n))}).")

    def base(row, customer, full_address, city, location):
        first, last = split_first_last(customer)
        return {"Route#": "", "Order": (row.get("Order") or "").strip(), "Customer": customer,
                "Customer First Name": first, "Customer Last Name": last,
                "Fulfillment Date": (row.get("Fulfillment Date") or "").strip(), "Location": location,
                "City": city, "Full Address": full_address,
                "Customer Email": (row.get("Customer Email") or "").strip(),
                "Customer Phone": (row.get("Customer Phone") or "").strip(),
                "Driver Instructions": (row.get("Driver Instructions") or "").strip(),
                "Shipper": SHIPPER, "Goods": GOODS, "Total Items": (row.get("Total Items") or "").strip()}

    home = pickups_listed = left_off = combined = 0
    home_orders: set[str] = set()
    drops: dict[str, dict] = {}         # one-drop location name -> its row
    for key, row in orders.items():
        customer = " ".join((row.get("Customer") or "").split())
        location = (row.get("Location") or "").strip()
        label = f"Order {key} ({customer or 'no name'})"
        if not customer:
            rep.warnings.append(f"Order {key}: no customer name.")
        if not (row.get("Fulfillment Date") or "").strip():
            rep.warnings.append(f"{label}: no fulfillment date.")
        if not is_pickup(row.get("Fulfillment Type", "")):
            address = fix_zip_in_address(row.get("Full Address", ""))
            if not address:
                rep.warnings.append(f"{label}: home delivery with no address.")
            rep.rows.append(base(row, customer, address, (row.get("City") or "").strip(), location))
            home += 1
            home_orders.add(key)
            _contact_warnings(rep, rep.rows[-1], label)
            continue
        loc = match_location(location, locations)
        if loc is None:
            rep.warnings.append(f"{label}: pickup location “{location or '(blank)'}” isn't in the pickup-location "
                                "list, so its address was left blank. Add it under Pickup locations.")
            rep.rows.append(base(row, customer, "", "", location))
            pickups_listed += 1
            continue
        if loc.mode == "off":
            left_off += 1
            continue
        if loc.mode == "one_drop":
            combined += 1
            drop = drops.get(loc.name)
            if drop is None:
                stop = loc.drop_name or loc.name
                drop = base(row, stop, loc.full_address(), loc.city(), location)
                drop.update({"Order": "", "Customer First Name": stop, "Customer Last Name": "",
                             "Customer Email": "", "Customer Phone": "", "Driver Instructions": "",
                             "Total Items": "0"})
                drops[loc.name] = drop
                rep.rows.append(drop)
            drop["Total Items"] = str(_int(drop["Total Items"]) + _int(row.get("Total Items")))
            continue
        rep.rows.append(base(row, customer, loc.full_address(), loc.city(), location))
        pickups_listed += 1
        _contact_warnings(rep, rep.rows[-1], label)

    for loc in locations:
        if loc.mode == "one_drop":
            found = [r["Order"] for r in rep.rows if r["Order"] in home_orders and same_place(r["Full Address"], loc)]
            if found:
                rep.fold_candidates[loc.name] = found
                rep.drop_locations[loc.name] = loc
    rep.audit = {"orders": len(orders), "rows": len(rep.rows), "home": home, "pickups_listed": pickups_listed,
                 "left_off": left_off, "combined": combined, "drops": len(drops)}
    if home + pickups_listed + len(drops) != len(rep.rows) or home + pickups_listed + left_off + combined != len(orders):
        rep.errors.append("Row count check failed (orders in and rows out don't add up). Please report this.")
    if any(list(r) != COLUMNS for r in rep.rows):
        rep.errors.append("Column check failed. Please report this.")
    return rep


def same_place(address: str, loc: PickupLocation) -> bool:
    """A delivery address is the location's when it has the location's street number and street name
    and its town, e.g. '(Chapel Haven) 1040 Whalley Avenue, Apt 304, New Haven' for '1040 Whalley Ave, New Haven'."""
    m = re.match(r"\s*(\d+)\s+([A-Za-z]+)", loc.address or "")
    city = loc.city().lower()
    if not m or not city:
        return False
    text = (address or "").lower()
    return bool(re.search(rf"(?<!\d){m.group(1)}\s+{re.escape(m.group(2).lower())}\b", text)) and city in text


def fold_into_drops(rep: Report, orders: list[str]) -> None:
    """Move the chosen home deliveries (order numbers) into their location's drop-off stop."""
    chosen = set(orders)
    for loc_name, candidates in rep.fold_candidates.items():
        loc = rep.drop_locations[loc_name]
        stop = loc.drop_name or loc.name
        for order in candidates:
            if order not in chosen:
                continue
            i = next((n for n, r in enumerate(rep.rows) if r["Order"] == order), None)
            if i is None:
                continue
            row = rep.rows.pop(i)
            drop = next((r for r in rep.rows if not r["Order"] and r["Customer"] == stop), None)
            if drop is None:  # no pickups there this week: the drop-off starts with this order
                drop = dict(row, **{"Order": "", "Customer": stop, "Customer First Name": stop,
                                    "Customer Last Name": "", "Location": loc.name, "City": loc.city(),
                                    "Full Address": loc.full_address(), "Customer Email": "", "Customer Phone": "",
                                    "Driver Instructions": "", "Total Items": "0"})
                rep.rows.insert(i, drop)
                rep.audit["drops"] += 1
            drop["Total Items"] = str(_int(drop["Total Items"]) + _int(row["Total Items"]))
            rep.audit["home"] -= 1
            rep.audit["combined"] += 1
    rep.audit["rows"] = len(rep.rows)
    rep.fold_candidates = {}


def _contact_warnings(rep: Report, row: dict, label: str) -> None:
    for col, what in (("Customer Email", "email"), ("Customer Phone", "phone")):
        if not row[col]:
            rep.warnings.append(f"{label}: no {what}.")


def _int(v) -> int:
    try:
        return int(float(str(v).strip() or 0))
    except ValueError:
        return 0


def write_report(path: str | Path, rows: list[dict]) -> None:
    """UTF-8 CSV with exactly the 15 template columns, everything as text."""
    path = Path(path)
    tmp = path.with_name(path.name + ".partial")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r.get(c, "") for c in COLUMNS])
    tmp.replace(path)
