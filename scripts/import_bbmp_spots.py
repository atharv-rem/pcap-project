#!/usr/bin/env python3
"""Build data/known_spots.csv from the BBMP flood-location maps (contract C5 format).

usage: python3 scripts/import_bbmp_spots.py [--raw data/raw] [--out data/known_spots.csv]

Input: three KML point files from the OpenCity "Flooding Locations in Bengaluru Urban"
dataset (publisher BBMP, source KSRSAC), downloaded into --raw:
  bbmp_vulnerable_points.kml  "Map of Locations Vulnerable to Flooding" (200 points)
  bbmp_flood_prone.kml        "Flood Prone Locations Map" (70 points)
  bbmp_low_lying.kml          "BBMP Low Lying Areas" (129 points)
These are official locations, so they are written with verified=yes and the exact
download link as source_url. Points within DEDUP_M of one already kept are dropped.
The team's original seed spots (approximate, verified=no) are kept at the top.
"""
import argparse
import csv
import math
import os
import xml.etree.ElementTree as ET

DATASET = ("https://data.opencity.in/dataset/b03218ea-4b7c-4fa9-ab67-b9054d7ecc4c/resource/")
SOURCES = [   # file, label, resource URL
    ("bbmp_vulnerable_points.kml", "BBMP vulnerable",
     DATASET + "a7d8a01f-1fbc-41e1-85f0-f15ea16b2d27"),
    ("bbmp_flood_prone.kml", "BBMP flood-prone",
     DATASET + "d90fe768-caba-4c6e-b6b5-a75acd5e88a9"),
    ("bbmp_low_lying.kml", "BBMP low-lying",
     DATASET + "62ceac3b-f6e2-4dd1-ae9f-be80b1f2fda8"),
]
SEEDS = [   # the team's starting list (approximate, not verified)
    ("Silk Board Junction", 12.9177, 77.6238),
    ("Bellandur", 12.9304, 77.6784),
    ("Marathahalli", 12.9569, 77.7011),
    ("Koramangala", 12.9352, 77.6245),
    ("Hebbal", 13.0358, 77.5970),
]
DEDUP_M = 50.0
NS = {"k": "http://www.opengis.net/kml/2.2"}


def clean(s):
    """One line, no commas (the live demo reads the CSV with a simple splitter)."""
    s = " ".join((s or "").split())
    return s.replace(",", " -").replace('"', "")


def read_kml(path):
    """[(name, lat, lon)] from KML Placemark points."""
    root = ET.parse(path).getroot()
    out = []
    for pm in root.iter("{%s}Placemark" % NS["k"]):
        coords = pm.find(".//k:Point/k:coordinates", NS)
        if coords is None or not coords.text:
            continue
        lon, lat = (float(v) for v in coords.text.strip().split(",")[:2])
        if not (math.isfinite(lat) and math.isfinite(lon)):
            print(f"{os.path.basename(path)}: skipped a point with no coordinates")
            continue
        data = {sd.get("name"): sd.text for sd in pm.iter("{%s}SimpleData" % NS["k"])}
        name = data.get("LocationName") or (pm.findtext("k:name", default="", namespaces=NS))
        ward = data.get("WARD_NAME")
        name = clean(name) or "(unnamed)"
        if ward:
            name = f"{name} ({clean(ward)})"
        out.append((name, lat, lon))
    return out


def dist_m(a, b):
    dy = (a[0] - b[0]) * 111320.0
    dx = (a[1] - b[1]) * 111320.0 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def main():
    ap = argparse.ArgumentParser(description="Import BBMP flood points into known_spots.csv.")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/known_spots.csv")
    a = ap.parse_args()

    rows = [(n, lat, lon, "", "no") for n, lat, lon in SEEDS]
    kept = []
    for fname, label, url in SOURCES:
        path = os.path.join(a.raw, fname)
        if not os.path.isfile(path):
            print(f"missing {path}, skipped")
            continue
        pts = read_kml(path)
        added = 0
        for name, lat, lon in pts:
            if any(dist_m((lat, lon), k) < DEDUP_M for k in kept):
                continue
            kept.append((lat, lon))
            rows.append((f"{label}: {name}", lat, lon, url, "yes"))
            added += 1
        print(f"{fname}: {len(pts)} points, {added} added ({len(pts) - added} duplicates)")

    with open(a.out, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["name", "lat", "lon", "source_url", "verified"])
        for name, lat, lon, url, ver in rows:
            w.writerow([name, f"{lat:.6f}", f"{lon:.6f}", url, ver])
    print(f"wrote {a.out}: {len(rows)} spots ({len(SEEDS)} team seeds, verified=no; "
          f"{len(rows) - len(SEEDS)} BBMP points, verified=yes)")


if __name__ == "__main__":
    main()
