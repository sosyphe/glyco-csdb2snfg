"""CLI entry point for csdb2snfg."""

import argparse
import json
import os
import sys
from typing import List, Tuple


def _get_version() -> str:
    """Return the package version string (lazy import keeps startup light)."""
    from csdb2snfg import __version__

    return __version__


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    """Add the -c/--csdb and -f/--file input options shared by all subcommands."""
    parser.add_argument(
        "-c",
        "--csdb",
        type=str,
        default=None,
        help="CSDB linear notation string",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        default=None,
        help="File with CSDB strings (one per line)",
    )


def _add_image_subcommand(subparsers) -> None:
    """Register the 'image' subcommand (PNG/SVG rendering)."""
    img = subparsers.add_parser("image", help="Render SNFG diagram as PNG/SVG image")
    _add_input_args(img)
    img.add_argument(
        "-o",
        "--output",
        type=str,
        default=".",
        help="Output directory (default: current directory)",
    )
    img.add_argument(
        "--format",
        choices=["png", "svg"],
        default="png",
        help="Output format (default: png)",
    )
    img.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="DPI for PNG output (default: 150)",
    )
    _add_render_args(img)


def _add_pptx_subcommand(subparsers) -> None:
    """Register the 'pptx' subcommand (PowerPoint export)."""
    pptx = subparsers.add_parser("pptx", help="Export SNFG diagram to PowerPoint")
    _add_input_args(pptx)
    pptx.add_argument(
        "-o",
        "--output",
        type=str,
        default=".",
        help="Output directory (default: current directory)",
    )
    pptx.add_argument(
        "--template",
        type=str,
        default=None,
        help="Path to .pptx/.potx template file",
    )
    _add_render_args(pptx)


def _add_parse_subcommand(subparsers) -> None:
    """Register the 'parse' subcommand (JSON AST dump)."""
    parse_cmd = subparsers.add_parser("parse", help="Parse CSDB string and output JSON AST")
    _add_input_args(parse_cmd)
    parse_cmd.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation (default: 2)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``csdb2snfg`` argument parser (image / pptx / parse subcommands)."""
    parser = argparse.ArgumentParser(
        prog="csdb2snfg",
        description="Convert CSDB linear notation to SNFG glycan diagrams.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_image_subcommand(subparsers)
    _add_pptx_subcommand(subparsers)
    _add_parse_subcommand(subparsers)
    return parser


def _add_render_args(parser: argparse.ArgumentParser) -> None:
    """Add common rendering options to a subparser."""
    parser.add_argument(
        "--ratio",
        type=float,
        default=1,
        help="Branch scaling ratio (default: 1)",
    )
    parser.add_argument(
        "--mono-size",
        type=float,
        default=0.3,
        help="Monosaccharide node size (default: 0.3)",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=8,
        help="Label font size (default: 8)",
    )
    parser.add_argument(
        "--font-family",
        type=str,
        default="sans-serif",
        help="Font family (default: sans-serif)",
    )
    parser.add_argument(
        "--no-legend",
        action="store_true",
        help="Do not draw the monosaccharide legend",
    )
    parser.add_argument(
        "--compact-repeat",
        action="store_true",
        help="Show repeat units as [unit]n instead of expanding",
    )
    parser.add_argument(
        "--split-fuzzy",
        action="store_true",
        help="Expand <<A|B>>/<A|B> fuzzy blocks: the merged structure and "
        "each variant get their own image/slide",
    )
    parser.add_argument(
        "--style",
        type=str,
        default=None,
        metavar="NAME_OR_PATH",
        help="Style preset name ('default', 'glycoworkbench') or path to a "
        "JSON style file (default: built-in 'default' style)",
    )
    parser.add_argument(
        "--node-size",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Node radius in abstract layout units (image: overrides "
        "--mono-size; pptx: overrides automatic node sizing)",
    )
    parser.add_argument(
        "--node-stroke-width",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Node outline width in points (default: backend native)",
    )
    parser.add_argument(
        "--link-width",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Edge line width in points (default: backend native)",
    )
    parser.add_argument(
        "--no-linkage",
        action="store_true",
        help="Do not draw linkage labels on edges (XOR/OR mode labels and repeat counts are kept)",
    )
    parser.add_argument(
        "--highlight",
        type=str,
        default=None,
        metavar="MOTIF",
        help="CSDB substructure motif to highlight; non-matching elements "
        "are dimmed ('?' wildcards allowed, e.g. 'bDGlcp(1-?)?DGlc')",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        metavar="END",
        help="Reducing-end (right side) marker: 'freeEnd' (squiggle), "
        "'redEnd' (squiggle + O, i.e. reduced end/alditol) or any other "
        "text drawn as a label (e.g. PA, 2AB). Names match exactly.",
    )
    parser.add_argument(
        "--show-unknown",
        action="store_true",
        help="Render '?' markers for unknown anomeric configuration / linkage "
        "positions parsed from the CSDB string (edge-label slots)",
    )


def _expand_jobs(strings: List[str], split_fuzzy: bool) -> List[Tuple[str, str]]:
    """-> [(base_name, csdb)]: base naming follows the legacy rule (single
    input 'snfg' / multiple inputs 'snfg_NNN'); with split, each input
    additionally yields (base + '_vK', variant K).
    """
    from csdb2snfg.csdb.fuzzy import split_fuzzy_variants

    jobs = []
    for i, csdb in enumerate(strings):
        base = "snfg" if len(strings) == 1 else f"snfg_{i + 1:03d}"
        jobs.append((base, csdb))
        if split_fuzzy:
            for k, v in enumerate(split_fuzzy_variants(csdb)):
                if v != csdb:
                    jobs.append((f"{base}_v{k + 1}", v))
    return jobs


def _get_csdb_strings(args: argparse.Namespace) -> List[str]:
    """Resolve CSDB strings from -c/--csdb or -f/--file."""
    strings = []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            strings = [
                line.strip() for line in f if line.strip() and not line.strip().startswith("#")
            ]
    if args.csdb:
        strings.append(args.csdb)
    if not strings:
        print(
            "Error: provide a CSDB string with -c/--csdb or use -f/--file",
            file=sys.stderr,
        )
        sys.exit(1)
    return strings


def cmd_image(args: argparse.Namespace) -> None:
    """Render SNFG diagrams as PNG or SVG images."""
    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt

    from csdb2snfg.csdb.parser import parse_csdb_linear
    from csdb2snfg.export.image import draw_snfg

    strings = _get_csdb_strings(args)
    os.makedirs(args.output, exist_ok=True)

    jobs = _expand_jobs(strings, args.split_fuzzy)
    mono_size = args.node_size if args.node_size is not None else args.mono_size
    render_kw = dict(
        style=args.style,
        node_stroke_width=args.node_stroke_width,
        link_width=args.link_width,
        show_linkage=not args.no_linkage,
        highlight_motif=args.highlight,
        end=args.end,
        show_unknown=args.show_unknown,
    )
    # Count of caught exceptions; parse warnings and empty-parse skips are
    # NOT failures and must keep the exit code at 0.
    failures = 0
    for i, (base, csdb) in enumerate(jobs):
        try:
            tree = parse_csdb_linear(csdb)
            if tree is None:
                print(f"[{i + 1}] Warning: empty parse result, skipping", file=sys.stderr)
                continue

            if args.format == "svg":
                path = os.path.join(args.output, f"{base}.svg")
                draw_snfg(
                    tree,
                    mono_size=mono_size,
                    ratio=args.ratio,
                    font_size=args.font_size,
                    font_family=args.font_family,
                    save_svg=path,
                    add_legend=not args.no_legend,
                    compact_repeat=args.compact_repeat,
                    **render_kw,
                )
            else:
                path = os.path.join(args.output, f"{base}.png")
                fig, ax = draw_snfg(
                    tree,
                    mono_size=mono_size,
                    ratio=args.ratio,
                    font_size=args.font_size,
                    font_family=args.font_family,
                    add_legend=not args.no_legend,
                    compact_repeat=args.compact_repeat,
                    **render_kw,
                )
                fig.savefig(path, dpi=args.dpi, bbox_inches="tight")
                plt.close(fig)

            print(f"[{i + 1}/{len(jobs)}] Saved {path}")
        except Exception as e:
            # Broad catch is intentional: a batch CLI must finish the
            # remaining entries; the failure surfaces via a non-zero exit.
            print(f"[{i + 1}] Error: {e}", file=sys.stderr)
            print(f"  Input: {csdb}", file=sys.stderr)
            failures += 1

    if failures:
        sys.exit(1)


def cmd_pptx(args: argparse.Namespace) -> None:
    """Export SNFG diagrams to PowerPoint."""
    from csdb2snfg.export.pptx import generate_snfg_pptx

    strings = _get_csdb_strings(args)
    os.makedirs(args.output, exist_ok=True)

    buf = generate_snfg_pptx(
        strings,
        template_path=args.template,
        ratio=args.ratio,
        font_size=args.font_size,
        font_family=args.font_family,
        compact_repeat=args.compact_repeat,
        split_fuzzy=args.split_fuzzy,
        style=args.style,
        node_size=args.node_size,
        node_stroke_width=args.node_stroke_width,
        link_width=args.link_width,
        show_linkage=not args.no_linkage,
        highlight_motif=args.highlight,
        end=args.end,
        show_unknown=args.show_unknown,
    )

    if args.split_fuzzy:
        from csdb2snfg.csdb.fuzzy import expand_fuzzy

        n_slides = len(expand_fuzzy(strings))
    else:
        n_slides = len(strings)

    if len(strings) == 1:
        filename = "snfg.pptx"
    else:
        filename = "snfg_diagrams.pptx"

    path = os.path.join(args.output, filename)
    with open(path, "wb") as f:
        f.write(buf.read())

    print(f"Saved {path} ({n_slides} slide(s))")


def cmd_parse(args: argparse.Namespace) -> None:
    """Parse CSDB strings and output JSON AST."""
    from csdb2snfg.csdb.parser import parse_csdb_linear

    strings = _get_csdb_strings(args)

    # Count of caught exceptions; empty-parse warnings are NOT failures and
    # must keep the exit code at 0.
    failures = 0
    for i, csdb in enumerate(strings):
        try:
            tree = parse_csdb_linear(csdb)
            if tree is None:
                print(f"[{i + 1}] Warning: empty parse result", file=sys.stderr)
                continue
            result = tree.to_dict()
            print(json.dumps(result, indent=args.indent, ensure_ascii=False))
            if len(strings) > 1:
                print()  # blank line between multiple results
        except Exception as e:
            # Broad catch is intentional: process every input; the failure
            # surfaces via a non-zero exit code.
            print(f"[{i + 1}] Error: {e}", file=sys.stderr)
            print(f"  Input: {csdb}", file=sys.stderr)
            failures += 1

    if failures:
        sys.exit(1)


def main() -> None:
    """CLI entry point: parse argv and dispatch to the chosen subcommand."""
    # Surface library warnings (e.g. dropped CSDB fragments) on stderr, but
    # never clobber logging configured by an embedding application.
    import logging

    if not logging.getLogger().handlers:
        logging.basicConfig(
            stream=sys.stderr, level=logging.WARNING, format="%(name)s: %(levelname)s: %(message)s"
        )

    parser = build_parser()
    args = parser.parse_args()
    dispatch = {
        "image": cmd_image,
        "pptx": cmd_pptx,
        "parse": cmd_parse,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
