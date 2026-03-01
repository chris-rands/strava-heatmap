"""Simple caching module to avoid re-parsing activity files."""

import pickle
import hashlib
from pathlib import Path
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class CoordinateCache:
    """Cache parsed coordinates to disk."""

    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _get_cache_key(self, data_directory: str) -> str:
        """Generate cache key based on directory path, file count, and directory mtime.

        Uses a single stat() on the directory instead of scanning every file.
        Adding or removing a file changes both the count and the directory mtime.
        """
        data_path = Path(data_directory)

        # Count activity files with a single directory walk
        supported = {'.gpx', '.fit', '.tcx'}
        file_count = 0
        for entry in data_path.rglob("*"):
            if not entry.is_file():
                continue
            if entry.suffix.lower() in supported or entry.name.lower().endswith('.fit.gz'):
                file_count += 1

        # Directory mtime changes when files are added/removed
        dir_mtime = data_path.stat().st_mtime

        key_string = f"{data_directory}_{file_count}_{dir_mtime}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, data_directory: str) -> Optional[dict]:
        """Retrieve cached data if available."""
        cache_key = self._get_cache_key(data_directory)
        cache_file = self.cache_dir / f"{cache_key}.pkl"

        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cache_data = pickle.load(f)

                # Handle old cache format (just coordinates)
                if isinstance(cache_data, list):
                    logger.info(f"Loaded {len(cache_data):,} coordinates from cache (old format)")
                    return {'coordinates': cache_data, 'activities': []}

                # New format with activities
                logger.info(f"Loaded {len(cache_data.get('coordinates', [])):,} coordinates and {len(cache_data.get('activities', []))} activities from cache")
                return cache_data
            except Exception as e:
                logger.error(f"Error loading cache: {e}")
                return None

        return None

    def set(self, data_directory: str, coordinates: List[Tuple[float, float]], activities: list = None, file_counts: dict = None) -> None:
        """Save coordinates, activities, and file counts to cache."""
        cache_key = self._get_cache_key(data_directory)
        cache_file = self.cache_dir / f"{cache_key}.pkl"

        try:
            cache_data = {
                'coordinates': coordinates,
                'activities': activities or [],
                'file_counts': file_counts
            }
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            logger.info(f"Saved {len(coordinates):,} coordinates and {len(activities or [])} activities to cache")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def clear(self) -> None:
        """Clear all cached files."""
        for cache_file in self.cache_dir.glob("*.pkl"):
            cache_file.unlink()
        logger.info("Cache cleared")
