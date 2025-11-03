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

                for track in gpx.tracks:
                    for segment in track.segments:
                        for point in segment.points:
                            coords.append((point.latitude, point.longitude))

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

    def parse_all_activities(self) -> List[Tuple[float, float]]:
        """
        Parse all activity files in the data directory.

        Returns:
            List of all (latitude, longitude) tuples from all activities
        """
        all_coords = []

        if not self.data_directory.exists():
            logger.error(f"Data directory does not exist: {self.data_directory}")
            return all_coords

        # Find all activity files
        gpx_files = list(self.data_directory.rglob("*.gpx"))
        fit_files = list(self.data_directory.rglob("*.fit"))
        fit_gz_files = list(self.data_directory.rglob("*.fit.gz"))
        tcx_files = list(self.data_directory.rglob("*.tcx"))

        total_fit = len(fit_files) + len(fit_gz_files)
        logger.info(f"Found {len(gpx_files)} GPX, {total_fit} FIT ({len(fit_files)} .fit, {len(fit_gz_files)} .fit.gz), {len(tcx_files)} TCX files")

        # Parse GPX files
        for gpx_file in gpx_files:
            coords = self.parse_gpx_file(gpx_file)
            all_coords.extend(coords)

        # Parse FIT files
        for fit_file in fit_files:
            coords = self.parse_fit_file(fit_file)
            all_coords.extend(coords)

        # Parse compressed FIT files
        for fit_file in fit_gz_files:
            coords = self.parse_fit_file(fit_file)
            all_coords.extend(coords)

        # Parse TCX files
        for tcx_file in tcx_files:
            coords = self.parse_tcx_file(tcx_file)
            all_coords.extend(coords)

        logger.info(f"Total coordinates extracted: {len(all_coords)}")
        self.coordinates = all_coords

        return all_coords

    def get_activity_stats(self) -> Dict[str, int]:
        """
        Get statistics about parsed activities.

        Returns:
            Dictionary with activity counts and coordinate count
        """
        gpx_count = len(list(self.data_directory.rglob("*.gpx")))
        fit_count = len(list(self.data_directory.rglob("*.fit")))
        fit_gz_count = len(list(self.data_directory.rglob("*.fit.gz")))
        tcx_count = len(list(self.data_directory.rglob("*.tcx")))

        total_fit = fit_count + fit_gz_count

        return {
            'gpx_files': gpx_count,
            'fit_files': total_fit,
            'tcx_files': tcx_count,
            'total_activities': gpx_count + total_fit + tcx_count,
            'total_coordinates': len(self.coordinates)
        }
