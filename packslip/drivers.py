"""Driver assignment and the delivery list.

The Operator assigns a driver to each delivery order (Assign Drivers…). Assignments are
remembered per customer, per layout, so returning customers are pre-assigned next week.
When drivers are assigned, the PDF starts with a delivery list (one section per driver,
stops in order) and the pack slips follow in the same order, each showing
"Driver: Mike · Stop 3".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import storage

UNASSIGNED = "No driver yet"


def is_pickup(values: dict) -> bool:
    return bool(re.search(r"pick\s*up", values.get("fulfillment", "") or "", re.I))


def customer_key(values: dict) -> str:
    """Identifies a customer across weeks (name + address, case/space-insensitive)."""
    def norm(s):
        return " ".join((s or "").lower().split())
    return f"{norm(values.get('customer_name'))}|{norm(values.get('address'))}"


def _zip(address: str) -> str:
    m = re.findall(r"\b\d{5}\b", address or "")
    return m[-1] if m else "99999"


def town(address: str) -> str:
    """'141 WOODLAND ST APT 2, Meriden, CT 06450' -> 'Meriden'."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    return parts[-2] if len(parts) >= 3 else (parts[-1] if parts else "")


@dataclass
class DriverBook:
    """Driver names and remembered assignments for one layout."""
    layout: str
    names: list[str] = field(default_factory=list)
    memory: dict[str, str] = field(default_factory=dict)  # customer_key -> driver

    # Stored in their own file (drivers.json), keyed by layout, so other settings writes can't clobber them.
    @staticmethod
    def _path():
        return storage.data_dir() / "drivers.json"

    @classmethod
    def load(cls, layout: str) -> "DriverBook":
        data = (storage.read_json(cls._path(), {}) or {}).get(layout) or {}
        return cls(layout=layout, names=list(data.get("names") or []), memory=dict(data.get("memory") or {}))

    def save(self) -> None:
        data = storage.read_json(self._path(), {}) or {}
        data[self.layout] = {"names": self.names, "memory": self.memory}
        storage.write_json(self._path(), data)

    def suggest(self, all_values: list[dict]) -> dict[int, str]:
        """Pre-assign deliveries to the driver they had before."""
        out = {}
        for i, v in enumerate(all_values):
            d = self.memory.get(customer_key(v))
            if d and not is_pickup(v):
                out[i] = d
        return out

    def remember(self, all_values: list[dict], assignment: dict[int, str]) -> None:
        for i, v in enumerate(all_values):
            if is_pickup(v):
                continue
            key = customer_key(v)
            if assignment.get(i):
                self.memory[key] = assignment[i]
                if assignment[i] not in self.names:
                    self.names.append(assignment[i])
            else:
                self.memory.pop(key, None)


@dataclass
class Plan:
    """Print order: each driver's stops, then unassigned deliveries, then pickups by location."""
    routes: list[tuple[str, list[int]]]          # (driver or UNASSIGNED, record indexes in stop order)
    pickups: list[tuple[str, list[int]]]         # (pickup location, record indexes)

    def order(self) -> list[int]:
        return [i for _, idx in self.routes for i in idx] + [i for _, idx in self.pickups for i in idx]

    def stop_of(self) -> dict[int, tuple[str, int]]:
        out = {}
        for driver, idx in self.routes:
            if driver == UNASSIGNED:
                continue
            for n, i in enumerate(idx, 1):
                out[i] = (driver, n)
        return out


def make_plan(all_values: list[dict], assignment: dict[int, str], driver_order: list[str]) -> Plan:
    groups: dict[str, list[int]] = {}
    pickups: dict[str, list[int]] = {}
    for i, v in enumerate(all_values):
        if is_pickup(v):
            pickups.setdefault(v.get("pickup_location") or "Pickup", []).append(i)
        else:
            groups.setdefault(assignment.get(i) or UNASSIGNED, []).append(i)

    def stop_key(i):  # rough geographic order: by zip, then town, then street
        a = all_values[i].get("address", "")
        return (_zip(a), town(a).lower(), a.lower())

    rank = {d: n for n, d in enumerate(driver_order)}
    drivers = sorted((d for d in groups if d != UNASSIGNED), key=lambda d: (rank.get(d, len(rank)), d.lower()))
    routes = [(d, sorted(groups[d], key=stop_key)) for d in drivers]
    if UNASSIGNED in groups:
        routes.append((UNASSIGNED, sorted(groups[UNASSIGNED], key=stop_key)))
    pickup_list = [(loc, sorted(idx, key=lambda i: all_values[i].get("customer_name", "").lower()))
                   for loc, idx in sorted(pickups.items(), key=lambda kv: kv[0].lower())]
    return Plan(routes=routes, pickups=pickup_list)
