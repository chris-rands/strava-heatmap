"""
Parser module for Strava activity data.
Supports GPX, FIT, and TCX file formats.
"""

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

    def __init__(self, data_directory: str):
        """
        Initialize parser with data directory.

        Args:
            data_directory: Path to directory containing Strava export files
        """
        self.data_directory = Path(data_directory)
        self.coordinates = []
        self.activities = []  # Store activity metadata
        self._file_counts = None  # Cache file counts to avoid rescanning

    def parse_gpx_file(self, file_path: Path) -> List[Tuple[float, float]]:
        """
        Parse GPX file and extract coordinates.

        Args:
            file_path: Path to GPX file

        Returns:
            List of (latitude, longitude) tuples
        """
        coords = []
        try:
            with open(file_path, 'r') as gpx_file:
                gpx = gpxpy.parse(gpx_file)

                # Extract activity metadata
                total_distance = 0
                total_duration = 0

                for track in gpx.tracks:
                    for segment in track.segments:
                        for point in segment.points:
                            coords.append((point.latitude, point.longitude))

                # Calculate distance and duration using gpxpy
                total_distance = gpx.length_3d() if gpx.length_3d() else gpx.length_2d()

                # Get time bounds
                time_bounds = gpx.get_time_bounds()
                if time_bounds.start_time and time_bounds.end_time:
                    total_duration = (time_bounds.end_time - time_bounds.start_time).total_seconds()

                # Store activity metadata
                self.activities.append({
                    'filename': file_path.name,
                    'type': 'gpx',
                    'distance_m': total_distance,
                    'duration_s': total_duration,
                    'points': len(coords)
                })

                logger.info(f"Parsed {len(coords)} points from {file_path.name}")
        except Exception as e:
            logger.error(f"Error parsing GPX file {file_path}: {e}")

        return coords

    def parse_fit_file(self, file_path: Path) -> List[Tuple[float, float]]:
        """
        Parse FIT file and extract coordinates.
        Handles both .fit and .fit.gz (compressed) files.

        Args:
            file_path: Path to FIT file

        Returns:
            List of (latitude, longitude) tuples
        """
        coords = []
        try:
            # Check if file is gzipped
            if str(file_path).endswith('.gz'):
                with gzip.open(file_path, 'rb') as f:
                    fitfile = FitFile(f)
                    coords = self._extract_fit_coordinates(fitfile, file_path.name)
            else:
                fitfile = FitFile(str(file_path))
                coords = self._extract_fit_coordinates(fitfile, file_path.name)

        except Exception as e:
            logger.error(f"Error parsing FIT file {file_path}: {e}")

        return coords

    def _extract_fit_coordinates(self, fitfile: FitFile, filename: str) -> List[Tuple[float, float]]:
        """
        Extract coordinates from a FitFile object.

        Args:
            fitfile: FitFile object
            filename: Name of the file being parsed

        Returns:
            List of (latitude, longitude) tuples
        """
        coords = []
        total_distance = 0
        total_duration = 0
        start_time = None
        end_time = None

        # Get session data for distance and duration
        for session in fitfile.get_messages('session'):
            for data in session:
                if data.name == 'total_distance':
                    total_distance = data.value if data.value else 0
                elif data.name == 'total_elapsed_time':
                    total_duration = data.value if data.value else 0
                elif data.name == 'start_time':
                    start_time = data.value
                elif data.name == 'timestamp':
                    end_time = data.value

        # Extract coordinates
        for record in fitfile.get_messages('record'):
            lat = None
            lon = None

            for data in record:
                if data.name == 'position_lat':
                    lat = data.value
                elif data.name == 'position_long':
                    lon = data.value

            if lat is not None and lon is not None:
                # Convert semicircles to degrees
                lat_deg = lat * (180 / 2**31)
                lon_deg = lon * (180 / 2**31)
                coords.append((lat_deg, lon_deg))

        # Store activity metadata
        self.activities.append({
            'filename': filename,
            'type': 'fit',
            'distance_m': total_distance,
            'duration_s': total_duration,
            'points': len(coords)
        })

        logger.info(f"Parsed {len(coords)} points from {filename}")
        return coords

    def parse_tcx_file(self, file_path: Path) -> List[Tuple[float, float]]:
        """
        Parse TCX file and extract coordinates.

        Args:
            file_path: Path to TCX file

        Returns:
            List of (latitude, longitude) tuples
        """
        coords = []
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            # TCX namespace
            ns = {'tcx': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}

            for trackpoint in root.findall('.//tcx:Trackpoint', ns):
                position = trackpoint.find('tcx:Position', ns)
                if position is not None:
                    lat_elem = position.find('tcx:LatitudeDegrees', ns)
                    lon_elem = position.find('tcx:LongitudeDegrees', ns)

                    if lat_elem is not None and lon_elem is not None:
                        lat = float(lat_elem.text)
                        lon = float(lon_elem.text)
                        coords.append((lat, lon))

            logger.info(f"Parsed {len(coords)} points from {file_path.name}")
        except Exception as e:
            logger.error(f"Error parsing TCX file {file_path}: {e}")

        return coords

    def _parse_file(self, file_path: Path) -> Tuple[List[Tuple[float, float]], dict]:
        """Parse a single file and return coords + activity metadata."""
        suffix = file_path.suffix.lower()
        if suffix == '.gpx':
            coords = self.parse_gpx_file(file_path)
        elif suffix == '.fit' or str(file_path).endswith('.fit.gz'):
            coords = self.parse_fit_file(file_path)
        elif suffix == '.tcx':
            coords = self.parse_tcx_file(file_path)
        else:
            coords = []
        # Return the last activity added (if any)
        activity = self.activities[-1] if self.activities else None
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

            total_distance = gpx.length_3d() if gpx.length_3d() else gpx.length_2d()
            total_duration = 0
            time_bounds = gpx.get_time_bounds()
            if time_bounds.start_time and time_bounds.end_time:
                total_duration = (time_bounds.end_time - time_bounds.start_time).total_seconds()

        activity = {
            'filename': file_path.name,
            'type': 'gpx',
            'distance_m': total_distance,
            'duration_s': total_duration,
            'points': len(coords)
        }
        logger.info(f"Parsed {len(coords)} points from {file_path.name}")
        return coords, activity

    def _parse_fit_isolated(self, file_path: Path) -> Tuple[List[Tuple[float, float]], dict]:
        """Thread-safe FIT parsing."""
        coords = []
        total_distance = 0
        total_duration = 0

        if str(file_path).endswith('.gz'):
            with gzip.open(file_path, 'rb') as f:
                fitfile = FitFile(f)
                coords, total_distance, total_duration = self._extract_fit_data(fitfile)
        else:
            fitfile = FitFile(str(file_path))
            coords, total_distance, total_duration = self._extract_fit_data(fitfile)

        activity = {
            'filename': file_path.name,
            'type': 'fit',
            'distance_m': total_distance,
            'duration_s': total_duration,
            'points': len(coords)
        }
        logger.info(f"Parsed {len(coords)} points from {file_path.name}")
        return coords, activity

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

        activity = {
            'filename': file_path.name,
            'type': 'tcx',
            'distance_m': 0,
            'duration_s': 0,
            'points': len(coords)
        }
        logger.info(f"Parsed {len(coords)} points from {file_path.name}")
        return coords, activity

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
