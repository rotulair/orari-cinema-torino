"""Coordinate dei cinema (per ordinarli per distanza dalla zona scelta dall'utente).

Si cercano una sola volta su OpenStreetMap (Nominatim) e si salvano in data/coordinates.json.
Per correggere una posizione a mano: modifica il file e aggiungi "manual": true a quel cinema
(non verra' piu' sovrascritta)."""
from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path

NOMINATIM = "https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=it&q="
LAT = (44.95, 45.20)    # riquadro di Torino e dintorni: scarta risultati finiti altrove
LON = (7.55, 7.80)


def queries(c: dict) -> list[str]:
    q = []
    if c.get("address"):
        q.append(f"{c['address']}, Torino, Italia")
    q.append(f"{c['name']}, Torino, Italia")
    if "cinema" not in c["name"].lower():
        q.append(f"Cinema {c['name']}, Torino, Italia")
    return q


def parse_result(text: str) -> tuple[float, float] | None:
    try:
        arr = json.loads(text)
        lat, lon = float(arr[0]["lat"]), float(arr[0]["lon"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return (lat, lon) if LAT[0] <= lat <= LAT[1] and LON[0] <= lon <= LON[1] else None


def ensure(cinemas: list[dict], path: Path, fetcher, sleep: float = 1.2) -> dict:
    """cinemas: [{id, name, address}]. Cerca solo i cinema senza coordinate (o con indirizzo cambiato)."""
    try:
        coords = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        coords = {}
    changed = False
    for c in cinemas:
        cur = coords.get(c["id"])
        if cur and (cur.get("manual") or cur.get("addr") == (c.get("address") or c["name"])):
            continue
        found = None
        for q in queries(c):
            try:
                found = parse_result(fetcher(NOMINATIM + urllib.parse.quote(q)))
            except Exception as exc:  # noqa: BLE001 - la posizione e' facoltativa
                print(f"  coordinate: {c['name']}: {exc}")
            time.sleep(sleep)
            if found:
                break
        if found:
            coords[c["id"]] = {"lat": round(found[0], 5), "lon": round(found[1], 5), "addr": c.get("address") or c["name"]}
            changed = True
            print(f"  coordinate: {c['name']} -> {found[0]:.4f}, {found[1]:.4f}")
        else:
            print(f"  coordinate: {c['name']} non trovate")
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(coords, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return coords
