# csdb2snfg

[![PyPI Version](https://img.shields.io/pypi/v/glyco-csdb2snfg)](https://pypi.org/project/glyco-csdb2snfg)
[![PyPI Downloads](https://static.pepy.tech/badge/glyco-csdb2snfg)](https://pepy.tech/project/glyco-csdb2snfg)
[![Bioconda Version](https://img.shields.io/conda/vn/bioconda/glyco-csdb2snfg.svg)](https://anaconda.org/bioconda/glyco-csdb2snfg)
[![Bioconda Downloads](https://img.shields.io/conda/dn/bioconda/glyco-csdb2snfg.svg)](https://anaconda.org/bioconda/glyco-csdb2snfg)

> Convert [CSDB](https://csdb.glycoscience.ru/) linear notation to SNFG (Symbol Nomenclature for Glycans) diagrams.

## Installation

```bash
pip install glyco-csdb2snfg                  # PyPI (stable)
conda install -c bioconda glyco-csdb2snfg    # Bioconda
pip install git+https://github.com/sosyphe/glyco-csdb2snfg.git  # source
```


## Examples

**Simple linear chain**

`-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/simple_linear.svg" width="300">

**Branched unit**

`-4)[βDGalp(1-6)]αDManp(1-4)[βDGalp(1-3)]αDManp(1-4)βDGlcNAcp(1-4)βDGlcNAcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/branched.svg" width="300">

**Repeating unit** (`/n=3/`, compact form)

`-4)βDGalp(1-4)/βDGalp(1-4)/n=3/βDGalp(1-4)αDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/repeating.svg" width="300">

**With modifiers** (Me, Ac)

`-4)[Me(1-3)]αDGalp(1-6)[Ac(1-3)]αDGalp(1-6)αDGalp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/with_modifiers.svg" width="300">

**Complex multi-branched**

`-3)[[αDGalp(1-6)]αLArap(1-3)αLAraf(1-6)]βDGalp(1-3)[Me(1-4)βDGalp(1-4)βDGalp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDXylp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDManp(1-6)]βDGalp(1-3)βDGalp(1-3)βDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/complex_branched.svg" width="300">

**Fuzzy unit** (XOR alternatives)

`-4)βDGalp(1-4)βDGalp(1-3)[<<αLAraf(1-6)|βLAraf(1-6)>>]βDGalp(1-3)αDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/fuzzy.svg" width="300">

## Quick Start

```bash
csdb2snfg image -c="-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-" --format png -o output/  # PNG/SVG
csdb2snfg pptx  -c="-4)βDGalp(1-4)βDGalp(1-3)αDGalp(1-" -o output/               # one slide per glycan
csdb2snfg parse -c="-4)βDGlcp(1-4)αDGlcp(1-"                                     # JSON AST on stdout
csdb2snfg image -f glycans.txt -o output/     # batch: one string per line, # comments
```

> **Note:** Use `-c="..."` (with `=`) to prevent argparse from treating the leading `-` as a flag.

```python
from csdb2snfg import parse_csdb_linear, draw_snfg, generate_snfg_pptx

tree = parse_csdb_linear("-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-")

fig, ax = draw_snfg(tree)                       # matplotlib figure
fig.savefig("glycan.png", dpi=300, bbox_inches="tight")
draw_snfg(tree, save_svg="glycan.svg")          # or SVG directly

buf = generate_snfg_pptx(["-4)βDGlcp(1-4)αDGlcp(1-"])
with open("glycans.pptx", "wb") as f:
    f.write(buf.read())
```

## Features

- **Parse** CSDB linear strings into a structured AST (JSON output)
- **Render** SNFG diagrams as PNG/SVG images; **export** PowerPoint (PPTX) with vector shapes
- Supports branching, repeating units (`/n=N/`), modifiers (Me, Ac) and fuzzy structural alternatives (`<A|B>` OR, `<<A|B>>` XOR)
- **Styles**: presets (`default`, `glycoworkbench`), per-element color/width overrides via dict or JSON file; node size and stroke controls
- **Motif highlighting**: dim everything except a matched CSDB substructure
- **Reducing-end markers**: `freeEnd`/`redEnd` squiggles or arbitrary text labels
- **Unknown markers**: `?` (unknown anomeric configuration / linkage position) is parsed into the AST and rendered with `show_unknown` / `--show-unknown`
- **Parse notices**: dropped fragments (unknown sugar names like `?DGro`, non-stoichiometric suffixes like `40%`) are reported via `logging`

## Known Limitations

- Visual overlap may occur when a single residue has ≥3 consecutive linkages, or between branches in dense structures
- Highlight motifs may not contain fuzzy (`<<|>>`/`<|>`) or repeat (`/…/n=…/`) blocks; `?` wildcards the anomeric configuration / linkage site and `X` the absolute configuration
- Only **orthogonal (horizontal/vertical) chain layout**; no diagonal or angled linkages

## Command-Line Interface

All three subcommands accept a single string (`-c/--csdb`) or a batch file
(`-f/--file`). Single inputs write `snfg.<ext>`; batches write `snfg_001`,
`snfg_002`, … (PPTX: `snfg.pptx` / `snfg_diagrams.pptx`). Parse warnings go to
stderr; library users configure `logging.getLogger("csdb2snfg")` themselves.

| Flag (`image` / `pptx`) | Effect |
| --- | --- |
| `--format`, `--dpi` | Output format `png`/`svg` (image only) and resolution |
| `--template PATH` | Reuse masters/layouts from a `.pptx`/`.potx` (pptx only) |
| `--style NAME_OR_PATH` | Preset (`default`, `glycoworkbench`) or JSON style file |
| `--highlight MOTIF` | Dim everything except a matched substructure; `?` wildcards |
| `--end END` | Reducing-end marker: `freeEnd`, `redEnd` or any text label |
| `--compact-repeat` | Show repeat units as `[unit]n` instead of expanding |
| `--split-fuzzy` | Merged structure and each fuzzy variant get their own image/slide |
| `--no-linkage`, `--no-legend` | Hide edge linkage labels / the monosaccharide legend |
| `--show-unknown` | Render `?` for unknown anomeric config / linkage positions |
| `--node-size`, `--node-stroke-width`, `--link-width` | Node radius (layout units), line widths (points) |
| `--ratio`, `--font-size`, `--font-family` | Branch scaling and label typography |

## Python API

`import csdb2snfg` is lazy: matplotlib / python-pptx are imported only when
`draw_snfg` / `generate_snfg_pptx` is first accessed.

```python
from csdb2snfg import parse_csdb_linear, print_ast, draw_snfg, generate_snfg_pptx

tree = parse_csdb_linear("-4)βDGlcp(1-4)αDGlcp(1-")  # None for an empty string
data = tree.to_dict()        # JSON-serializable AST
print_ast(tree)              # indented text dump (debug aid)

fig, ax = draw_snfg(tree)    # (fig, ax): further matplotlib customization stays available
buf = generate_snfg_pptx(["-4)βDGlcp(1-4)αDGlcp(1-"], template_path=None)
```

## Feature Guide

Every option below is both a keyword argument on `draw_snfg` / `generate_snfg_pptx` and a CLI flag; every default reproduces the historical appearance exactly.

### Styles and presets

`-4)βDGlcp(1-4)αDGlcp(1-` rendered with `--style glycoworkbench --node-stroke-width 1.5 --link-width 2`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/style_glycoworkbench.svg" width="300">

```bash
csdb2snfg image -c="-4)βDGlcp(1-4)αDGlcp(1-" --style glycoworkbench \
    --node-stroke-width 1.5 --link-width 2 -o output/
```

```python
draw_snfg(tree, style="glycoworkbench")            # built-in preset
draw_snfg(tree, style={"extends": "default",       # dict: scalars replace,
                       "palette": {"Blue": "#123456"},  # sections merge key-wise
                       "link_width": 2.0})
draw_snfg(tree, style="my_style.json")             # same schema as the dict
draw_snfg(tree, node_stroke_width=1.5, link_width=2, show_linkage=False)
generate_snfg_pptx([csdb], node_size=0.4)          # abstract units, like mono_size
```

Style dict/JSON keys (all optional): `name`, `extends`, `palette`, `dim_palette`, `mono_styles`, plus colors/widths `node_stroke_*`, `link_color`, `link_width`, `link_label_color`, `fuzzy_box_*`, `bracket_*`. `null` means "backend-native literal", which keeps the default style byte-identical to older releases. Unknown top-level keys are rejected; unknown color names / monosaccharides are allowed and fall back.

### Motif highlighting

Matched elements keep the full palette, everything else dims to pastels. A motif is itself a CSDB string; `?` wildcards the anomeric configuration or a linkage site, `X` the absolute configuration. A motif with no match logs a warning and renders normally.

`-4)βDGalp(1-4)βDGalp(1-3)αDGalp(1-` with `--highlight "βDGalp(1-4)βDGalp"`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/highlight.svg" width="300">

```bash
csdb2snfg image -c="-4)βDGalp(1-4)βDGalp(1-3)αDGalp(1-" \
    --highlight "βDGalp(1-4)βDGalp" -o output/
```

```python
tree = parse_csdb_linear("-4)βDGalp(1-4)βDGalp(1-3)αDGalp(1-")
draw_snfg(tree, highlight_motif="βDGalp(1-4)βDGalp")  # exact substructure
draw_snfg(tree, highlight_motif="βDGalp(1-?)?DGalp")  # ? wildcards
```

### Fuzzy residues

`<<A|B>>` (XOR) and `<A|B>` (OR) draw all candidates together in a grey box by default; `--split-fuzzy` / `split_fuzzy=True` emits the merged structure *and* each resolved variant as separate images/slides.

```bash
csdb2snfg image -c="-4)βDGalp(1-3)[<<αLAraf(1-6)|βLAraf(1-6)>>]βDGalp(1-" \
    --split-fuzzy -o output/
```

```python
from csdb2snfg import expand_fuzzy, split_fuzzy_variants

csdb = "-4)βDGalp(1-3)[<<αLAraf(1-6)|βLAraf(1-6)>>]βDGalp(1-"
for variant in expand_fuzzy([csdb]):   # [merged original, variant1, ...] per input
    draw_snfg(parse_csdb_linear(variant), add_legend=False)
split_fuzzy_variants(csdb)             # plain variants only (Cartesian product)
generate_snfg_pptx([csdb], split_fuzzy=True)
```

### End markers, repeats and unknowns

`-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-` with `end="freeEnd"` / `end="redEnd"` / `end="2AB"` (left to right):

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/end_freeend.svg" width="220"> <img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/end_redend.svg" width="220"> <img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/end_2ab.svg" width="220">

- `end="freeEnd"` / `end="redEnd"` draw the GlycoWorkbench squiggle / squiggle with a centered `O` (reduced end, alditol); any other non-empty string (`PA`, `2AB`) becomes a text label.
- `/unit/n=N/` repeats: the Python API renders the compact `[unit]ₙ` form by default (`compact_repeat=True`), the CLI expands into N copies unless `--compact-repeat` is given; an unknown count (`n=?`) draws a single unit plus the bracket.
- `?` in the source (`?DGalp`, `(1-?)`) is kept in the AST; `show_unknown=True` / `--show-unknown` renders it in the edge-label slots.

## License

MIT License - see [LICENSE](LICENSE) for details.
