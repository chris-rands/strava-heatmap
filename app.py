"""
Flask web application for Strava activity heatmap.
"""

from flask import Flask, render_template, request, redirect, url_for, flash
from parser import StravaDataParser
from heatmap import StravaHeatmap
from cache import CoordinateCache
import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize cache
cache = CoordinateCache()

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

# Configuration
DATA_DIR = os.getenv('STRAVA_DATA_DIR', './data/activities')


@app.route('/')
def index():
    """Home page."""
    return render_template('index.html', data_dir=DATA_DIR)


@app.route('/heatmap')
def heatmap():
    """Generate and display heatmap."""
    data_dir = request.args.get('data_dir', DATA_DIR)

    if not os.path.exists(data_dir):
        flash(f'Data directory not found: {data_dir}', 'error')
        return redirect(url_for('index'))

    try:
        # Check cache first
        coordinates = cache.get(data_dir)

        if coordinates is None:
            # Parse activities if not cached
            logger.info("No cache found, parsing all activities...")
            parser = StravaDataParser(data_dir)
            coordinates = parser.parse_all_activities()

            if not coordinates:
                flash('No activity data found in the directory', 'warning')
                return redirect(url_for('index'))

            # Save to cache
            cache.set(data_dir, coordinates)
        else:
            logger.info(f"Using cached data with {len(coordinates):,} coordinates")
            # Still need parser for stats
            parser = StravaDataParser(data_dir)
            parser.coordinates = coordinates

        # Get stats
        stats = parser.get_activity_stats()

        # Create heatmap
        heatmap_obj = StravaHeatmap(coordinates)
        map_obj = heatmap_obj.create_heatmap()

        # Save to templates directory
        map_html = map_obj._repr_html_()

        return render_template(
            'heatmap.html',
            map_html=map_html,
            stats=stats
        )

    except Exception as e:
        logger.error(f"Error generating heatmap: {e}")
        flash(f'Error generating heatmap: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/stats')
def stats():
    """Display activity statistics."""
    data_dir = request.args.get('data_dir', DATA_DIR)

    if not os.path.exists(data_dir):
        flash(f'Data directory not found: {data_dir}', 'error')
        return redirect(url_for('index'))

    try:
        # Check cache first
        coordinates = cache.get(data_dir)

        if coordinates is None:
            # Parse if not cached
            logger.info("No cache found, parsing all activities...")
            parser = StravaDataParser(data_dir)
            coordinates = parser.parse_all_activities()
            cache.set(data_dir, coordinates)
        else:
            logger.info(f"Using cached data")
            parser = StravaDataParser(data_dir)
            parser.coordinates = coordinates

        stats = parser.get_activity_stats()
        return render_template('stats.html', stats=stats)

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        flash(f'Error getting stats: {str(e)}', 'error')
        return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
