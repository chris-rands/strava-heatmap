# Strava Activity Heatmap

An interactive web application that visualizes your Strava running activities as a beautiful heatmap. See where you've run the most and explore your activity patterns.

## Features

- Parse Strava export data (GPX, FIT, and TCX formats)
- Interactive heatmap visualization using Leaflet
- Activity statistics dashboard
- Multiple map tile layers
- Web-based interface with Flask

## Prerequisites

- Python 3.7 or higher
- A Strava account with activity data

## Installation

1. Clone or navigate to this directory:
```bash
cd strava_heatmap
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

## Project Structure

```
strava_heatmap/
├── app.py              # Flask web application
├── parser.py           # Data parsing module (GPX, FIT, TCX)
├── heatmap.py          # Heatmap visualization module
├── requirements.txt    # Python dependencies
├── templates/          # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── heatmap.html
│   └── stats.html
└── README.md          # This file
```

## How It Works

1. **Data Parsing**: The app reads your activity files (GPX, FIT, or TCX format) from the Strava export
2. **Coordinate Extraction**: GPS coordinates are extracted from each activity
3. **Visualization**: All coordinates are combined and rendered as an interactive heatmap using Folium
4. **Web Interface**: Flask serves the visualization through a user-friendly web interface

## Features Explained

### Heatmap View
- Shows activity intensity across your running routes
- Red areas indicate where you've run the most
- Blue areas show less frequent routes
- Multiple map layers available (OpenStreetMap, CartoDB Positron, CartoDB Dark Matter)

### Statistics View
- Total number of activities
- Total GPS data points
- Breakdown by file type (GPX, FIT, TCX)

## Customization

You can customize the heatmap appearance by modifying parameters in `heatmap.py`:

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

## Dependencies

- **Flask**: Web framework
- **Folium**: Interactive map visualization
- **gpxpy**: GPX file parsing
- **fitparse**: FIT file parsing
- **python-dateutil**: Date/time utilities

## Privacy Note

All data processing happens locally on your computer. Your Strava data is never uploaded to any external server (except for the map tiles from OpenStreetMap/CartoDB, which only receive the geographic coordinates being displayed).

## License

This project is provided as-is for personal use.

## Future Enhancements

Potential features to add:
- Filter activities by date range
- Activity type filtering (run, bike, etc.)
- Distance and elevation statistics
- Export heatmap as image
- Individual route viewing
- Year-over-year comparisons

## Support

For issues or questions, please check:
1. Ensure your virtual environment is activated
2. Verify the path to your Strava data is correct
3. Check that activity files are present in the directory
4. Review console output for error messages
