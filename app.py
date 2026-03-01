"""
Flask web application for Strava activity heatmap.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from parser import StravaDataParser
from heatmap import StravaHeatmap
from cache import CoordinateCache
import os
import tempfile
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize cache
cache = CoordinateCache()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# Configuration
DATA_DIR = os.getenv('STRAVA_DATA_DIR', './data/activities')


def _load_or_parse(data_dir: str):
    """Load coordinates from cache or parse activity files.

    Returns:
        Tuple of (parser, coordinates) where parser has activities/stats populated.
    """
    cache_data = cache.get(data_dir)

    if cache_data is None:
        logger.info("No cache found, parsing all activities...")
        parser = StravaDataParser(data_dir)
        coordinates = parser.parse_all_activities()
        if coordinates:
            cache.set(data_dir, coordinates, parser.activities, parser._file_counts)
    else:
        logger.info(f"Using cached data with {len(cache_data['coordinates']):,} coordinates")
        parser = StravaDataParser(data_dir)
        parser.coordinates = cache_data['coordinates']
        parser.activities = cache_data['activities']
        parser._file_counts = cache_data.get('file_counts')
        coordinates = cache_data['coordinates']

    return parser, coordinates


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
        parser, coordinates = _load_or_parse(data_dir)

        if not coordinates:
            flash('No activity data found in the directory', 'warning')
            return redirect(url_for('index'))

        stats = parser.get_activity_stats()

        heatmap_obj = StravaHeatmap(coordinates)
        map_obj = heatmap_obj.create_heatmap()
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
        parser, coordinates = _load_or_parse(data_dir)

        stats = parser.get_activity_stats()
        return render_template('stats.html', stats=stats)

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        flash(f'Error getting stats: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/export')
def export():
    """Generate and download a static heatmap image."""
    from static_export import create_static_heatmap

    data_dir = request.args.get('data_dir', DATA_DIR)
    n_panels = int(request.args.get('panels', 2))
    fmt = request.args.get('format', 'png')

    if fmt not in ('png', 'jpeg'):
        flash('Invalid format. Use png or jpeg.', 'error')
        return redirect(url_for('index'))

    if not os.path.exists(data_dir):
        flash(f'Data directory not found: {data_dir}', 'error')
        return redirect(url_for('index'))

    try:
        parser, coordinates = _load_or_parse(data_dir)

        if not coordinates:
            flash('No activity data found in the directory', 'warning')
            return redirect(url_for('index'))

        ext = 'jpg' if fmt == 'jpeg' else fmt
        tmp = tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False)
        tmp.close()

        stats = parser.get_activity_stats()
        create_static_heatmap(
            coordinates,
            output_path=tmp.name,
            n_panels=n_panels,
            fmt=fmt,
            total_activities=stats.get('total_activities', 0),
            total_distance_km=stats.get('total_distance_km', 0),
        )

        mimetype = 'image/png' if fmt == 'png' else 'image/jpeg'
        return send_file(
            tmp.name,
            mimetype=mimetype,
            as_attachment=True,
            download_name=f'strava_heatmap.{ext}',
        )

    except Exception as e:
        logger.error(f"Error exporting heatmap: {e}")
        flash(f'Error exporting heatmap: {str(e)}', 'error')
        return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
