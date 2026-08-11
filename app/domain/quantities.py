"""Rundung auf die Kaufeinheit, siehe docs/PLAN.md §4.

Reine Logik: kein SQL, kein I/O.
"""

from __future__ import annotations


def reorder_quantity(*, stock: int, target_stock: int, pack_size: int) -> int:
    """Nachkaufmenge: `ceil((target_stock - stock) / pack_size) * pack_size`.

    Mindestens `pack_size` — eine Kaufeinheit wird immer vorgeschlagen, auch wenn der
    rechnerische Bedarf null oder negativ ist.
    """
    needed = target_stock - stock
    packs = -(-needed // pack_size) if needed > 0 else 0
    return max(packs * pack_size, pack_size)
