"""Generate example PNG images for the README."""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from csdb2snfg.parser import parse_csdb_linear
from csdb2snfg.renderer import draw_snfg

EXAMPLES = {
    "simple_linear": (
        "Simple linear chain",
        "-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-",
    ),
    "branched": (
        "Branched N-glycan core",
        "-4)[βDGalp(1-6)]αDManp(1-4)[βDGalp(1-3)]αDManp(1-4)βDGlcNAcp(1-4)βDGlcNAcp(1-",
    ),
    "repeating": (
        "Repeating unit",
        "-4)βDGalp(1-4)/βDGalp(1-4)/n=3/βDGalp(1-4)αDGlcp(1-",
    ),
    "with_modifiers": (
        "With modifiers (Me, Ac)",
        "-4)[Me(1-3)]αDGalp(1-6)[Ac(1-3)]αDGalp(1-6)αDGalp(1-",
    ),
    "complex_branched": (
        "Complex multi-branched",
        "-3)[[αDGalp(1-6)]αLArap(1-3)αLAraf(1-6)]βDGalp(1-3)[Me(1-4)βDGalp(1-4)βDGalp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDXylp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDManp(1-6)]βDGalp(1-3)βDGalp(1-3)βDGlcp(1-",
    ),
}

OUT_PNG = os.path.join(os.path.dirname(__file__), "..", "examples", "png")
OUT_SVG = os.path.join(os.path.dirname(__file__), "..", "examples", "svg")
os.makedirs(OUT_PNG, exist_ok=True)
os.makedirs(OUT_SVG, exist_ok=True)

for name, (desc, csdb) in EXAMPLES.items():
    tree = parse_csdb_linear(csdb)

    # PNG
    fig, ax = draw_snfg(tree, font_size=12)
    png_path = os.path.join(OUT_PNG, f"{name}.png")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Generated {png_path}")

    # SVG
    svg_path = os.path.join(OUT_SVG, f"{name}.svg")
    draw_snfg(tree, font_size=12, save_svg=svg_path)
    print(f"Generated {svg_path}")
