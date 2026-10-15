#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generates crisp, high-resolution cropped icons and MS Store / MSIX Assets
from DeckBridge_logo.png using Pillow Lanczos resampling.
"""

import os
from PIL import Image

def generate_assets():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(base_dir, "DeckBridge_logo.png")
    if not os.path.isfile(logo_path):
        raise FileNotFoundError(f"Missing {logo_path}")

    src_img = Image.open(logo_path).convert("RGBA")
    alpha = src_img.split()[-1]
    # Filter out faint alpha noise around edges (alpha > 25)
    mask = alpha.point(lambda p: 255 if p > 25 else 0)
    bbox = mask.getbbox()
    if not bbox:
        bbox = (0, 0, src_img.width, src_img.height)

    # Crop to content
    cropped = src_img.crop(bbox)
    cw, ch = cropped.size

    # Make square with minimal breathing padding (~1% on each side) to maximize logo size
    max_dim = max(cw, ch)
    padding = max(2, int(max_dim * 0.01))
    canvas_dim = max_dim + 2 * padding
    square_img = Image.new("RGBA", (canvas_dim, canvas_dim), (0, 0, 0, 0))

    offset_x = (canvas_dim - cw) // 2
    offset_y = (canvas_dim - ch) // 2
    square_img.paste(cropped, (offset_x, offset_y), cropped)

    # High-res master logo (1024x1024)
    master_logo = square_img.resize((1024, 1024), Image.Resampling.LANCZOS)
    master_logo.save(logo_path, format="PNG", optimize=True)
    print(f"Updated {logo_path} (1024x1024)")

    # Generate DeckBridge.ico and app_icon.ico with all standard Windows sizes
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_targets = [
        os.path.join(base_dir, "DeckBridge.ico"),
        os.path.join(base_dir, "app_icon.ico"),
        os.path.join(base_dir, "Assets", "app.ico"),
        os.path.join(base_dir, "dist", "DeckBridge", "DeckBridge.ico"),
        os.path.join(base_dir, "dist", "DeckBridge", "_internal", "DeckBridge.ico")
    ]
    for target in ico_targets:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        master_logo.save(target, format="ICO", sizes=ico_sizes)
        print(f"Generated ICO: {target}")

    # Generate all Assets/ PNGs
    assets_dirs = [
        os.path.join(base_dir, "Assets"),
        os.path.join(base_dir, "dist", "DeckBridge", "Assets")
    ]

    # Map of filename -> (width, height)
    assets_specs = {
        # AppList (Square44x44)
        "AppList.png": (44, 44),
        "AppList.scale-125.png": (55, 55),
        "AppList.scale-150.png": (66, 66),
        "AppList.scale-200.png": (88, 88),
        "AppList.scale-400.png": (176, 176),
        # AppList targetsize
        "AppList.targetsize-16.png": (16, 16),
        "AppList.targetsize-16_altform-unplated.png": (16, 16),
        "AppList.targetsize-20.png": (20, 20),
        "AppList.targetsize-20_altform-unplated.png": (20, 20),
        "AppList.targetsize-24.png": (24, 24),
        "AppList.targetsize-24_altform-unplated.png": (24, 24),
        "AppList.targetsize-30.png": (30, 30),
        "AppList.targetsize-30_altform-unplated.png": (30, 30),
        "AppList.targetsize-32.png": (32, 32),
        "AppList.targetsize-32_altform-unplated.png": (32, 32),
        "AppList.targetsize-36.png": (36, 36),
        "AppList.targetsize-36_altform-unplated.png": (36, 36),
        "AppList.targetsize-40.png": (40, 40),
        "AppList.targetsize-40_altform-unplated.png": (40, 40),
        "AppList.targetsize-48.png": (48, 48),
        "AppList.targetsize-48_altform-unplated.png": (48, 48),
        "AppList.targetsize-60.png": (60, 60),
        "AppList.targetsize-60_altform-unplated.png": (60, 60),
        "AppList.targetsize-64.png": (64, 64),
        "AppList.targetsize-64_altform-unplated.png": (64, 64),
        "AppList.targetsize-72.png": (72, 72),
        "AppList.targetsize-72_altform-unplated.png": (72, 72),
        "AppList.targetsize-80.png": (80, 80),
        "AppList.targetsize-80_altform-unplated.png": (80, 80),
        "AppList.targetsize-96.png": (96, 96),
        "AppList.targetsize-96_altform-unplated.png": (96, 96),
        "AppList.targetsize-256.png": (256, 256),
        "AppList.targetsize-256_altform-unplated.png": (256, 256),
        # MedTile (Square150x150)
        "MedTile.png": (150, 150),
        "MedTile.scale-125.png": (188, 188),
        "MedTile.scale-150.png": (225, 225),
        "MedTile.scale-200.png": (300, 300),
        "MedTile.scale-400.png": (600, 600),
        # StoreLogo (Square50x50)
        "StoreLogo.png": (50, 50),
        "StoreLogo.scale-125.png": (63, 63),
        "StoreLogo.scale-150.png": (75, 75),
        "StoreLogo.scale-200.png": (100, 100),
        "StoreLogo.scale-400.png": (200, 200),
        # WideTile (Wide310x150)
        "WideTile.png": (310, 150),
        "WideTile.scale-125.png": (388, 188),
        "WideTile.scale-150.png": (465, 225),
        "WideTile.scale-200.png": (620, 300),
        "WideTile.scale-400.png": (1240, 600),
    }

    for adir in assets_dirs:
        os.makedirs(adir, exist_ok=True)
        for fname, (w, h) in assets_specs.items():
            out_path = os.path.join(adir, fname)
            if "WideTile" in fname:
                # Center square logo inside wide rectangle with height h
                icon_sz = int(h * 0.85)
                scaled_icon = master_logo.resize((icon_sz, icon_sz), Image.Resampling.LANCZOS)
                wide_canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                wide_canvas.paste(scaled_icon, ((w - icon_sz) // 2, (h - icon_sz) // 2), scaled_icon)
                wide_canvas.save(out_path, format="PNG", optimize=True)
            else:
                scaled = master_logo.resize((w, h), Image.Resampling.LANCZOS)
                scaled.save(out_path, format="PNG", optimize=True)

    # Also copy DeckBridge_logo.png to dist\DeckBridge\_internal
    dist_logo = os.path.join(base_dir, "dist", "DeckBridge", "_internal", "DeckBridge_logo.png")
    if os.path.isdir(os.path.dirname(dist_logo)):
        master_logo.save(dist_logo, format="PNG", optimize=True)
    dist_root_logo = os.path.join(base_dir, "dist", "DeckBridge", "DeckBridge_logo.png")
    if os.path.isdir(os.path.dirname(dist_root_logo)):
        master_logo.save(dist_root_logo, format="PNG", optimize=True)

    print("All icons and Assets successfully regenerated!")

if __name__ == "__main__":
    generate_assets()
