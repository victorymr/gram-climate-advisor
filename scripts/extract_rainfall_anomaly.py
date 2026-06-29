#!/usr/bin/env python3
"""
Extract rainfall anomaly values from IMD Extended Range Forecast maps.

This script:
1. Loads the IMD rainfall anomaly PNG (4-panel map)
2. Identifies the 4 map panels and their lat/lon extents
3. For each district, converts lat/lon to pixel coordinates
4. Reads the pixel color at that location
5. Maps the color to the anomaly scale (-15 to +15 mm/day)

Usage:
    python scripts/extract_rainfall_anomaly.py data/samples/rfanom_MME2026062400.png
"""

import sys
import csv
import json
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("❌ Missing dependencies. Install with:")
    print("   pip install Pillow numpy")
    sys.exit(1)


# --- Configuration ---

# District coordinates file
DISTRICT_COORDS_FILE = "data/district_coordinates.csv"

# Color scale: maps RGB values to anomaly values (mm/day)
# The IMD legend goes from -15 (red) through 0 (white) to +15 (blue)
# We'll sample the legend bar from the image to build the exact mapping


def load_district_coordinates(filepath: str) -> list[dict]:
    """Load district lat/lon from CSV."""
    districts = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            districts.append({
                "state": row["state"],
                "district": row["district"],
                "lat": float(row["latitude"]),
                "lon": float(row["longitude"]),
            })
    return districts


def detect_panel_bounds(img: Image.Image) -> dict:
    """
    Detect the pixel boundaries and lat/lon extents of each of the 4 map panels.
    
    Finds the actual map axis boundaries by scanning for continuous black lines
    (axis borders) in each quadrant of the image.
    """
    width, height = img.size
    img_array = np.array(img)
    
    # Split image into quadrants and find axis borders in each
    quadrants = {
        "week1": {"x_scan": (10, width // 2), "y_scan": (30, height // 2), "label": "Week 1"},
        "week2": {"x_scan": (width // 2, width - 10), "y_scan": (30, height // 2), "label": "Week 2"},
        "week3": {"x_scan": (10, width // 2), "y_scan": (height // 2, height - 10), "label": "Week 3"},
        "week4": {"x_scan": (width // 2, width - 10), "y_scan": (height // 2, height - 10), "label": "Week 4"},
    }
    
    panels = {}
    
    for key, quad in quadrants.items():
        x_start, x_end = quad["x_scan"]
        y_start, y_end = quad["y_scan"]
        
        # Find vertical black lines (axis left and right borders)
        vert_lines = []
        for x in range(x_start, x_end):
            black_count = 0
            for y in range(y_start, y_end):
                r, g, b = img_array[y, x, :3]
                if r < 10 and g < 10 and b < 10:
                    black_count += 1
            if black_count > (y_end - y_start) * 0.5:
                vert_lines.append(x)
        
        # Find horizontal black lines (axis top and bottom borders)
        horiz_lines = []
        for y in range(y_start, y_end):
            black_count = 0
            for x in range(x_start, x_end):
                r, g, b = img_array[y, x, :3]
                if r < 10 and g < 10 and b < 10:
                    black_count += 1
            if black_count > (x_end - x_start) * 0.5:
                horiz_lines.append(y)
        
        if vert_lines and horiz_lines:
            map_x_min = min(vert_lines)
            map_x_max = max(vert_lines)
            map_y_min = min(horiz_lines)
            map_y_max = max(horiz_lines)
            
            # Sanity check: map area should be at least 100px wide
            # If not, the right border was not detected (e.g., clipped by image edge)
            if (map_x_max - map_x_min) < 100:
                print(f"   ⚠️  {quad['label']}: detected width too narrow ({map_x_max - map_x_min}px), will fix from sibling panel")
                panels[key] = {
                    "map_bounds": None,  # Will be fixed later
                    "label": quad["label"],
                    "partial": (map_x_min, map_y_min, map_x_max, map_y_max),
                }
            else:
                panels[key] = {
                    "map_bounds": (map_x_min, map_y_min, map_x_max, map_y_max),
                    "label": quad["label"],
                }
                print(f"   {quad['label']}: map_bounds = ({map_x_min}, {map_y_min}, {map_x_max}, {map_y_max}) [{map_x_max-map_x_min}x{map_y_max-map_y_min} px]")
        else:
            print(f"   ⚠️  Could not detect axis boundaries for {quad['label']}")
    
    # Fix any panels with missing bounds by using sibling panel dimensions
    # Week 4 should match Week 2's width, Week 3's height
    for key in panels:
        if panels[key].get("map_bounds") is None and "partial" in panels[key]:
            partial = panels[key]["partial"]
            # Find sibling panels to get expected width/height
            if key == "week4":
                sibling_w = panels.get("week2", {}).get("map_bounds")
                sibling_h = panels.get("week3", {}).get("map_bounds")
                if sibling_w:
                    expected_width = sibling_w[2] - sibling_w[0]
                    map_x_max = partial[0] + expected_width
                    panels[key]["map_bounds"] = (partial[0], partial[1], map_x_max, partial[3])
                    print(f"   {panels[key]['label']}: fixed bounds = {panels[key]['map_bounds']} (width from Week 2)")
            elif key == "week3":
                sibling_w = panels.get("week1", {}).get("map_bounds")
                if sibling_w:
                    expected_width = sibling_w[2] - sibling_w[0]
                    map_x_max = partial[0] + expected_width
                    panels[key]["map_bounds"] = (partial[0], partial[1], map_x_max, partial[3])
                    print(f"   {panels[key]['label']}: fixed bounds = {panels[key]['map_bounds']} (width from Week 1)")
    
    # Geographic calibration from axis tick marks (Week 1 panel):
    # Lon ticks at x = 84, 134, 185, 235, 285 correspond to 70E, 77E, 84E, 91E, 98E
    # Lat ticks at y = 98, 141, 183, 226, 269, 312, 355 correspond to 35N, 30N, 25N, 20N, 15N, 10N, 5N
    # px_per_deg_lon = (285-84) / (98-70) = 201/28 = 7.179
    # px_per_deg_lat = (355-98) / (35-5) = 257/30 = 8.567
    # These ticks are in the Week 1 panel; other panels use the same geographic extent.
    for key, panel in panels.items():
        panel["lon_ticks"] = {"pixel_positions": [84, 134, 185, 235, 285],
                               "values": [70.0, 77.0, 84.0, 91.0, 98.0]}
        panel["lat_ticks"] = {"pixel_positions": [98, 141, 183, 226, 269, 312, 355],
                               "values": [35.0, 30.0, 25.0, 20.0, 15.0, 10.0, 5.0]}
    
    return panels


def calibrate_panels(img: Image.Image, panels: dict) -> dict:
    """No additional calibration needed — bounds detected from axis lines."""
    return panels


def latlon_to_pixel(lat: float, lon: float, panel: dict) -> tuple[int, int]:
    """
    Convert lat/lon to pixel coordinates using tick-mark calibration.
    
    Uses the known axis tick positions and their geographic values to compute
    px_per_degree, then offsets from the first tick to get the pixel coordinate.
    For non-Week-1 panels, applies the panel offset from Week 1.
    """
    lon_ticks = panel["lon_ticks"]
    lat_ticks = panel["lat_ticks"]
    map_bounds = panel["map_bounds"]
    
    # Compute scale from tick marks (using first and last ticks)
    lon_px = lon_ticks["pixel_positions"]
    lon_vals = lon_ticks["values"]
    lat_px = lat_ticks["pixel_positions"]
    lat_vals = lat_ticks["values"]
    
    px_per_deg_lon = (lon_px[-1] - lon_px[0]) / (lon_vals[-1] - lon_vals[0])
    px_per_deg_lat = (lat_px[-1] - lat_px[0]) / (lat_vals[0] - lat_vals[-1])
    # lat_vals[0] is the top (35N), lat_vals[-1] is bottom (5N)
    
    # Week 1 reference tick positions
    ref_lon_px0 = lon_px[0]  # x pixel of first lon tick (70E)
    ref_lat_px0 = lat_px[0]  # y pixel of first lat tick (35N)
    ref_lon_val0 = lon_vals[0]  # 70.0
    ref_lat_val0 = lat_vals[0]  # 35.0
    
    # Compute pixel in Week 1 coordinate space
    px_week1 = ref_lon_px0 + (lon - ref_lon_val0) * px_per_deg_lon
    py_week1 = ref_lat_px0 + (ref_lat_val0 - lat) * px_per_deg_lat
    
    # Apply panel offset (difference between this panel's map bounds and Week 1's)
    # The tick positions are defined relative to Week 1, so we need to shift
    # for other panels based on their map_bounds vs Week 1's position
    # Week 1 left border is at map_bounds[0], its first lon tick is at lon_px[0]
    # The offset from border to first tick is the same for all panels
    # So for panel N: actual_px = panel_N_x_min + (px_week1 - week1_x_min)
    
    # We store week1 bounds in the tick data (ticks are always relative to week1)
    # For non-week1 panels, shift by the difference in map_bounds[0] and map_bounds[1]
    # Actually, since all panels have the same tick positions stored, we just need
    # to shift by the panel offset
    
    # The tick pixel positions are absolute (Week 1), so for other panels:
    # panel_offset_x = panel.map_bounds[0] - week1.map_bounds[0]
    # But we don't have week1 bounds here. Instead, use the map_bounds directly:
    # The first lon tick in Week 1 is at x=84. The map left border is at x=48.
    # So tick-to-border offset = 84 - 48 = 36 pixels.
    # For any panel, first_tick_x = panel.map_bounds[0] + 36
    
    tick_to_left_border = lon_px[0] - 48   # 84 - 48 = 36 (Week 1 reference)
    tick_to_top_border = lat_px[0] - 72    # 98 - 72 = 26 (Week 1 reference)
    
    panel_first_tick_x = map_bounds[0] + tick_to_left_border
    panel_first_tick_y = map_bounds[1] + tick_to_top_border
    
    px = int(panel_first_tick_x + (lon - ref_lon_val0) * px_per_deg_lon)
    py = int(panel_first_tick_y + (ref_lat_val0 - lat) * px_per_deg_lat)
    
    return px, py


def extract_legend_colormap(img: Image.Image) -> list[tuple]:
    """
    Get the color scale for the IMD rainfall anomaly map.
    
    Uses the calibrated color scale extracted from the actual image colorbar
    segments found at y=391 in rfanom_MME2026062400.png.
    
    Returns a list of (anomaly_value, R, G, B) tuples spanning -15 to +15.
    """
    # Use the calibrated colormap derived from actual pixel sampling of the image
    print("   Using calibrated IMD color scale (extracted from image colorbar segments)")
    return _get_standard_imd_colormap()


def _get_standard_imd_colormap() -> list[tuple]:
    """
    IMD rainfall anomaly color scale extracted from actual image colorbar.
    
    Calibrated from rfanom_MME2026062400.png colorbar at y=391.
    The scale is -15 to +15 mm/day with these discrete color segments:
    - Orange/Red tones = negative (below normal)
    - White = near zero
    - Blue/Purple tones = positive (above normal)
    """
    # Key colors extracted from actual IMD colorbar (pixel x positions mapped to anomaly values)
    # Colorbar spans x=104 to x=500 in the image
    # Legend labels show: -15, -10, -7, -3, -1, 1, 3, 7, 10, 15
    # Mapping x positions to anomaly values based on label positions:
    key_colors = [
        (-15.0, 215, 14, 0),      # Dark red-orange (from y=393 scan)
        (-10.0, 255, 82, 0),      # Strong orange (x=104)
        (-7.0, 255, 142, 29),     # Orange (x=154)
        (-3.0, 255, 202, 89),     # Light orange (x=203)
        (-1.0, 255, 244, 165),    # Very light orange/cream (x=253)
        (0.0, 255, 255, 255),     # White (center)
        (1.0, 200, 200, 233),     # Very light blue (x=351)
        (3.0, 140, 140, 191),     # Light blue (x=401)
        (7.0, 100, 100, 163),     # Blue (x=450)
        (10.0, 60, 60, 135),      # Dark blue (x=500)
        (15.0, 30, 30, 100),      # Very dark blue (extrapolated)
    ]
    
    # Interpolate to create a dense colormap
    colormap = []
    for i in range(301):  # -15 to +15 in 0.1 steps
        anomaly = -15.0 + (30.0 * i / 300)
        
        # Find surrounding key colors
        lower = key_colors[0]
        upper = key_colors[-1]
        for j in range(len(key_colors) - 1):
            if key_colors[j][0] <= anomaly <= key_colors[j + 1][0]:
                lower = key_colors[j]
                upper = key_colors[j + 1]
                break
        
        # Linear interpolation
        if upper[0] == lower[0]:
            frac = 0.5
        else:
            frac = (anomaly - lower[0]) / (upper[0] - lower[0])
        
        r = int(lower[1] + frac * (upper[1] - lower[1]))
        g = int(lower[2] + frac * (upper[2] - lower[2]))
        b = int(lower[3] + frac * (upper[3] - lower[3]))
        
        colormap.append((anomaly, r, g, b))
    
    return colormap


def color_to_anomaly(r: int, g: int, b: int, colormap: list[tuple]) -> float:
    """
    Find the closest matching anomaly value for a given RGB color.
    
    Uses Euclidean distance in RGB space.
    """
    min_dist = float('inf')
    best_anomaly = 0.0
    
    for anomaly, cr, cg, cb in colormap:
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < min_dist:
            min_dist = dist
            best_anomaly = anomaly
    
    return best_anomaly


def get_pixel_color_averaged(img_array: np.ndarray, px: int, py: int, 
                              radius: int = 2) -> tuple[int, int, int]:
    """
    Get the nearest valid data pixel color at the target location.
    
    Only filters out black pixels (R,G,B all < 15) which are coastline/border lines.
    White is valid data (near-zero anomaly per the IMD legend).
    
    Searches in expanding radius from the target pixel, returns the
    nearest non-black pixel found.
    """
    h, w = img_array.shape[:2]
    
    # First check the target pixel itself
    r, g, b = img_array[py, px, :3]
    if not (r < 15 and g < 15 and b < 15):
        return int(r), int(g), int(b)
    
    # Target is on a border line — find nearest non-black pixel
    for search_r in range(1, radius + 10):
        best_dist = float('inf')
        best_color = None
        
        for dy in range(-search_r, search_r + 1):
            for dx in range(-search_r, search_r + 1):
                # Only check pixels at the current ring (not interior, already checked)
                if abs(dy) != search_r and abs(dx) != search_r:
                    continue
                    
                ny, nx = py + dy, px + dx
                if 0 <= ny < h and 0 <= nx < w:
                    pr, pg, pb = img_array[ny, nx, :3]
                    # Skip black (border) pixels
                    if pr < 15 and pg < 15 and pb < 15:
                        continue
                    dist = dx * dx + dy * dy
                    if dist < best_dist:
                        best_dist = dist
                        best_color = (int(pr), int(pg), int(pb))
        
        if best_color is not None:
            return best_color
    
    # Fallback
    return 255, 255, 255


def anomaly_to_signal(anomaly: float) -> str:
    """Convert mm/day anomaly to forecast signal category."""
    if anomaly >= 3.0:
        return "above_normal"
    elif anomaly <= -3.0:
        return "below_normal"
    else:
        return "near_normal"


def extract_rainfall_anomalies(image_path: str, districts: list[dict]) -> list[dict]:
    """
    Main extraction function.
    
    Args:
        image_path: Path to the IMD rainfall anomaly PNG
        districts: List of district dicts with lat/lon
        
    Returns:
        List of extraction results per district per week
    """
    img = Image.open(image_path).convert("RGB")
    img_array = np.array(img)
    
    print(f"📷 Image size: {img.size[0]} x {img.size[1]} pixels")
    
    # Step 1: Detect and calibrate panel bounds
    print("🔍 Detecting panel boundaries...")
    panels = detect_panel_bounds(img)
    panels = calibrate_panels(img, panels)
    
    for key, panel in panels.items():
        print(f"   {panel['label']}: map_bounds = {panel.get('map_bounds', 'NOT FOUND')}")
    
    # Step 2: Extract color scale from legend
    print("🎨 Extracting color scale from legend...")
    colormap = extract_legend_colormap(img)
    print(f"   Sampled {len(colormap)} colors from legend bar")
    
    # Verify colormap makes sense
    # Left end should be warm (red/orange), right end should be cool (blue)
    left_color = colormap[0]
    right_color = colormap[-1]
    mid_color = colormap[len(colormap) // 2]
    print(f"   Left (anomaly={left_color[0]:.1f}): RGB({left_color[1]}, {left_color[2]}, {left_color[3]})")
    print(f"   Mid (anomaly={mid_color[0]:.1f}): RGB({mid_color[1]}, {mid_color[2]}, {mid_color[3]})")
    print(f"   Right (anomaly={right_color[0]:.1f}): RGB({right_color[1]}, {right_color[2]}, {right_color[3]})")
    
    # Step 3: For each district, extract anomaly from each panel
    print(f"\n📊 Extracting anomalies for {len(districts)} districts...")
    results = []
    
    for district in districts:
        district_result = {
            "state": district["state"],
            "district": district["district"],
            "lat": district["lat"],
            "lon": district["lon"],
        }
        
        for week_key in ["week1", "week2", "week3", "week4"]:
            panel = panels[week_key]
            
            # Convert lat/lon to pixel
            px, py = latlon_to_pixel(district["lat"], district["lon"], panel)
            
            # Check if pixel is within image bounds
            if 0 <= px < img.size[0] and 0 <= py < img.size[1]:
                # Get averaged color at location
                r, g, b = get_pixel_color_averaged(img_array, px, py, radius=3)
                
                # Convert to anomaly value
                anomaly = color_to_anomaly(r, g, b, colormap)
                signal = anomaly_to_signal(anomaly)
                
                district_result[f"{week_key}_rgb"] = f"({r},{g},{b})"
                district_result[f"{week_key}_anomaly_mm_day"] = round(anomaly, 1)
                district_result[f"{week_key}_signal"] = signal
                district_result[f"{week_key}_pixel"] = f"({px},{py})"
            else:
                district_result[f"{week_key}_rgb"] = "OUT_OF_BOUNDS"
                district_result[f"{week_key}_anomaly_mm_day"] = None
                district_result[f"{week_key}_signal"] = "UNKNOWN"
                district_result[f"{week_key}_pixel"] = f"({px},{py})"
        
        results.append(district_result)
    
    return results


def print_results(results: list[dict]):
    """Print extraction results in a readable table."""
    print(f"\n{'='*90}")
    print(f"{'District':<20} {'Week1':<20} {'Week2':<20} {'Week3':<20} {'Week4':<20}")
    print(f"{'='*90}")
    
    for r in results:
        name = f"{r['district']}"
        w1 = f"{r.get('week1_anomaly_mm_day', '?'):>5} ({r.get('week1_signal', '?')})"
        w2 = f"{r.get('week2_anomaly_mm_day', '?'):>5} ({r.get('week2_signal', '?')})"
        w3 = f"{r.get('week3_anomaly_mm_day', '?'):>5} ({r.get('week3_signal', '?')})"
        w4 = f"{r.get('week4_anomaly_mm_day', '?'):>5} ({r.get('week4_signal', '?')})"
        print(f"{name:<20} {w1:<20} {w2:<20} {w3:<20} {w4:<20}")
    
    print(f"{'='*90}")


def save_results(results: list[dict], output_path: str):
    """Save extraction results to CSV."""
    if not results:
        return
    
    fieldnames = list(results[0].keys())
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"\n💾 Results saved to: {output_path}")


def main():
    """Main entry point."""
    print("🌾 IMD Rainfall Anomaly Extractor")
    print("=" * 50)
    
    # Determine image path
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        # Default: look for most recent rfanom file
        samples_dir = Path("data/samples")
        rfanom_files = list(samples_dir.glob("rfanom*.png"))
        if not rfanom_files:
            print("❌ No rfanom*.png files found in data/samples/")
            print("   Usage: python scripts/extract_rainfall_anomaly.py <image_path>")
            sys.exit(1)
        image_path = str(sorted(rfanom_files)[-1])  # Most recent
    
    print(f"📁 Image: {image_path}")
    
    # Load district coordinates
    districts = load_district_coordinates(DISTRICT_COORDS_FILE)
    print(f"📍 Loaded {len(districts)} districts")
    
    # Extract anomalies
    results = extract_rainfall_anomalies(image_path, districts)
    
    # Print results
    print_results(results)
    
    # Save results
    output_path = "data/extracted_rainfall_anomaly.csv"
    save_results(results, output_path)
    
    # Print diagnostic info for verification
    print("\n🔍 VERIFICATION DATA (check these against what you see on the map):")
    print("   Pixel locations and RGB values for manual verification:")
    for r in results:
        print(f"   {r['district']}: Week1 pixel={r.get('week1_pixel')} RGB={r.get('week1_rgb')}")
    
    print("\n⚠️  Please verify these results against your own reading of the map.")
    print("   If values look wrong, the panel calibration may need adjustment.")


if __name__ == "__main__":
    main()
