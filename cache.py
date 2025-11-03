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
        """Generate cache key based on directory path and file count."""
        data_path = Path(data_directory)

        # Get file counts and timestamps
        gpx_files = list(data_path.rglob("*.gpx"))
        fit_files = list(data_path.rglob("*.fit"))
        fit_gz_files = list(data_path.rglob("*.fit.gz"))

        all_files = gpx_files + fit_files + fit_gz_files

        # Create key from path, file count, and latest modification time
        file_count = len(all_files)
        latest_mtime = max((f.stat().st_mtime for f in all_files), default=0)

        key_string = f"{data_directory}_{file_count}_{latest_mtime}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, data_directory: str) -> Optional[List[Tuple[float, float]]]:
        """Retrieve cached coordinates if available."""
        cache_key = self._get_cache_key(data_directory)
        cache_file = self.cache_dir / f"{cache_key}.pkl"

        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    coords = pickle.load(f)
                logger.info(f"Loaded {len(coords):,} coordinates from cache")
                return coords
            except Exception as e:
                logger.error(f"Error loading cache: {e}")
                return None

        return None

    def set(self, data_directory: str, coordinates: List[Tuple[float, float]]) -> None:
        """Save coordinates to cache."""
        cache_key = self._get_cache_key(data_directory)
        cache_file = self.cache_dir / f"{cache_key}.pkl"

        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(coordinates, f)
            logger.info(f"Saved {len(coordinates):,} coordinates to cache")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")

    def clear(self) -> None:
        """Clear all cached files."""
        for cache_file in self.cache_dir.glob("*.pkl"):
            cache_file.unlink()
        logger.info("Cache cleared")
