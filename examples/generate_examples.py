"""Generate example PNG/SVG images for the README."""

import os
import sys

# Deterministic output: freeze the SVG dc:date (and any other date metadata)
# so re-running this script is byte-idempotent.
os.environ.setdefault("SOURCE_DATE_EPOCH", "0")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Fixed hash salt: clip-path ids in the SVG output would otherwise be
# regenerated from a random uuid on every run (same paradigm as the
# byte-stability tests).
matplotlib.rcParams["svg.hashsalt"] = "csdb2snfg"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from csdb2snfg.csdb.parser import parse_csdb_linear
from csdb2snfg.export.image import draw_snfg

# name -> (description, CSDB string, extra draw_snfg kwargs)
EXAMPLES = {
    # --- Basic structures (## Examples in the README) ---
    "simple_linear": (
        "Simple linear chain",
        "-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-",
        {},
    ),
    "branched": (
        "Branched N-glycan core",
        "-4)[βDGalp(1-6)]αDManp(1-4)[βDGalp(1-3)]αDManp(1-4)βDGlcNAcp(1-4)βDGlcNAcp(1-",
        {},
    ),
    "repeating": (
        "Repeating unit",
        "-4)βDGalp(1-4)/βDGalp(1-4)/n=3/βDGalp(1-4)αDGlcp(1-",
        {},
    ),
    "with_modifiers": (
        "With modifiers (Me, Ac)",
        "-4)[Me(1-3)]αDGalp(1-6)[Ac(1-3)]αDGalp(1-6)αDGalp(1-",
        {},
    ),
    "complex_branched": (
        "Complex multi-branched",
        "-3)[[αDGalp(1-6)]αLArap(1-3)αLAraf(1-6)]βDGalp(1-3)[Me(1-4)βDGalp(1-4)βDGalp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDXylp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDManp(1-6)]βDGalp(1-3)βDGalp(1-3)βDGlcp(1-",
        {},
    ),
    "fuzzy": (
        "Fuzzy unit",
        "-4)βDGalp(1-4)βDGalp(1-3)[<<αLAraf(1-6)|βLAraf(1-6)>>]βDGalp(1-3)αDGlcp(1-",
        {},
    ),
    # --- Feature options (Feature Guide in the README) ---
    "style_glycoworkbench": (
        "glycoworkbench preset (exactly the Feature Guide bash snippet)",
        "-4)βDGlcp(1-4)αDGlcp(1-",
        {"style": "glycoworkbench", "node_stroke_width": 1.5, "link_width": 2},
    ),
    "highlight": (
        "Motif highlighting",
        "-4)βDGalp(1-4)βDGalp(1-3)αDGalp(1-",
        {"highlight_motif": "βDGalp(1-4)βDGalp"},
    ),
    "end_freeend": (
        "Reducing-end marker: freeEnd squiggle",
        "-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-",
        {"end": "freeEnd"},
    ),
    "end_redend": (
        "Reducing-end marker: redEnd squiggle with centered O",
        "-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-",
        {"end": "redEnd"},
    ),
    "end_2ab": (
        "Reducing-end marker: 2AB text label",
        "-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-",
        {"end": "2AB"},
    ),
}

OUT_PNG = os.path.join(os.path.dirname(__file__), "..", "examples", "png")
OUT_SVG = os.path.join(os.path.dirname(__file__), "..", "examples", "svg")
os.makedirs(OUT_PNG, exist_ok=True)
os.makedirs(OUT_SVG, exist_ok=True)

for name, (_desc, csdb, kwargs) in EXAMPLES.items():
    tree = parse_csdb_linear(csdb)

    # PNG
    fig, ax = draw_snfg(tree, font_size=12, **kwargs)
    png_path = os.path.join(OUT_PNG, f"{name}.png")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Generated {png_path}")

    # SVG
    svg_path = os.path.join(OUT_SVG, f"{name}.svg")
    draw_snfg(tree, font_size=12, save_svg=svg_path, **kwargs)
    print(f"Generated {svg_path}")
