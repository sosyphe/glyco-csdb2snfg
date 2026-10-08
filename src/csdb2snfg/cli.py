"""CLI entry point for csdb2snfg."""

import argparse
import json
import os
import sys


def _get_version():
    from csdb2snfg import __version__
    return __version__


def build_parser():
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

    # --- image subcommand ---
    img = subparsers.add_parser(
        "image", help="Render SNFG diagram as PNG/SVG image"
    )
    img.add_argument(
        "-c", "--csdb", type=str, default=None,
        help="CSDB linear notation string",
    )
    img.add_argument(
        "-f", "--file", type=str, default=None,
        help="File with CSDB strings (one per line)",
    )
    img.add_argument(
        "-o", "--output", type=str, default=".",
        help="Output directory (default: current directory)",
    )
    img.add_argument(
        "--format", choices=["png", "svg"], default="png",
        help="Output format (default: png)",
    )
    img.add_argument(
        "--dpi", type=int, default=150,
        help="DPI for PNG output (default: 150)",
    )
    _add_render_args(img)

    # --- pptx subcommand ---
    pptx = subparsers.add_parser(
        "pptx", help="Export SNFG diagram to PowerPoint"
    )
    pptx.add_argument(
        "-c", "--csdb", type=str, default=None,
        help="CSDB linear notation string",
    )
    pptx.add_argument(
        "-f", "--file", type=str, default=None,
        help="File with CSDB strings (one per line)",
    )
    pptx.add_argument(
        "-o", "--output", type=str, default=".",
        help="Output directory (default: current directory)",
    )
    pptx.add_argument(
        "--template", type=str, default=None,
        help="Path to .pptx/.potx template file",
    )
    _add_render_args(pptx)

    # --- parse subcommand ---
    parse_cmd = subparsers.add_parser(
        "parse", help="Parse CSDB string and output JSON AST"
    )
    parse_cmd.add_argument(
        "-c", "--csdb", type=str, default=None,
        help="CSDB linear notation string",
    )
    parse_cmd.add_argument(
        "-f", "--file", type=str, default=None,
        help="File with CSDB strings (one per line)",
    )
    parse_cmd.add_argument(
        "--indent", type=int, default=2,
        help="JSON indentation (default: 2)",
    )

    return parser


def _add_render_args(parser):
    """Add common rendering options to a subparser."""
    parser.add_argument(
        "--ratio", type=float, default=1,
        help="Branch scaling ratio (default: 1)",
    )
    parser.add_argument(
        "--mono-size", type=float, default=0.3,
        help="Monosaccharide node size (default: 0.3)",
    )
    parser.add_argument(
        "--font-size", type=int, default=8,
        help="Label font size (default: 8)",
    )
    parser.add_argument(
        "--font-family", type=str, default="sans-serif",
        help="Font family (default: sans-serif)",
    )
    parser.add_argument(
        "--no-legend", action="store_true",
        help="Do not draw the monosaccharide legend",
    )
    parser.add_argument(
        "--compact-repeat", action="store_true",
        help="Show repeat units as [unit]n instead of expanding",
    )


def _get_csdb_strings(args):
    """Resolve CSDB strings from -c/--csdb or -f/--file."""
    strings = []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            strings = [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
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


def cmd_image(args):
    """Render SNFG diagrams as PNG or SVG images."""
    import matplotlib
    matplotlib.use("Agg")

    from csdb2snfg.csdb.parser import parse_csdb_linear
    from csdb2snfg.export.image import draw_snfg

    strings = _get_csdb_strings(args)
    os.makedirs(args.output, exist_ok=True)

    for i, csdb in enumerate(strings):
        try:
            tree = parse_csdb_linear(csdb)
            if tree is None:
                print(f"[{i + 1}] Warning: empty parse result, skipping", file=sys.stderr)
                continue

            if len(strings) == 1:
                base = "snfg"
            else:
                base = f"snfg_{i + 1:03d}"

            if args.format == "svg":
                path = os.path.join(args.output, f"{base}.svg")
                draw_snfg(
                    tree,
                    mono_size=args.mono_size,
                    ratio=args.ratio,
                    font_size=args.font_size,
                    font_family=args.font_family,
                    save_svg=path,
                    add_legend=not args.no_legend,
                    compact_repeat=args.compact_repeat,
                )
            else:
                path = os.path.join(args.output, f"{base}.png")
                fig, ax = draw_snfg(
                    tree,
                    mono_size=args.mono_size,
                    ratio=args.ratio,
                    font_size=args.font_size,
                    font_family=args.font_family,
                    add_legend=not args.no_legend,
                    compact_repeat=args.compact_repeat,
                )
                fig.savefig(path, dpi=args.dpi, bbox_inches="tight")
                import matplotlib.pyplot as plt
                plt.close(fig)

            print(f"[{i + 1}/{len(strings)}] Saved {path}")
        except Exception as e:
            print(f"[{i + 1}] Error: {e}", file=sys.stderr)
            print(f"  Input: {csdb}", file=sys.stderr)


def cmd_pptx(args):
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
    )

    if len(strings) == 1:
        filename = "snfg.pptx"
    else:
        filename = "snfg_diagrams.pptx"

    path = os.path.join(args.output, filename)
    with open(path, "wb") as f:
        f.write(buf.read())

    print(f"Saved {path} ({len(strings)} slide(s))")


def cmd_parse(args):
    """Parse CSDB strings and output JSON AST."""
    from csdb2snfg.csdb.parser import parse_csdb_linear

    strings = _get_csdb_strings(args)

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
            print(f"[{i + 1}] Error: {e}", file=sys.stderr)
            print(f"  Input: {csdb}", file=sys.stderr)


def main():
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
