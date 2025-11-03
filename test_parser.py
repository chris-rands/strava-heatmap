"""Quick test of the parser with actual data."""

from parser import StravaDataParser

# Test with activities directory
parser = StravaDataParser('./data/activities')
print("Parsing activities...")
coords = parser.parse_all_activities()
stats = parser.get_activity_stats()

print("\n=== Statistics ===")
print(f"Total activities: {stats['total_activities']}")
print(f"GPX files: {stats['gpx_files']}")
print(f"FIT files: {stats['fit_files']}")
print(f"TCX files: {stats['tcx_files']}")
print(f"Total coordinates: {stats['total_coordinates']:,}")

if coords:
    print(f"\nFirst coordinate: {coords[0]}")
    print(f"Last coordinate: {coords[-1]}")
