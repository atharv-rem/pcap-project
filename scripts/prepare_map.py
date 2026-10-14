#!/usr/bin/env python3
"""Build data/grid.bin + data/grid.meta (contract C1) from SRTM 1 arc-second tiles.

    python3 scripts/prepare_map.py --input data/raw/*.tif --bbox 12.83 13.14 77.45 77.78 --out data/
    python3 scripts/prepare_map.py --synthetic --out data/      # fake terrain, same size

Inputs: .hgt (SRTM, e.g. N12E077.hgt) or GeoTIFF (.tif/.tiff, EPSG:4326). GeoTIFFs are read
with rasterio if it is installed, otherwise with Pillow + the GeoTIFF tags. The output grid
uses the source pixel lattice (1 arc-second cells), cropped to the bbox, voids filled with
the nearest valid height. Needs numpy; scipy is used for void filling if available.
"""
import argparse
import glob
import math
import os
import re
import gzip
import sys

import numpy as np

ARCSEC = 1.0 / 3600.0
DEFAULT_BBOX = (12.83, 13.14, 77.45, 77.78)  # lat_min lat_max lon_min lon_max


class Tile:
    """A raster in lat/lon: data[row, col], top-left corner of pixel (0,0) at (lat0, lon0)."""

    def __init__(self, path, data, lat0, lon0, dlat, dlon, nodata):
        self.path, self.data = path, data
        self.lat0, self.lon0, self.dlat, self.dlon = lat0, lon0, dlat, dlon
        self.nodata = nodata


def read_hgt(path):
    m = re.search(r"([NS])(\d{2})([EW])(\d{3})", os.path.basename(path).upper())
    if not m:
        sys.exit(f"cannot read the tile position from the file name {path} (expected e.g. N12E077.hgt)")
    lat = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
    lon = int(m.group(4)) * (1 if m.group(3) == "E" else -1)
    if path.lower().endswith(".gz"):
        with gzip.open(path, "rb") as f:
            raw = np.frombuffer(f.read(), dtype=">i2")
    else:
        raw = np.fromfile(path, dtype=">i2")
    side = int(round(math.sqrt(raw.size)))
    if side * side != raw.size:
        sys.exit(f"{path}: {raw.size} values is not a square .hgt tile")
    step = 1.0 / (side - 1)
    data = raw.reshape(side, side).astype(np.float32)
    # .hgt pixel centres sit on whole arc-seconds, the first one at (lat+1, lon)
    return Tile(path, data, lat + 1 + step / 2, lon - step / 2, step, step, -32768.0)


def read_tif_rasterio(path):
    import rasterio  # optional

    with rasterio.open(path) as ds:
        if ds.crs is not None and ds.crs.to_epsg() not in (4326, None):
            sys.exit(f"{path}: CRS {ds.crs} is not EPSG:4326 (lat/lon); reproject it first")
        t = ds.transform
        data = ds.read(1).astype(np.float32)
        nodata = ds.nodata
    return Tile(path, data, t.f, t.c, -t.e, t.a, nodata)


def read_tif_pillow(path):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    img = Image.open(path)
    tags = img.tag_v2
    scale = tags.get(33550)  # ModelPixelScaleTag
    tie = tags.get(33922)    # ModelTiepointTag
    if not scale or not tie:
        sys.exit(f"{path}: no GeoTIFF position tags; install rasterio or use .hgt files")
    keys = tags.get(34735)   # GeoKeyDirectoryTag
    pixel_is_point = False
    if keys:
        for k in range(4, len(keys), 4):
            if keys[k] == 1025 and keys[k + 3] == 2:  # GTRasterTypeGeoKey = RasterPixelIsPoint
                pixel_is_point = True
    nodata = tags.get(42113)  # GDAL_NODATA
    nodata = float(str(nodata).strip("\x00 ")) if nodata is not None else None
    data = np.array(img).astype(np.float32)
    i, j, _, x, y, _ = tie[:6]
    dlon, dlat = float(scale[0]), float(scale[1])
    lon0 = x - i * dlon
    lat0 = y + j * dlat
    if pixel_is_point:
        lon0 -= dlon / 2
        lat0 += dlat / 2
    return Tile(path, data, lat0, lon0, dlat, dlon, nodata)


def read_tile(path):
    if path.lower().endswith(".hgt.gz"):
        return read_hgt(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".hgt":
        return read_hgt(path)
    if ext in (".tif", ".tiff"):
        try:
            import rasterio  # noqa: F401
            return read_tif_rasterio(path)
        except ImportError:
            return read_tif_pillow(path)
    sys.exit(f"{path}: unsupported file type (use .hgt or .tif)")


def fill_voids(h, void):
    """Replace void cells with the height of the nearest valid cell."""
    if not void.any():
        return h
    try:
        from scipy import ndimage

        idx = ndimage.distance_transform_edt(void, return_distances=False, return_indices=True)
        return h[tuple(idx)]
    except ImportError:
        pass
    # numpy-only fallback: grow valid values into the voids one ring at a time
    h = h.copy()
    void = void.copy()
    while void.any():
        acc = np.zeros_like(h, dtype=np.float64)
        cnt = np.zeros_like(h, dtype=np.int32)
        valid = ~void
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            vs = np.roll(valid, (dr, dc), axis=(0, 1))
            hs = np.roll(np.where(valid, h, 0), (dr, dc), axis=(0, 1))
            if dr == 1: vs[0, :] = False
            if dr == -1: vs[-1, :] = False
            if dc == 1: vs[:, 0] = False
            if dc == -1: vs[:, -1] = False
            acc += np.where(vs, hs, 0)
            cnt += vs
        grow = void & (cnt > 0)
        if not grow.any():
            raise SystemExit("void filling failed: no valid heights at all")
        h[grow] = (acc[grow] / cnt[grow]).astype(h.dtype)
        void &= ~grow
    return h


def box_smooth(h):
    """3x3 box average (edge cells use the nearest edge values). Removes single-cell
    pits and spikes from the SRTM noise so water does not get stuck in them."""
    p = np.pad(h.astype(np.float64), 1, mode="edge")
    rows, cols = h.shape
    acc = np.zeros((rows, cols), dtype=np.float64)
    for dr in range(3):
        for dc in range(3):
            acc += p[dr:dr + rows, dc:dc + cols]
    return (acc / 9.0).astype(np.float32)


def grid_shape(bbox, cell):
    lat_min, lat_max, lon_min, lon_max = bbox
    return int(round((lat_max - lat_min) / cell)), int(round((lon_max - lon_min) / cell))


def build_real(paths, bbox):
    tiles = [read_tile(p) for p in paths]
    ref = tiles[0]
    if abs(ref.dlat - ARCSEC) > 0.05 * ARCSEC or abs(ref.dlon - ARCSEC) > 0.05 * ARCSEC:
        print(f"WARNING: {ref.path} has {ref.dlat * 3600:.3f} x {ref.dlon * 3600:.3f} arc-second "
              "pixels, expected 1 arc-second (SRTM1)")
    cell = ref.dlat
    lat_min, lat_max, lon_min, lon_max = bbox
    # snap the grid to the source pixel lattice so cells are copied, not resampled
    lat_top = ref.lat0 - round((ref.lat0 - lat_max) / cell) * cell
    lon_left = ref.lon0 + round((lon_min - ref.lon0) / ref.dlon) * ref.dlon
    rows, cols = grid_shape(bbox, cell)

    lat_c = lat_top - (np.arange(rows) + 0.5) * cell
    lon_c = lon_left + (np.arange(cols) + 0.5) * ref.dlon
    out = np.full((rows, cols), np.nan, dtype=np.float32)
    for t in tiles:
        rr = np.floor((t.lat0 - lat_c) / t.dlat).astype(np.int64)
        cc = np.floor((lon_c - t.lon0) / t.dlon).astype(np.int64)
        rok = (rr >= 0) & (rr < t.data.shape[0])
        cok = (cc >= 0) & (cc < t.data.shape[1])
        if not rok.any() or not cok.any():
            print(f"  {os.path.basename(t.path)}: does not overlap the bbox, skipped")
            continue
        vals = t.data[np.ix_(rr[rok], cc[cok])]
        bad = ~np.isfinite(vals) | (vals < -1000)
        if t.nodata is not None:
            bad |= vals == t.nodata
        vals = np.where(bad, np.nan, vals)
        sub = out[np.ix_(np.where(rok)[0], np.where(cok)[0])]
        take = np.isnan(sub)                      # first tile wins where tiles overlap
        sub[take] = vals[take]
        out[np.ix_(np.where(rok)[0], np.where(cok)[0])] = sub
        print(f"  {os.path.basename(t.path)}: {t.data.shape[0]}x{t.data.shape[1]} pixels, "
              f"covers {int(rok.sum())} rows x {int(cok.sum())} cols of the grid")
    return out, lat_top, lon_left, cell, "SRTM 1 arc-second"


def smooth_noise(rng, rows, cols, scale_cells):
    """Gaussian random field with features about `scale_cells` wide, std 1."""
    f = np.fft.rfft2(rng.standard_normal((rows, cols)))
    ky = np.fft.fftfreq(rows)[:, None]
    kx = np.fft.rfftfreq(cols)[None, :]
    f *= np.exp(-((kx ** 2 + ky ** 2) * (scale_cells ** 2)) * 2.0)
    n = np.fft.irfft2(f, s=(rows, cols))
    return (n - n.mean()) / n.std()


def build_synthetic(bbox, seed=42):
    cell = ARCSEC
    rows, cols = grid_shape(bbox, cell)
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float64)
    yf, xf = y / rows, x / cols
    # gentle plateau tilting down to the south-east, ~880-940 m like Bengaluru
    h = 935.0 - 30.0 * yf - 20.0 * xf
    h += 12.0 * smooth_noise(rng, rows, cols, 150)   # rolling hills
    h += 3.0 * smooth_noise(rng, rows, cols, 25)     # smaller ridges
    # a valley running north to south-east, draining off the bottom edge
    centre = 0.35 + 0.30 * yf + 0.06 * np.sin(5.0 * yf)
    h -= 15.0 * np.exp(-(((xf - centre) * cols / 45.0) ** 2))
    # bowls (lake/tank-like depressions)
    for _ in range(8):
        r0, c0 = rng.uniform(0.1, 0.9) * rows, rng.uniform(0.1, 0.9) * cols
        rad, depth = rng.uniform(20, 60), rng.uniform(3, 8)
        q = ((y - r0) ** 2 + (x - c0) ** 2) / rad ** 2
        h -= np.where(q < 1, depth * (1 - q) ** 2, 0.0)
    h += 0.03 * rng.standard_normal((rows, cols))     # sensor-like noise
    return h.astype(np.float32), bbox[1], bbox[2], cell, "SYNTHETIC (not real terrain)"


def downsample(h, k):
    """Average k x k blocks into one cell (rows/cols that do not fill a block are dropped)."""
    rows, cols = h.shape[0] // k, h.shape[1] // k
    blocks = h[:rows * k, :cols * k].astype(np.float64).reshape(rows, k, cols, k)
    return blocks.mean(axis=(1, 3)).astype(np.float32)


def write_grid(out_dir, h, lat_top, lon_left, cell, source, cell_size_m=30.0):
    os.makedirs(out_dir, exist_ok=True)
    rows, cols = h.shape
    h.astype("<f4").tofile(os.path.join(out_dir, "grid.bin"))
    with open(os.path.join(out_dir, "grid.meta"), "w", newline="\n") as f:
        f.write(f"rows={rows}\ncols={cols}\ncell_size_m={cell_size_m:.1f}\n")
        f.write(f"lat_top={lat_top:.9f}\nlon_left={lon_left:.9f}\ncell_deg={cell:.12f}\n")
        f.write(f"source={source}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", nargs="*", default=None,
                    help="SRTM tiles (.hgt / .tif); default: everything in data/raw/")
    ap.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX),
                    metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"))
    ap.add_argument("--out", default="data/")
    ap.add_argument("--synthetic", action="store_true", help="generate fake terrain instead")
    ap.add_argument("--seed", type=int, default=42, help="random seed for --synthetic")
    ap.add_argument("--smooth", action=argparse.BooleanOptionalAction, default=True,
                    help="3x3 box average of the heights (default: on; --no-smooth to skip)")
    ap.add_argument("--downsample", type=int, default=1, metavar="K",
                    help="average K x K cells into one (quick tests; default 1 = full resolution)")
    a = ap.parse_args()
    if a.downsample < 1:
        sys.exit("--downsample must be >= 1")
    bbox = tuple(a.bbox)
    if not (bbox[0] < bbox[1] and bbox[2] < bbox[3]):
        sys.exit("bbox must be LAT_MIN LAT_MAX LON_MIN LON_MAX with min < max")

    if a.synthetic:
        print("=" * 64)
        print("  WARNING: GENERATING SYNTHETIC TERRAIN - THIS IS NOT REAL DATA")
        print("  Results from this grid say nothing about Bengaluru.")
        print("=" * 64)
        h, lat_top, lon_left, cell, source = build_synthetic(bbox, a.seed)
        n_void = 0
    else:
        paths = a.input
        if not paths:
            paths = sorted(p for ext in ("hgt", "HGT", "hgt.gz", "tif", "tiff", "TIF")
                           for p in glob.glob(os.path.join("data", "raw", f"*.{ext}")))
        paths = [p for pat in paths for p in (sorted(glob.glob(pat)) or [pat])]  # Windows globbing
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            sys.exit("No SRTM input files found. Put the SRTM 1 arc-second tiles covering the bbox\n"
                     "(for Bengaluru: N12E077 and N13E077, as .hgt or GeoTIFF) into data/raw/\n"
                     "and run again, or use --synthetic for fake terrain.")
        print(f"reading {len(paths)} tile(s)")
        h, lat_top, lon_left, cell, source = build_real(paths, bbox)
        void = ~np.isfinite(h)
        n_void = int(void.sum())
        if n_void == h.size:
            sys.exit("None of the input tiles cover the bbox. Check the tiles and --bbox.")
        if n_void > 0.01 * h.size:
            print(f"WARNING: {n_void} of {h.size} cells ({100.0 * n_void / h.size:.1f}%) are voids "
                  "or not covered by any tile; a tile may be missing")
        h = fill_voids(h, void)

    if a.smooth:
        h = box_smooth(h)
        source += ", 3x3 smoothed"
    if a.downsample > 1:
        h = downsample(h, a.downsample)
        cell *= a.downsample
        source += f", downsampled {a.downsample}x"
    write_grid(a.out, h, lat_top, lon_left, cell, source, 30.0 * a.downsample)
    rows, cols = h.shape
    print(f"source      : {source}")
    print(f"rows x cols : {rows} x {cols}")
    print(f"top-left    : lat {lat_top:.6f}, lon {lon_left:.6f}, cell {cell * 3600:.3f} arc-sec")
    print(f"height      : min {h.min():.1f} m, max {h.max():.1f} m, mean {h.mean():.1f} m")
    print(f"voids filled: {n_void}")
    print(f"smoothing   : {'3x3 box average' if a.smooth else 'off'}")
    print(f"downsample  : {str(a.downsample) + 'x' + str(a.downsample) + ' block average' if a.downsample > 1 else 'off'}")
    print(f"cell size   : {30.0 * a.downsample:.1f} m")
    print(f"wrote {os.path.join(a.out, 'grid.bin')} and {os.path.join(a.out, 'grid.meta')}")


if __name__ == "__main__":
    main()
