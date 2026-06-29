#!/usr/bin/env python3
"""
Extract 2m max temperature anomaly values from IMD Extended Range Forecast maps.

This script:
1. Loads the IMD Tmax anomaly PNG (4-panel map)
2. Identifies the 4 map panels and their lat/lon extents
3. For each district, converts lat/lon to pixel coordinates
4. Reads the pixel color at that location
5. Maps the color to the anomaly scale (-6 to +6 °C)

Usage:
    python scripts/extract_tmax_anomaly.py data/samples/tmaxanom_MME2026062400.png
"""

import sys
import csv
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("❌ Missing dependencies. Install with:")
    print("   pip install Pillow numpy")
    sys.exit(1)

# Reuse shared functions from rainfall anomaly script
from extract_rainfall_anomaly import (
    load_district_coordinates,
    detect_panel_bounds,
    calibrate_panels,
    latlon_to_pixel,
    get_pixel_color_averaged,
    color_to_anomaly,
    DISTRICT_COORDS_FILE,
)


def _get_tmax_colormap() -> list[tuple]:
    """
    IMD Tmax anomaly color scale extracted from actual image colorbar.

    Calibrated from tmaxanom_MME2026062400.png colorbar at y=398.
    The scale is -6 to +6 °C with these discrete color segments:
    - Blue/Purple tones = negative (cooler than normal)
    - White/Cream = near zero
    - Orange/Red tones = positive (hotter than normal)
    """
    # Key colors extracted from actual colorbar scan at y=398
    # 13 discrete segments mapped to anomaly values -6 to +6
    key_colors = [
        (-6.0,  16,  16,  58),    # Very dark blue
        (-5.0,  56,  56, 128),    # Dark blue
        (-4.0,  90,  90, 156),    # Blue
        (-3.0, 130, 130, 184),    # Medium blue
        (-2.0, 170, 170, 212),    # Light blue
        (-1.0, 200, 200, 233),    # Very light blue
        ( 0.0, 220, 220, 247),    # Pale blue-white (the zero band is shifted slightly blue)
        ( 0.5, 255, 250, 205),    # Cream/pale yellow
        ( 1.0, 255, 166,  53),    # Light orange
        ( 2.0, 255, 118,   5),    # Orange
        ( 3.0, 255,  94,   0),    # Dark orange
        ( 4.0, 255,  46,   0),    # Red-orange
        ( 5.0, 195,   4,   0),    # Red
        ( 6.0, 115,   0,   0),    # Dark red
    ]

    # Interpolate to create a dense colormap
    colormap = []
    for i in range(241):  # -6 to +6 in 0.05 steps
        anomaly = -6.0 + (12.0 * i / 240)

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


def tmax_anomaly_to_signal(anomaly: float) -> str:
    """Convert °C anomaly to forecast signal category."""
    if anomaly >= 1.5:
        return "above_normal"
    elif anomaly <= -1.5:
        return "below_normal"
    else:
        return "near_normal"


def extract_tmax_anomalies(image_path: str, districts: list[dict]) -> list[dict]:
    """
    Main extraction function for Tmax anomaly maps.
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

    # Step 2: Build Tmax color scale
    print("🎨 Using calibrated Tmax anomaly color scale (-6 to +6 °C)")
    colormap = _get_tmax_colormap()
    print(f"   Sampled {len(colormap)} colors from interpolated legend")

    left_color = colormap[0]
    mid_color = colormap[len(colormap) // 2]
    right_color = colormap[-1]
    print(f"   Left (anomaly={left_color[0]:.1f}°C): RGB({left_color[1]}, {left_color[2]}, {left_color[3]})")
    print(f"   Mid (anomaly={mid_color[0]:.1f}°C): RGB({mid_color[1]}, {mid_color[2]}, {mid_color[3]})")
    print(f"   Right (anomaly={right_color[0]:.1f}°C): RGB({right_color[1]}, {right_color[2]}, {right_color[3]})")

    # Step 3: For each district, extract anomaly from each panel
    print(f"\n📊 Extracting Tmax anomalies for {len(districts)} districts...")
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
                # Get pixel color (filter black borders only)
                r, g, b = get_pixel_color_averaged(img_array, px, py, radius=2)

                # Convert to anomaly value
                anomaly = color_to_anomaly(r, g, b, colormap)
                signal = tmax_anomaly_to_signal(anomaly)

                district_result[f"{week_key}_rgb"] = f"({r},{g},{b})"
                district_result[f"{week_key}_anomaly_degC"] = round(anomaly, 1)
                district_result[f"{week_key}_signal"] = signal
                district_result[f"{week_key}_pixel"] = f"({px},{py})"
            else:
                district_result[f"{week_key}_rgb"] = "OUT_OF_BOUNDS"
                district_result[f"{week_key}_anomaly_degC"] = None
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
        w1 = f"{r.get('week1_anomaly_degC', '?'):>5}°C ({r.get('week1_signal', '?')})"
        w2 = f"{r.get('week2_anomaly_degC', '?'):>5}°C ({r.get('week2_signal', '?')})"
        w3 = f"{r.get('week3_anomaly_degC', '?'):>5}°C ({r.get('week3_signal', '?')})"
        w4 = f"{r.get('week4_anomaly_degC', '?'):>5}°C ({r.get('week4_signal', '?')})"
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
    print("🌡️  IMD Tmax Anomaly Extractor")
    print("=" * 50)

    # Determine image path
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        # Default: look for most recent tmaxanom file
        samples_dir = Path("data/samples")
        tmax_files = list(samples_dir.glob("tmaxanom*.png"))
        if not tmax_files:
            print("❌ No tmaxanom*.png files found in data/samples/")
            print("   Usage: python scripts/extract_tmax_anomaly.py <image_path>")
            sys.exit(1)
        image_path = str(sorted(tmax_files)[-1])  # Most recent

    print(f"📁 Image: {image_path}")

    # Load district coordinates
    districts = load_district_coordinates(DISTRICT_COORDS_FILE)
    print(f"📍 Loaded {len(districts)} districts")

    # Extract anomalies
    results = extract_tmax_anomalies(image_path, districts)

    # Print results
    print_results(results)

    # Save results
    output_path = "data/extracted_tmax_anomaly.csv"
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
