#!/usr/bin/env python3
"""Download OpenStreetMap tiles for the grid area and make a basemap picture.

usage: python3 scripts/osm_basemap.py [--meta data/grid.meta] [--zoom 13]
                                      [--out data/raw/osm]

Downloads the standard OSM tiles (tile.openstreetmap.org) covering the grid once and caches
them in OUT/tiles/ (about 64 tiles at zoom 13; please do not raise the zoom much, the OSM
tile policy forbids bulk downloads). The tiles are stitched and reprojected from Web
Mercator to the grid's lat/lon lattice, so the picture lines up exactly with the grid:
  OUT/basemap.png        original colours
  OUT/basemap_muted.png  mostly grey (water and parks would clash with the flood colours)
  OUT/basemap.txt        lat_top, lon_left, lat_bottom, lon_right of the pictures
make_risk_map.py and build/live use basemap_muted.png when it exists.
Map data and tiles: (c) OpenStreetMap contributors (ODbL / CC BY-SA); always credit them.
"""
import argparse
import io
import math
import os
import time
import urllib.request

import matplotlib.image as mpimg
import numpy as np

from rank_areas import read_meta

TILE = 256
URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "flood-risk-mpi-student-project/1.0 (university course; one-off basemap)"
MUTE = 0.25   # share of the original colour kept in the muted picture


def tile_xy(lat, lon, z):
    """Fractional tile coordinates (Web Mercator)."""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def fetch(z, x, y, cache):
    path = os.path.join(cache, str(z), str(x), f"{y}.png")
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        req = urllib.request.Request(URL.format(z=z, x=x, y=y),
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
        time.sleep(0.25)                       # be gentle with the tile servers
    img = mpimg.imread(path)
    if img.dtype != np.float32 and img.dtype != np.float64:
        img = img.astype(np.float32) / 255.0
    return img[:, :, :3]


def main():
    ap = argparse.ArgumentParser(description="Make an OpenStreetMap basemap for the grid.")
    ap.add_argument("--meta", default="data/grid.meta")
    ap.add_argument("--zoom", type=int, default=13)
    ap.add_argument("--out", default="data/raw/osm")
    a = ap.parse_args()
    m = read_meta(a.meta)
    lat_top, lon_left = m["lat_top"], m["lon_left"]
    lat_bot = lat_top - m["rows"] * m["cell_deg"]
    lon_right = lon_left + m["cols"] * m["cell_deg"]
    z = a.zoom

    x0, y0 = tile_xy(lat_top, lon_left, z)
    x1, y1 = tile_xy(lat_bot, lon_right, z)
    tx = range(int(x0), int(x1) + 1)
    ty = range(int(y0), int(y1) + 1)
    print(f"zoom {z}: {len(tx)} x {len(ty)} = {len(tx) * len(ty)} tiles")
    cache = os.path.join(a.out, "tiles")
    mosaic = np.zeros((len(ty) * TILE, len(tx) * TILE, 3), dtype=np.float32)
    for j, y in enumerate(ty):
        for i, x in enumerate(tx):
            mosaic[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE] = fetch(z, x, y, cache)

    # output lattice: same degrees per pixel both ways (like the grid), at tile resolution
    deg_px = 360.0 / (TILE * 2 ** z)
    W = int(round((lon_right - lon_left) / deg_px))
    H = int(round((lat_top - lat_bot) / deg_px))
    lons = lon_left + (np.arange(W) + 0.5) * (lon_right - lon_left) / W
    lats = lat_top - (np.arange(H) + 0.5) * (lat_top - lat_bot) / H
    px = np.array([tile_xy(lat_top, lo, z)[0] for lo in lons]) - tx[0]
    py = np.array([tile_xy(la, lon_left, z)[1] for la in lats]) - ty[0]
    ci = np.clip((px * TILE).astype(int), 0, mosaic.shape[1] - 1)
    ri = np.clip((py * TILE).astype(int), 0, mosaic.shape[0] - 1)
    pic = mosaic[np.ix_(ri, ci)]

    grey = (0.299 * pic[..., 0] + 0.587 * pic[..., 1] + 0.114 * pic[..., 2])[..., None]
    muted = MUTE * pic + (1 - MUTE) * grey
    muted = 0.15 + 0.85 * muted                # a little lighter, so overlays stand out

    os.makedirs(a.out, exist_ok=True)
    mpimg.imsave(os.path.join(a.out, "basemap.png"), np.clip(pic, 0, 1))
    mpimg.imsave(os.path.join(a.out, "basemap_muted.png"), np.clip(muted, 0, 1))
    with open(os.path.join(a.out, "basemap.txt"), "w") as f:
        f.write(f"lat_top={lat_top:.9f}\nlon_left={lon_left:.9f}\n"
                f"lat_bottom={lat_bot:.9f}\nlon_right={lon_right:.9f}\nzoom={z}\n"
                "attribution=(c) OpenStreetMap contributors\n")
    print(f"wrote {a.out}/basemap.png and basemap_muted.png ({W} x {H} px); "
          f"credit: (c) OpenStreetMap contributors")


if __name__ == "__main__":
    main()
