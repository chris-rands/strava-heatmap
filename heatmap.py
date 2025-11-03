"""
Heatmap visualization module for Strava activities.
"""

import folium
from folium.plugins import HeatMap
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


class StravaHeatmap:
    """Create interactive heatmap from activity coordinates."""

    def __init__(self, coordinates: List[Tuple[float, float]]):
        """
        Initialize heatmap with coordinates.

        Args:
            coordinates: List of (latitude, longitude) tuples
        """
        self.coordinates = coordinates

    def calculate_center(self) -> Tuple[float, float]:
        """
        Calculate the center point of all coordinates.

        Returns:
            (latitude, longitude) tuple of the center point
        """
        if not self.coordinates:
            return (0, 0)

        avg_lat = sum(coord[0] for coord in self.coordinates) / len(self.coordinates)
        avg_lon = sum(coord[1] for coord in self.coordinates) / len(self.coordinates)

        return (avg_lat, avg_lon)

    def create_heatmap(self, output_file: str = None) -> folium.Map:
        """
        Create an interactive heatmap.

        Args:
            output_file: Optional path to save HTML file

        Returns:
            Folium map object
        """
        if not self.coordinates:
            logger.warning("No coordinates available to create heatmap")
            # Return empty map centered on world
            return folium.Map(location=[0, 0], zoom_start=2)

        # Calculate center
        center = self.calculate_center()
        logger.info(f"Map center: {center}")

        # Create base map
        m = folium.Map(
            location=center,
            zoom_start=12,
            tiles='OpenStreetMap'
        )

        # Add tile layers
        folium.TileLayer('cartodbpositron').add_to(m)
        folium.TileLayer('cartodbdark_matter').add_to(m)

        # Create heatmap layer
        HeatMap(
            self.coordinates,
            min_opacity=0.3,
            max_val=1.0,
            radius=10,
            blur=15,
            gradient={
                0.0: 'blue',
                0.3: 'lime',
                0.5: 'yellow',
                0.7: 'orange',
                1.0: 'red'
            }
        ).add_to(m)

        # Add layer control
        folium.LayerControl().add_to(m)

        # Save to file if specified
        if output_file:
            m.save(output_file)
            logger.info(f"Heatmap saved to {output_file}")

        return m

    def create_point_map(self, output_file: str = None, sample_rate: int = 100) -> folium.Map:
        """
        Create a map with individual points (good for smaller datasets).

        Args:
            output_file: Optional path to save HTML file
            sample_rate: Only show every Nth point to avoid overcrowding

        Returns:
            Folium map object
        """
        if not self.coordinates:
            logger.warning("No coordinates available to create point map")
            return folium.Map(location=[0, 0], zoom_start=2)

        center = self.calculate_center()

        # Create base map
        m = folium.Map(location=center, zoom_start=12)

        # Add sampled points
        sampled_coords = self.coordinates[::sample_rate]
        for lat, lon in sampled_coords:
            folium.CircleMarker(
                location=[lat, lon],
                radius=2,
                color='red',
                fill=True,
                fill_opacity=0.6
            ).add_to(m)

        if output_file:
            m.save(output_file)
            logger.info(f"Point map saved to {output_file}")

        return m

    def create_route_map(self, output_file: str = None) -> folium.Map:
        """
        Create a map with routes drawn as lines.

        Args:
            output_file: Optional path to save HTML file

        Returns:
            Folium map object
        """
        if not self.coordinates:
            logger.warning("No coordinates available to create route map")
            return folium.Map(location=[0, 0], zoom_start=2)

        center = self.calculate_center()

        # Create base map
        m = folium.Map(location=center, zoom_start=12)

        # Draw polyline
        folium.PolyLine(
            self.coordinates,
            color='red',
            weight=2,
            opacity=0.7
        ).add_to(m)

        if output_file:
            m.save(output_file)
            logger.info(f"Route map saved to {output_file}")

        return m
