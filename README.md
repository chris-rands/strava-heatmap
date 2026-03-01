# Strava Activity Heatmap

An interactive web application that visualizes your Strava running activities as a beautiful heatmap. See where you've run the most and explore your activity patterns.

## Features

- Parse Strava export data (GPX, FIT, FIT.gz, and TCX formats)
- Interactive heatmap visualization using Leaflet
- Static heatmap export (PNG/JPEG) with auto-detected running hotspots
- Activity statistics dashboard (distance, pace, duration)
- Multiple map tile layers
- Coordinate caching for fast repeat loads
- Web-based interface with Flask

## Prerequisites

- Python 3.7 or higher
- A Strava account with activity data

## Installation

1. Clone or navigate to this directory:
```bash
cd strava-heatmap
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate  # On Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Getting Your Strava Data

1. Log in to [Strava](https://www.strava.com)
2. Go to Settings → My Account
3. Scroll down to "Download or Delete Your Account"
4. Click "Get Started" or "Request Your Archive"
5. Wait for the email (usually arrives within a few hours)
6. Download and extract the ZIP file
7. Note the path to the `activities` folder inside the extracted archive

## Usage

### Web Interface

1. Make sure your virtual environment is activated:
```bash
source venv/bin/activate
```

2. Start the Flask application:
```bash
python app.py
```

3. Open your web browser and go to:
```
http://localhost:5000
```

4. Enter the path to your Strava `activities` folder and click "Generate Heatmap"
5. Use the nav links to switch between the interactive heatmap, statistics, and static image export

### Static Image Export (CLI)

Generate a multi-panel PNG/JPEG showing your top running hotspots, suitable for social media:

```bash
python static_export.py --data-dir ./data/activities --output heatmap.png
```

Options:
- `--panels N` — number of hotspot panels (default: 4)
- `--format png|jpeg` — image format (default: png)
- `--dpi N` — image resolution (default: 250)
- `--eps-km N` — DBSCAN clustering radius in km (default: 2.0)
- `--min-samples N` — minimum points for a cluster (default: 50)

The export auto-detects geographic clusters, reverse-geocodes each to a place name, and renders a dark-themed heatmap with per-panel run/distance stats.

## Project Structure

```
strava-heatmap/
├── app.py              # Flask web application
├── parser.py           # Data parsing module (GPX, FIT, TCX)
├── heatmap.py          # Interactive heatmap visualization (Folium)
├── static_export.py    # Static heatmap image export (matplotlib)
├── cache.py            # Disk-based coordinate cache
├── requirements.txt    # Python dependencies
├── templates/          # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── heatmap.html
│   └── stats.html
└── README.md           # This file
```

## How It Works

1. **Data Parsing**: The app reads your activity files (GPX, FIT, FIT.gz, or TCX format) from the Strava export, with GPS point downsampling to reduce data size
2. **Caching**: Parsed coordinates are cached to disk (`.cache/`) so subsequent loads are instant
3. **Interactive Heatmap**: All coordinates are rendered as an interactive heatmap using Folium/Leaflet
4. **Static Export**: DBSCAN clustering identifies geographic hotspots, each rendered as a panel with dark basemap tiles, a smoothed heatmap overlay, and reverse-geocoded location names
5. **Web Interface**: Flask serves the visualizations through a user-friendly web interface

## Features Explained

### Heatmap View
- Shows activity intensity across your running routes
- Red areas indicate where you've run the most
- Blue areas show less frequent routes
- Multiple map layers available (OpenStreetMap, CartoDB Positron, CartoDB Dark Matter)

### Static Export
- Multi-panel image with your top running hotspots
- Each panel shows a place name, estimated run count, and distance
- Dark themed with custom heatmap colormap
- Suitable for sharing on social media

### Statistics View
- Total number of activities and GPS data points
- Total and average distance (km and miles)
- Average pace and duration
- Breakdown by file type (GPX, FIT, TCX)

## Customization

You can customize the interactive heatmap appearance by modifying parameters in `heatmap.py`:

- `radius`: Size of the heatmap points (default: 10)
- `blur`: Blur radius (default: 15)
- `min_opacity`: Minimum opacity (default: 0.3)
- `gradient`: Color gradient dictionary

## Troubleshooting

### "Data directory not found"
- Make sure you've entered the correct path to the activities folder
- The path should point to the folder containing .gpx, .fit, or .tcx files

### "No activity data found"
- Verify that your Strava export contains activity files
- Check that the files are in GPX, FIT, or TCX format

### Import errors
- Make sure you've activated the virtual environment
- Try reinstalling dependencies: `pip install -r requirements.txt`

### Static export runs out of memory
- The DBSCAN clustering subsamples to 20K points by default, so this should not happen
- If it does, try reducing `--panels` to 2

## Dependencies

- **Flask**: Web framework
- **Folium**: Interactive map visualization
- **gpxpy**: GPX file parsing
- **fitparse**: FIT file parsing
- **python-dateutil**: Date/time utilities
- **matplotlib**: Static image rendering
- **contextily**: Basemap tiles for static export
- **scikit-learn**: DBSCAN clustering for hotspot detection
- **scipy**: Gaussian smoothing for heatmap overlay
- **numpy**: Numerical operations

## Privacy Note

All data processing happens locally on your computer. Your Strava data is never uploaded to any external server. The only external network requests are:
- Map tile fetches from OpenStreetMap/CartoDB (receive geographic bounding boxes only)
- Reverse geocoding via Nominatim (receives cluster centre coordinates for place name lookup)

## License

This project is licensed under the [MIT License](LICENSE).
