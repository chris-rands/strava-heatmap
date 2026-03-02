"""
Static heatmap export: generates a multi-panel PNG/JPEG showing
running hotspots with dark basemap and heatmap overlay.
"""

import argparse
import json
import logging
import math
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
from sklearn.cluster import DBSCAN
from scipy.ndimage import gaussian_filter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import contextily as cx

from parser import StravaDataParser
from cache import CoordinateCache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom colormap: transparent → deep red → orange → yellow → white
# High alpha so routes are vivid over the dimmed basemap
_CMAP_POSITIONS = [0.0, 0.05, 0.25, 0.5, 0.8, 1.0]
_CMAP_RGBS = [
    (0.0, 0.0, 0.0),
    (0.7, 0.0, 0.05),
    (1.0, 0.2, 0.0),
    (1.0, 0.6, 0.0),
    (1.0, 0.95, 0.2),
    (1.0, 1.0, 0.9),
]
_CMAP_ALPHAS = [0.0, 0.7, 0.85, 0.9, 0.95, 1.0]

HEATMAP_CMAP = LinearSegmentedColormap.from_list(
    'strava_heat',
    list(zip(_CMAP_POSITIONS, _CMAP_RGBS)),
)


# On-disk cache for geocoding results so we only hit Nominatim once per location
_GEOCODE_CACHE_PATH = Path('.cache/geocode.json')


def _load_geocode_cache() -> dict:
    try:
        return json.loads(_GEOCODE_CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_geocode_cache(cache: dict) -> None:
    _GEOCODE_CACHE_PATH.parent.mkdir(exist_ok=True)
    _GEOCODE_CACHE_PATH.write_text(json.dumps(cache))


def _reverse_geocode(lat: float, lon: float) -> str:
    """Get a human-readable place name via Nominatim reverse geocoding.

    Results are cached to disk so repeated runs don't re-request.
    """
    # Round to 2 decimal places (~1km) for cache key stability
    cache_key = f'{lat:.2f},{lon:.2f}'
    cache = _load_geocode_cache()
    if cache_key in cache:
        return cache[cache_key]

    params = urllib.parse.urlencode({
        'lat': f'{lat:.5f}',
        'lon': f'{lon:.5f}',
        'format': 'json',
        'zoom': 10,
        'addressdetails': 1,
    })
    url = f'https://nominatim.openstreetmap.org/reverse?{params}'
    req = urllib.request.Request(url, headers={'User-Agent': 'strava-heatmap-export/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        addr = data.get('address', {})
        name = (
            addr.get('city')
            or addr.get('town')
            or addr.get('village')
            or addr.get('county')
            or addr.get('state')
        )
        country = addr.get('country_code', '').upper()
        if name and country:
            result = f'{name}, {country}'
        elif name:
            result = name
        else:
            result = data.get('display_name', '').split(',')[0]

        cache[cache_key] = result
        _save_geocode_cache(cache)
        return result
    except Exception as e:
        logger.warning(f'Reverse geocoding failed for ({lat:.3f}, {lon:.3f}): {e}')
        return f'{lat:.2f}\u00b0N, {lon:.2f}\u00b0E'


def latlon_array_to_mercator(
    lats: np.ndarray, lons: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert lat/lon arrays to EPSG:3857 (Web Mercator) coordinates."""
    x = lons * 20037508.34 / 180.0
    y = np.log(np.tan((90.0 + lats) * math.pi / 360.0)) / (math.pi / 180.0)
    y = y * 20037508.34 / 180.0
    return x, y


def detect_hotspots(
    coordinates: List[Tuple[float, float]],
    n_hotspots: int = 2,
    eps_km: float = 2.0,
    min_samples: int = 50,
    max_cluster_points: int = 20_000,
    total_activities: int = 0,
    total_distance_km: float = 0.0,
) -> list:
    """Cluster GPS points into geographic hotspots using DBSCAN.

    To keep memory usage reasonable, DBSCAN runs on a subsample of
    points (capped at *max_cluster_points*). The full coordinate set is
    then assigned to the nearest cluster centre so that bboxes and
    counts reflect all data.

    Returns a list of dicts with: center, bbox, count, location,
    est_runs, est_km.
    """
    coords = np.array(coordinates)
    total_points = len(coords)

    # Subsample for DBSCAN to avoid O(n^2) memory on large datasets
    if len(coords) > max_cluster_points:
        rng = np.random.default_rng(42)
        sample_idx = rng.choice(len(coords), max_cluster_points, replace=False)
        sample = coords[sample_idx]
    else:
        sample = coords

    lats, lons = sample[:, 0], sample[:, 1]

    # Equirectangular projection to approximate km
    mean_lat = np.mean(lats)
    cos_lat = math.cos(math.radians(mean_lat))
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * cos_lat

    scaled = np.column_stack([lats * km_per_deg_lat, lons * km_per_deg_lon])

    # Scale min_samples proportionally when subsampled
    scale_factor = len(sample) / len(coords)
    adjusted_min_samples = max(5, int(min_samples * scale_factor))

    db = DBSCAN(eps=eps_km, min_samples=adjusted_min_samples).fit(scaled)
    labels = db.labels_

    unique_labels = set(labels) - {-1}
    if not unique_labels:
        logger.warning("DBSCAN found no clusters; treating all points as one cluster")
        unique_labels = {0}
        labels = np.zeros(len(sample), dtype=int)

    # Compute cluster centres from the sample
    centres = []
    for label in sorted(unique_labels):
        mask = labels == label
        pts = sample[mask]
        centres.append(np.mean(pts, axis=0))
    centres = np.array(centres)

    # Assign ALL points to nearest cluster centre
    all_lats, all_lons = coords[:, 0], coords[:, 1]
    all_scaled = np.column_stack([all_lats * km_per_deg_lat, all_lons * km_per_deg_lon])
    centres_scaled = np.column_stack([
        centres[:, 0] * km_per_deg_lat,
        centres[:, 1] * km_per_deg_lon,
    ])

    chunk_size = 50_000
    full_labels = np.empty(len(coords), dtype=int)
    for start in range(0, len(coords), chunk_size):
        end = min(start + chunk_size, len(coords))
        diffs = all_scaled[start:end, np.newaxis, :] - centres_scaled[np.newaxis, :, :]
        dists = np.sum(diffs ** 2, axis=2)
        full_labels[start:end] = np.argmin(dists, axis=1)

    clusters = []
    for i, label in enumerate(sorted(unique_labels)):
        mask = full_labels == i
        pts = coords[mask]
        count = int(mask.sum())
        center = (float(centres[i][0]), float(centres[i][1]))
        lat_min, lon_min = pts.min(axis=0)
        lat_max, lon_max = pts.max(axis=0)

        fraction = count / total_points if total_points > 0 else 0
        est_runs = max(1, round(total_activities * fraction))
        est_km = total_distance_km * fraction

        clusters.append({
            'center': center,
            'bbox': (float(lat_min), float(lat_max), float(lon_min), float(lon_max)),
            'count': count,
            'est_runs': est_runs,
            'est_km': est_km,
        })

    # Select top N BEFORE geocoding to avoid rate limits
    clusters.sort(key=lambda c: c['count'], reverse=True)
    clusters = clusters[:n_hotspots]

    # Reverse geocode only the selected clusters (with 1s delay for Nominatim)
    for i, cluster in enumerate(clusters):
        if i > 0:
            time.sleep(1.1)
        location = _reverse_geocode(cluster['center'][0], cluster['center'][1])
        cluster['location'] = location
        logger.info(
            f"Hotspot {i+1}: {location} "
            f"({cluster['count']:,} pts, ~{cluster['est_runs']} runs, ~{cluster['est_km']:.0f} km)"
        )

    # Fallback: if fewer clusters than panels, fill with wider zoom views
    while len(clusters) < n_hotspots and clusters:
        base = clusters[0]
        lat_min, lat_max, lon_min, lon_max = base['bbox']
        lat_range = lat_max - lat_min
        lon_range = lon_max - lon_min
        padding = 0.3 * len(clusters)
        wider_bbox = (
            lat_min - lat_range * padding,
            lat_max + lat_range * padding,
            lon_min - lon_range * padding,
            lon_max + lon_range * padding,
        )
        clusters.append({
            'center': base['center'],
            'bbox': wider_bbox,
            'count': base['count'],
            'location': base['location'] + ' (wide)',
            'est_runs': base['est_runs'],
            'est_km': base['est_km'],
        })

    return clusters


def render_hotspot_panel(
    ax: plt.Axes,
    points_mercator: Tuple[np.ndarray, np.ndarray],
    bbox_mercator: Tuple[float, float, float, float],
    title: str,
    subtitle: str = '',
    grid_size: int = 600,
    sigma: float = 1.2,
) -> None:
    """Render a single heatmap panel onto the given axes."""
    x, y = points_mercator
    x_min, x_max, y_min, y_max = bbox_mercator

    # 2D histogram on a fine grid for sharp route outlines
    hist, xedges, yedges = np.histogram2d(
        x, y, bins=grid_size, range=[[x_min, x_max], [y_min, y_max]]
    )

    # Light smoothing — just enough to connect adjacent GPS points
    hist = gaussian_filter(hist.T, sigma=sigma)

    # Log-scale normalisation for good contrast
    max_val = hist.max()
    if max_val > 0:
        hist_norm = np.log1p(hist) / np.log1p(max_val)
    else:
        hist_norm = hist

    # Build RGBA: apply colormap then vectorised alpha interpolation
    rgba = HEATMAP_CMAP(hist_norm)
    rgba[..., 3] = np.interp(hist_norm, _CMAP_POSITIONS, _CMAP_ALPHAS)

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)

    # Layer 1: Colorful basemap (Voyager — streets, water, parks in colour)
    try:
        lon_w = x_min * 180.0 / 20037508.34
        lon_e = x_max * 180.0 / 20037508.34
        lat_s = math.degrees(2 * math.atan(math.exp(y_min * math.pi / 20037508.34)) - math.pi / 2)
        lat_n = math.degrees(2 * math.atan(math.exp(y_max * math.pi / 20037508.34)) - math.pi / 2)
        auto_zoom = cx.tile._calculate_zoom(lon_w, lat_s, lon_e, lat_n)
        tile_zoom = min(auto_zoom + 1, 16)
        cx.add_basemap(
            ax,
            crs='EPSG:3857',
            source=cx.providers.CartoDB.Voyager,
            zoom=tile_zoom,
            zorder=1,
        )
    except Exception as e:
        logger.warning(f"Could not fetch basemap tiles: {e}")

    # Layer 2: Semi-transparent dark veil — dims the basemap so the
    # heatmap pops, while keeping geography (water, parks, labels) visible
    from matplotlib.patches import Rectangle
    veil = Rectangle(
        (x_min, y_min), x_max - x_min, y_max - y_min,
        facecolor='#0a0a2e', alpha=0.45, zorder=2,
    )
    ax.add_patch(veil)

    # Layer 3: Heatmap overlay
    ax.imshow(
        rgba,
        extent=[x_min, x_max, y_min, y_max],
        origin='lower',
        aspect='auto',
        zorder=3,
        interpolation='bilinear',
    )

    # Title and subtitle (white text on dark background)
    # Increase pad to make room for subtitle between title and map
    ax.set_title(
        title, color='white', fontsize=16, fontweight='bold', pad=30,
        fontfamily='sans-serif',
    )
    if subtitle:
        ax.text(
            0.5, 1.01, subtitle,
            transform=ax.transAxes, ha='center', va='bottom',
            fontsize=13, color='#ffb347', fontweight='bold',
            fontfamily='sans-serif',
        )

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor('#444444')
        spine.set_linewidth(1.5)


# Layout presets: (rows, cols, figsize)
_LAYOUT_PRESETS = {
    1: (1, 1, (12, 12)),
    2: (1, 2, (20, 12)),
    4: (2, 2, (16, 16)),
}


def create_static_heatmap(
    coordinates: List[Tuple[float, float]],
    output_path: str = 'heatmap_export.png',
    n_panels: int = 2,
    layout: Optional[Tuple[int, int]] = None,
    figsize: Optional[Tuple[int, int]] = None,
    dpi: int = 250,
    fmt: str = 'png',
    title: str = 'Where I Run',
    eps_km: float = 2.0,
    min_samples: int = 50,
    sigma: float = 1.2,
    total_activities: int = 0,
    total_distance_km: float = 0.0,
) -> str:
    """Generate a multi-panel static heatmap image.

    Args:
        n_panels: Number of hotspot panels (1, 2, or 4).

    Returns the path to the saved image.
    """
    preset = _LAYOUT_PRESETS.get(n_panels)
    if preset is not None:
        default_rows, default_cols, default_figsize = preset
    else:
        default_cols = math.ceil(math.sqrt(n_panels))
        default_rows = math.ceil(n_panels / default_cols)
        default_figsize = (16, 16)

    if layout is None:
        layout = (default_rows, default_cols)
    if figsize is None:
        figsize = default_figsize

    logger.info(f"Detecting hotspots (eps_km={eps_km}, min_samples={min_samples})...")
    hotspots = detect_hotspots(
        coordinates, n_hotspots=n_panels, eps_km=eps_km, min_samples=min_samples,
        total_activities=total_activities, total_distance_km=total_distance_km,
    )

    # Convert all points to Mercator once
    all_coords = np.array(coordinates)
    all_x, all_y = latlon_array_to_mercator(all_coords[:, 0], all_coords[:, 1])

    bg_color = '#1a1a2e'
    fig, axes = plt.subplots(
        layout[0], layout[1], figsize=figsize,
        facecolor=bg_color,
    )
    if n_panels == 1:
        axes = np.array([axes])
    axes = np.atleast_1d(axes).flatten()

    for i, hotspot in enumerate(hotspots):
        ax = axes[i]
        ax.set_facecolor(bg_color)

        lat_min, lat_max, lon_min, lon_max = hotspot['bbox']

        # Add 15% padding so routes aren't clipped at edges
        lat_pad = (lat_max - lat_min) * 0.15
        lon_pad = (lon_max - lon_min) * 0.15
        lat_min -= lat_pad
        lat_max += lat_pad
        lon_min -= lon_pad
        lon_max += lon_pad

        # Convert bbox to Mercator
        bbox_x, bbox_y = latlon_array_to_mercator(
            np.array([lat_min, lat_max]),
            np.array([lon_min, lon_max]),
        )
        bbox_mercator = (bbox_x[0], bbox_x[1], bbox_y[0], bbox_y[1])

        # Filter points within bbox
        mask = (
            (all_x >= bbox_mercator[0]) & (all_x <= bbox_mercator[1]) &
            (all_y >= bbox_mercator[2]) & (all_y <= bbox_mercator[3])
        )
        panel_x, panel_y = all_x[mask], all_y[mask]

        panel_title = hotspot['location']
        subtitle = f"{hotspot['est_runs']} runs  |  {hotspot['est_km']:,.0f} km"

        render_hotspot_panel(
            ax, (panel_x, panel_y), bbox_mercator,
            title=panel_title, subtitle=subtitle, sigma=sigma,
        )

    # Hide extra axes
    for j in range(len(hotspots), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle(
        title, color='white', fontsize=26, fontweight='bold', y=0.96,
        fontfamily='sans-serif',
    )

    # Summary line — all activities, not just displayed clusters
    summary_parts = []
    if total_activities:
        summary_parts.append(f'{total_activities} runs')
    if total_distance_km > 0:
        summary_parts.append(f'{total_distance_km:,.0f} km')
    summary_parts.append(f'{len(coordinates):,} GPS points')
    summary = '  |  '.join(summary_parts)
    fig.text(
        0.5, 0.928, summary,
        ha='center', va='top', fontsize=14, color='#ffb347',
        fontweight='bold', fontfamily='sans-serif',
    )

    fig.tight_layout(rect=[0.01, 0.01, 0.99, 0.93], h_pad=0.5, w_pad=2.0)

    fig.savefig(output_path, dpi=dpi, format=fmt, facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"Saved static heatmap to {output_path}")
    return output_path


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Export a static heatmap image of Strava activities')
    ap.add_argument('--data-dir', default='./data/activities', help='Path to Strava activity files')
    ap.add_argument('--output', '-o', default='heatmap_export.png', help='Output file path')
    ap.add_argument('--panels', type=int, default=2, choices=[1, 2, 4],
                    help='Number of hotspot panels (default: 2)')
    ap.add_argument('--format', choices=['png', 'jpeg'], default='png', help='Image format')
    ap.add_argument('--dpi', type=int, default=250, help='Image DPI')
    ap.add_argument('--eps-km', type=float, default=2.0, help='DBSCAN eps in km')
    ap.add_argument('--min-samples', type=int, default=50, help='DBSCAN min_samples')
    args = ap.parse_args()

    cache = CoordinateCache()
    cache_data = cache.get(args.data_dir)

    if cache_data is not None:
        logger.info(f"Using cached data with {len(cache_data['coordinates']):,} coordinates")
        coordinates = cache_data['coordinates']
        activities = cache_data.get('activities', [])
    else:
        logger.info("Parsing activity files...")
        parser = StravaDataParser(args.data_dir)
        coordinates = parser.parse_all_activities()
        activities = parser.activities
        if coordinates:
            cache.set(args.data_dir, coordinates, parser.activities, parser._file_counts)

    if not coordinates:
        logger.error("No coordinates found. Check your --data-dir path.")
        raise SystemExit(1)

    total_activities = len(activities)
    total_distance_km = sum(a.get('distance_m', 0) for a in activities) / 1000.0

    create_static_heatmap(
        coordinates,
        output_path=args.output,
        n_panels=args.panels,
        dpi=args.dpi,
        fmt=args.format,
        eps_km=args.eps_km,
        min_samples=args.min_samples,
        total_activities=total_activities,
        total_distance_km=total_distance_km,
    )
