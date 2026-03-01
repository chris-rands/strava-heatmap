"""
Static heatmap export: generates a multi-panel PNG/JPEG showing
running hotspots with dark basemap and heatmap overlay.
"""

import argparse
import logging
import math
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
from sklearn.cluster import DBSCAN
from scipy.ndimage import gaussian_filter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import contextily as cx

from parser import StravaDataParser
from cache import CoordinateCache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def latlon_array_to_mercator(
    lats: np.ndarray, lons: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert lat/lon arrays to EPSG:3857 (Web Mercator) coordinates.

    Pure numpy math, no pyproj dependency needed.
    """
    x = lons * 20037508.34 / 180.0
    y = np.log(np.tan((90.0 + lats) * math.pi / 360.0)) / (math.pi / 180.0)
    y = y * 20037508.34 / 180.0
    return x, y


def detect_hotspots(
    coordinates: List[Tuple[float, float]],
    n_hotspots: int = 4,
    eps_km: float = 2.0,
    min_samples: int = 50,
) -> list:
    """Cluster GPS points into geographic hotspots using DBSCAN.

    Returns a list of dicts, each with keys: center, points, bbox.
    """
    coords = np.array(coordinates)
    lats, lons = coords[:, 0], coords[:, 1]

    # Equirectangular projection to approximate km
    mean_lat = np.mean(lats)
    cos_lat = math.cos(math.radians(mean_lat))
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * cos_lat

    scaled = np.column_stack([lats * km_per_deg_lat, lons * km_per_deg_lon])

    db = DBSCAN(eps=eps_km, min_samples=min_samples).fit(scaled)
    labels = db.labels_

    unique_labels = set(labels) - {-1}
    if not unique_labels:
        logger.warning("DBSCAN found no clusters; treating all points as one cluster")
        unique_labels = {0}
        labels = np.zeros(len(coords), dtype=int)

    clusters = []
    for label in unique_labels:
        mask = labels == label
        pts = coords[mask]
        center = (np.mean(pts[:, 0]), np.mean(pts[:, 1]))
        lat_min, lon_min = pts.min(axis=0)
        lat_max, lon_max = pts.max(axis=0)
        clusters.append({
            'center': center,
            'points': pts,
            'bbox': (lat_min, lat_max, lon_min, lon_max),
            'count': len(pts),
        })

    # Sort by point count descending, take top N
    clusters.sort(key=lambda c: c['count'], reverse=True)
    clusters = clusters[:n_hotspots]

    # Fallback: if fewer clusters than panels, fill with wider zoom views
    # of the largest cluster
    while len(clusters) < n_hotspots and clusters:
        base = clusters[0]
        lat_min, lat_max, lon_min, lon_max = base['bbox']
        lat_range = lat_max - lat_min
        lon_range = lon_max - lon_min
        padding = 0.3 * len(clusters)  # progressively wider
        wider_bbox = (
            lat_min - lat_range * padding,
            lat_max + lat_range * padding,
            lon_min - lon_range * padding,
            lon_max + lon_range * padding,
        )
        clusters.append({
            'center': base['center'],
            'points': base['points'],
            'bbox': wider_bbox,
            'count': base['count'],
        })

    return clusters


def render_hotspot_panel(
    ax: plt.Axes,
    points_mercator: Tuple[np.ndarray, np.ndarray],
    bbox_mercator: Tuple[float, float, float, float],
    title: str,
    cmap: str = 'hot',
    grid_size: int = 200,
    sigma: float = 3.0,
) -> None:
    """Render a single heatmap panel onto the given axes."""
    x, y = points_mercator
    x_min, x_max, y_min, y_max = bbox_mercator

    # 2D histogram
    hist, xedges, yedges = np.histogram2d(
        x, y, bins=grid_size, range=[[x_min, x_max], [y_min, y_max]]
    )

    # Smooth
    hist = gaussian_filter(hist.T, sigma=sigma)

    # Mask zeros for transparency
    hist_masked = np.ma.masked_where(hist == 0, hist)

    ax.imshow(
        hist_masked,
        extent=[x_min, x_max, y_min, y_max],
        origin='lower',
        cmap=cmap,
        alpha=0.7,
        aspect='auto',
        zorder=2,
    )

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)

    # Add basemap tiles
    try:
        cx.add_basemap(
            ax,
            crs='EPSG:3857',
            source=cx.providers.CartoDB.DarkMatter,
            zoom='auto',
            zorder=1,
        )
    except Exception as e:
        logger.warning(f"Could not fetch basemap tiles: {e}")
        ax.set_facecolor('#1a1a2e')

    ax.set_title(title, color='white', fontsize=12, fontweight='bold', pad=8)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def create_static_heatmap(
    coordinates: List[Tuple[float, float]],
    output_path: str = 'heatmap_export.png',
    n_panels: int = 4,
    layout: Optional[Tuple[int, int]] = None,
    figsize: Tuple[int, int] = (16, 16),
    dpi: int = 200,
    fmt: str = 'png',
    title: str = 'Running Hotspots',
    eps_km: float = 2.0,
    min_samples: int = 50,
    cmap: str = 'hot',
    sigma: float = 3.0,
) -> str:
    """Generate a multi-panel static heatmap image.

    Returns the path to the saved image.
    """
    if layout is None:
        cols = math.ceil(math.sqrt(n_panels))
        rows = math.ceil(n_panels / cols)
        layout = (rows, cols)

    logger.info(f"Detecting hotspots (eps_km={eps_km}, min_samples={min_samples})...")
    hotspots = detect_hotspots(
        coordinates, n_hotspots=n_panels, eps_km=eps_km, min_samples=min_samples
    )

    # Convert all points to Mercator once
    all_coords = np.array(coordinates)
    all_x, all_y = latlon_array_to_mercator(all_coords[:, 0], all_coords[:, 1])

    fig, axes = plt.subplots(
        layout[0], layout[1], figsize=figsize,
        facecolor='#1a1a2e',
    )
    if n_panels == 1:
        axes = np.array([axes])
    axes = axes.flatten()

    for i, hotspot in enumerate(hotspots):
        ax = axes[i]
        ax.set_facecolor('#1a1a2e')

        lat_min, lat_max, lon_min, lon_max = hotspot['bbox']

        # Add 10% padding
        lat_pad = (lat_max - lat_min) * 0.1
        lon_pad = (lon_max - lon_min) * 0.1
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

        panel_title = f"Hotspot {i + 1} ({hotspot['count']:,} points)"

        render_hotspot_panel(
            ax, (panel_x, panel_y), bbox_mercator,
            title=panel_title, cmap=cmap, sigma=sigma,
        )

    # Hide extra axes
    for j in range(len(hotspots), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle(title, color='white', fontsize=20, fontweight='bold', y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    fig.savefig(output_path, dpi=dpi, format=fmt, facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"Saved static heatmap to {output_path}")
    return output_path


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Export a static heatmap image of Strava activities')
    ap.add_argument('--data-dir', default='./data/activities', help='Path to Strava activity files')
    ap.add_argument('--output', '-o', default='heatmap_export.png', help='Output file path')
    ap.add_argument('--panels', type=int, default=4, help='Number of hotspot panels')
    ap.add_argument('--format', choices=['png', 'jpeg'], default='png', help='Image format')
    ap.add_argument('--dpi', type=int, default=200, help='Image DPI')
    ap.add_argument('--eps-km', type=float, default=2.0, help='DBSCAN eps in km')
    ap.add_argument('--min-samples', type=int, default=50, help='DBSCAN min_samples')
    ap.add_argument('--cmap', default='hot', help='Matplotlib colormap name')
    args = ap.parse_args()

    cache = CoordinateCache()
    cache_data = cache.get(args.data_dir)

    if cache_data is not None:
        logger.info(f"Using cached data with {len(cache_data['coordinates']):,} coordinates")
        coordinates = cache_data['coordinates']
    else:
        logger.info("Parsing activity files...")
        parser = StravaDataParser(args.data_dir)
        coordinates = parser.parse_all_activities()
        if coordinates:
            cache.set(args.data_dir, coordinates, parser.activities, parser._file_counts)

    if not coordinates:
        logger.error("No coordinates found. Check your --data-dir path.")
        raise SystemExit(1)

    create_static_heatmap(
        coordinates,
        output_path=args.output,
        n_panels=args.panels,
        dpi=args.dpi,
        fmt=args.format,
        eps_km=args.eps_km,
        min_samples=args.min_samples,
        cmap=args.cmap,
    )
