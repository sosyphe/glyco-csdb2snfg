"""Style system for SNFG rendering: palettes, per-element colors and stroke widths.

Backend-agnostic (stdlib + snfg.symbols only). A Style bundles every visual
knob shared by the image and pptx backends:

- ``palette`` / ``dim_palette`` / ``mono_styles``: color-name -> hex tables and
  the monosaccharide -> [shape, color-name] mapping (defaults are copies of
  ``symbols.glycan_color`` / ``symbols.glycan_dict``);
- stroke/line/fuzzy/bracket colors and widths. Any of these set to ``None``
  means "backend-native default": the backends keep using their historical
  hardcoded literals, which guarantees byte-identical output for the default
  style;
- ``dim_*`` fields carry concrete defaults because they only take effect while
  a highlight plan is active (never on the default render path).

Presets live in ``PRESETS``; ``load_style`` accepts ``None``, a preset name, a
``Style`` instance, a dict (with optional ``"extends"``) or a path to a JSON
file with the same schema, so future styles can be added either as code
presets or as user-provided configuration files.
"""

import json
import os
from dataclasses import dataclass, field, fields, replace
from typing import Any, Dict, Optional, Union

from csdb2snfg.snfg.symbols import glycan_color, glycan_dict

# Pastel "dimmed" palette used for non-highlighted elements, keyed by COLOR
# NAME so it works with any base palette. Values follow the glycowork
# transparent palette (glycowork/motif/draw.py col_dict_transparent).
DEFAULT_DIM_PALETTE: Dict[str, str] = {
    "White": "#FFFFFF",
    "Blue": "#CDE7EF",
    "Green": "#CDE9DF",
    "Yellow": "#FFF6DE",
    "LightBlue": "#EEF8FB",
    "Pink": "#FDF0F1",
    "Purple": "#F1E6ED",
    "Brown": "#F1E9E5",
    "Orange": "#FDE7E0",
    "Red": "#F7E0E0",
    "CRed": "#EFD5DA",
    "COrange": "#FBE7D8",
}

DEFAULT_COLOR_HEX = "#FFFFFF"


@dataclass(frozen=True)
class Style:
    """Immutable bundle of all SNFG rendering style knobs.

    Numeric/color fields default to ``None`` = backend-native literal (see
    module docstring). Dict sections merge key-wise in :meth:`from_dict`.
    """

    name: str = "custom"

    # --- color tables -------------------------------------------------------
    palette: Dict[str, str] = field(default_factory=lambda: dict(glycan_color))
    dim_palette: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_DIM_PALETTE))
    mono_styles: Dict[str, list] = field(default_factory=lambda: dict(glycan_dict))
    default_shape: str = "FCircle"
    default_color_name: str = "White"

    # --- node outline (None = backend-native: mpl 'black'/rc lw, pptx '000000'/0.25pt) ---
    node_stroke_color: Optional[str] = None
    node_stroke_width: Optional[float] = None

    # --- links / edges (None = backend-native: mpl 'black' lw=1, pptx 000000 Pt(1)) ---
    link_color: Optional[str] = None
    link_width: Optional[float] = None
    link_label_color: Optional[str] = None

    # --- fuzzy boxes (None = backend-native: mpl '#dddddd'/'black' lw=0.8,
    #     pptx '#DDDDDD'/'000000' 0.75pt) ---
    fuzzy_box_color: Optional[str] = None
    fuzzy_box_line_color: Optional[str] = None
    fuzzy_box_line_width: Optional[float] = None

    # --- repeat brackets (None = backend-native: mpl 'black' lw=0.8,
    #     pptx '#000000' vector line) ---
    bracket_color: Optional[str] = None
    bracket_width: Optional[float] = None

    # --- dimmed variants, used only when a highlight plan is active ---------
    dim_node_stroke_color: str = "#D9D9D9"
    dim_link_color: str = "#D9D9D9"
    dim_link_label_color: str = "#BFBFBF"
    dim_fuzzy_box_color: str = "#F0F0F0"
    dim_fuzzy_box_line_color: str = "#D9D9D9"
    dim_bracket_color: str = "#D9D9D9"

    def resolve(self, mono) -> tuple:
        """mono -> (comp, color_hex); same lookup/fallback logic as geometry.resolve_mono."""
        comp, color_name = self.mono_styles.get(mono, (self.default_shape, self.default_color_name))
        return comp, self.palette.get(color_name, DEFAULT_COLOR_HEX)

    def resolve_dim(self, mono) -> tuple:
        """mono -> (comp, color_hex) with the dimmed palette.

        A color name missing from dim_palette falls back to the base hex, so
        custom palettes never lose elements when highlighted.
        """
        comp, color_name = self.mono_styles.get(mono, (self.default_shape, self.default_color_name))
        hex_ = self.dim_palette.get(color_name)
        if hex_ is None:
            hex_ = self.palette.get(color_name, DEFAULT_COLOR_HEX)
        return comp, hex_

    # --- construction -------------------------------------------------------

    _DICT_SECTIONS = ("palette", "dim_palette", "mono_styles")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Style":
        """Build a Style from a plain dict.

        Semantics:
        - optional ``"extends"``: preset name (str) or nested dict, resolved
          recursively; without it the base is ``PRESETS['default']``;
        - scalar keys replace; dict sections (palette/dim_palette/mono_styles)
          merge key-wise over the base;
        - unknown top-level keys raise ``ValueError`` (typo guard); unknown
          color names / monosaccharides inside sections are allowed
          (forward-compatible) and resolve lazily with fallbacks.
        """
        d = dict(d)
        extends = d.pop("extends", None)
        if extends is None:
            base = PRESETS["default"]
        elif isinstance(extends, str):
            base = load_style(extends)
        elif isinstance(extends, dict):
            base = cls.from_dict(extends)
        elif isinstance(extends, Style):
            base = extends
        else:
            raise ValueError(
                f"'extends' must be a preset name, dict or Style, got {type(extends).__name__}"
            )

        known = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(f"unknown style keys: {unknown}; known keys: {sorted(known)}")

        changes: Dict[str, Any] = {}
        for key, value in d.items():
            current = getattr(base, key)
            if key in cls._DICT_SECTIONS:
                if not isinstance(value, dict):
                    raise ValueError(
                        f"style section {key!r} must be a dict, got {type(value).__name__}"
                    )
                merged = dict(current)
                merged.update(value)
                changes[key] = merged
            else:
                changes[key] = value
        return replace(base, **changes)

    @classmethod
    def from_json(cls, path: str) -> "Style":
        """Load a style from a JSON file (same schema as :meth:`from_dict`)."""
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"style JSON must be an object, got {type(data).__name__}: {path}")
        return cls.from_dict(data)


def _build_presets() -> Dict[str, Style]:
    """Construct the built-in preset table (name -> Style) at import time."""
    return {
        # Current built-in appearance: SNFG palette identical to
        # GlycoWorkbench's conf/residue_styles_snfg color table; every stroke
        # knob left at backend-native defaults.
        "default": Style(name="default"),
        # GlycoWorkbench reference appearance: same palette (verified equal)
        # plus GWB's explicit BasicStroke(1) references for node outline and
        # linkage lines (GraphicOptions NODE_SIZE=22, BasicStroke(1)).
        "glycoworkbench": Style(name="glycoworkbench", node_stroke_width=1.0, link_width=1.0),
    }


PRESETS: Dict[str, Style] = _build_presets()


def load_style(spec: Union[None, str, dict, Style]) -> Style:
    """Resolve a user-facing style specification into a Style.

    Accepts:
    - ``None`` -> ``PRESETS['default']``;
    - a :class:`Style` instance -> returned as-is;
    - a preset name str (case-insensitive) -> that preset;
    - a dict -> :meth:`Style.from_dict`;
    - a str path to an existing file or ending in ``.json`` -> :meth:`Style.from_json`.
    """
    if spec is None:
        return PRESETS["default"]
    if isinstance(spec, Style):
        return spec
    if isinstance(spec, dict):
        return Style.from_dict(spec)
    if isinstance(spec, str):
        preset = PRESETS.get(spec.casefold())
        if preset is not None:
            return preset
        if os.path.exists(spec) or spec.endswith(".json"):
            return Style.from_json(spec)
        raise ValueError(
            f"unknown style {spec!r}: not a preset {sorted(PRESETS)}, "
            f"not an existing path, and does not end with .json"
        )
    raise TypeError(f"cannot load style from {type(spec).__name__}")
