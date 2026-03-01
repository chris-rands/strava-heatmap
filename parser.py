"""
Parser module for Strava activity data.
Supports GPX, FIT, and TCX file formats.
"""

import math

import gpxpy
import gpxpy.gpx
from fitparse import FitFile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import gzip

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StravaDataParser:
    """Parse Strava export data files."""

    def __init__(self, data_directory: str, min_distance_m: float = 10.0):
        """
        Initialize parser with data directory.

        Args:
            data_directory: Path to directory containing Strava export files
            min_distance_m: Minimum distance in metres between kept GPS points.
                            Points closer than this to the previous kept point
                            are dropped. Set to 0 to keep all points.
        """
        self.data_directory = Path(data_directory)
        self.min_distance_m = min_distance_m
        self.coordinates = []
        self.activities = []  # Store activity metadata
        self._file_counts = None  # Cache file counts to avoid rescanning

    @staticmethod
    def _downsample(coords: List[Tuple[float, float]], min_distance_m: float) -> List[Tuple[float, float]]:
        """Drop points that are within *min_distance_m* of the previous kept point.

        Uses a fast equirectangular approximation (good enough for short distances).
        """
        if min_distance_m <= 0 or len(coords) <= 1:
            return coords

        kept = [coords[0]]
        prev_lat, prev_lon = coords[0]
        threshold_sq = min_distance_m ** 2

        m_per_deg_lat = 111_320.0
        cos_lat = math.cos(math.radians(prev_lat))
        m_per_deg_lon = m_per_deg_lat * cos_lat

        for lat, lon in coords[1:]:
            dlat = (lat - prev_lat) * m_per_deg_lat
            dlon = (lon - prev_lon) * m_per_deg_lon
            if dlat * dlat + dlon * dlon >= threshold_sq:
                kept.append((lat, lon))
                prev_lat, prev_lon = lat, lon

        return kept

    def _finalize_coords(self, coords: List[Tuple[float, float]], file_path: Path,
                         file_type: str, distance_m: float = 0, duration_s: float = 0
                         ) -> Tuple[List[Tuple[float, float]], dict]:
        """Downsample coordinates, build activity metadata, and log."""
        raw_count = len(coords)
        coords = self._downsample(coords, self.min_distance_m)
        activity = {
            'filename': file_path.name,
            'type': file_type,
            'distance_m': distance_m,
            'duration_s': duration_s,
            'points': raw_count,
        }
        logger.info(f"Parsed {raw_count} points from {file_path.name} (kept {len(coords)} after downsampling)")
        return coords, activity

    def parse_all_activities(self, max_workers: int = 4) -> List[Tuple[float, float]]:
        """
        Parse all activity files in the data directory using parallel processing.

        Args:
            max_workers: Number of parallel threads for parsing (default 4)

        Returns:
            List of all (latitude, longitude) tuples from all activities
        """
        all_coords = []

        if not self.data_directory.exists():
            logger.error(f"Data directory does not exist: {self.data_directory}")
            return all_coords

        # Find all activity files (single scan, reuse for stats)
        gpx_files = list(self.data_directory.rglob("*.gpx"))
        fit_files = list(self.data_directory.rglob("*.fit"))
        fit_gz_files = list(self.data_directory.rglob("*.fit.gz"))
        tcx_files = list(self.data_directory.rglob("*.tcx"))

        # Cache file counts to avoid rescanning in get_activity_stats()
        self._file_counts = {
            'gpx': len(gpx_files),
            'fit': len(fit_files),
            'fit_gz': len(fit_gz_files),
            'tcx': len(tcx_files)
        }

        total_fit = len(fit_files) + len(fit_gz_files)
        logger.info(f"Found {len(gpx_files)} GPX, {total_fit} FIT ({len(fit_files)} .fit, {len(fit_gz_files)} .fit.gz), {len(tcx_files)} TCX files")

        all_files = gpx_files + fit_files + fit_gz_files + tcx_files

        # Use thread pool for I/O-bound parsing
        if len(all_files) > 10:
            # Parallel parsing for larger datasets
            self.activities = []  # Reset before parallel parsing
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self._parse_single_file, f): f for f in all_files}
                for future in as_completed(futures):
                    coords, activity = future.result()
                    all_coords.extend(coords)
                    if activity:
                        self.activities.append(activity)
        else:
            # Sequential for small datasets (less overhead)
            for f in all_files:
                coords, activity = self._parse_single_file(f)
                all_coords.extend(coords)
                if activity:
                    self.activities.append(activity)

        logger.info(f"Total coordinates extracted: {len(all_coords)}")
        self.coordinates = all_coords

        return all_coords

    def _parse_single_file(self, file_path: Path) -> Tuple[List[Tuple[float, float]], dict]:
        """Parse a single file in isolation (thread-safe)."""
        suffix = file_path.suffix.lower()
        coords = []
        activity = None

        try:
            if suffix == '.gpx':
                coords, activity = self._parse_gpx_isolated(file_path)
            elif suffix == '.fit' or str(file_path).endswith('.fit.gz'):
                coords, activity = self._parse_fit_isolated(file_path)
            elif suffix == '.tcx':
                coords, activity = self._parse_tcx_isolated(file_path)
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")

        return coords, activity

    def _parse_gpx_isolated(self, file_path: Path) -> Tuple[List[Tuple[float, float]], dict]:
        """Thread-safe GPX parsing."""
        coords = []
        with open(file_path, 'r') as gpx_file:
            gpx = gpxpy.parse(gpx_file)
            for track in gpx.tracks:
                for segment in track.segments:
                    for point in segment.points:
                        coords.append((point.latitude, point.longitude))

            length_3d = gpx.length_3d()
            total_distance = length_3d if length_3d else gpx.length_2d()
            total_duration = 0
            time_bounds = gpx.get_time_bounds()
            if time_bounds.start_time and time_bounds.end_time:
                total_duration = (time_bounds.end_time - time_bounds.start_time).total_seconds()

        return self._finalize_coords(coords, file_path, 'gpx', total_distance, total_duration)

    def _parse_fit_isolated(self, file_path: Path) -> Tuple[List[Tuple[float, float]], dict]:
        """Thread-safe FIT parsing."""
        if str(file_path).endswith('.gz'):
            with gzip.open(file_path, 'rb') as f:
                fitfile = FitFile(f)
                coords, total_distance, total_duration = self._extract_fit_data(fitfile)
        else:
            fitfile = FitFile(str(file_path))
            coords, total_distance, total_duration = self._extract_fit_data(fitfile)

        return self._finalize_coords(coords, file_path, 'fit', total_distance, total_duration)

    def _extract_fit_data(self, fitfile: FitFile) -> Tuple[List[Tuple[float, float]], float, float]:
        """Extract coords and metadata from FIT file."""
        coords = []
        total_distance = 0
        total_duration = 0

        for session in fitfile.get_messages('session'):
            for data in session:
                if data.name == 'total_distance':
                    total_distance = data.value if data.value else 0
                elif data.name == 'total_elapsed_time':
                    total_duration = data.value if data.value else 0

        for record in fitfile.get_messages('record'):
            lat = None
            lon = None
            for data in record:
                if data.name == 'position_lat':
                    lat = data.value
                elif data.name == 'position_long':
                    lon = data.value
            if lat is not None and lon is not None:
                lat_deg = lat * (180 / 2**31)
                lon_deg = lon * (180 / 2**31)
                coords.append((lat_deg, lon_deg))

        return coords, total_distance, total_duration

    def _parse_tcx_isolated(self, file_path: Path) -> Tuple[List[Tuple[float, float]], dict]:
        """Thread-safe TCX parsing."""
        coords = []
        tree = ET.parse(file_path)
        root = tree.getroot()
        ns = {'tcx': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}

        for trackpoint in root.findall('.//tcx:Trackpoint', ns):
            position = trackpoint.find('tcx:Position', ns)
            if position is not None:
                lat_elem = position.find('tcx:LatitudeDegrees', ns)
                lon_elem = position.find('tcx:LongitudeDegrees', ns)
                if lat_elem is not None and lon_elem is not None:
                    coords.append((float(lat_elem.text), float(lon_elem.text)))

        return self._finalize_coords(coords, file_path, 'tcx')

    def get_activity_stats(self) -> Dict:
        """
        Get statistics about parsed activities.

        Returns:
            Dictionary with activity counts, distances, durations, etc.
        """
        # Use cached file counts if available, otherwise scan
        if self._file_counts:
            gpx_count = self._file_counts['gpx']
            fit_count = self._file_counts['fit']
            fit_gz_count = self._file_counts['fit_gz']
            tcx_count = self._file_counts['tcx']
        else:
            gpx_count = len(list(self.data_directory.rglob("*.gpx")))
            fit_count = len(list(self.data_directory.rglob("*.fit")))
            fit_gz_count = len(list(self.data_directory.rglob("*.fit.gz")))
            tcx_count = len(list(self.data_directory.rglob("*.tcx")))

        total_fit = fit_count + fit_gz_count

        # Calculate aggregate statistics from activities
        total_distance_m = sum(a['distance_m'] for a in self.activities if a['distance_m'])
        total_duration_s = sum(a['duration_s'] for a in self.activities if a['duration_s'])

        # Calculate averages (only for activities with valid data)
        activities_with_distance = [a for a in self.activities if a['distance_m'] > 0]
        activities_with_duration = [a for a in self.activities if a['duration_s'] > 0]

        avg_distance_m = total_distance_m / len(activities_with_distance) if activities_with_distance else 0
        avg_duration_s = total_duration_s / len(activities_with_duration) if activities_with_duration else 0

        # Calculate average pace (min/km) for activities with both distance and duration
        activities_with_pace = [a for a in self.activities if a['distance_m'] > 0 and a['duration_s'] > 0]
        if activities_with_pace:
            total_pace = sum((a['duration_s'] / 60) / (a['distance_m'] / 1000)
                           for a in activities_with_pace)
            avg_pace_min_per_km = total_pace / len(activities_with_pace)
        else:
            avg_pace_min_per_km = 0

        return {
            'gpx_files': gpx_count,
            'fit_files': total_fit,
            'tcx_files': tcx_count,
            'total_activities': gpx_count + total_fit + tcx_count,
            'total_coordinates': len(self.coordinates),
            'total_distance_km': total_distance_m / 1000,
            'total_distance_mi': total_distance_m / 1609.34,
            'total_duration_hours': total_duration_s / 3600,
            'avg_distance_km': avg_distance_m / 1000,
            'avg_distance_mi': avg_distance_m / 1609.34,
            'avg_duration_minutes': avg_duration_s / 60,
            'avg_pace_min_per_km': avg_pace_min_per_km,
            'avg_pace_min_per_mi': avg_pace_min_per_km * 1.60934,
            'activities_with_data': len(activities_with_distance)
        }
