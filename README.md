# csdb2snfg

> Convert [CSDB](https://csdb.glycoscience.ru/) linear notation to SNFG (Symbol Nomenclature for Glycans) diagrams.

## Features

- **Parse** CSDB linear strings into structured AST (JSON output)
- **Render** SNFG diagrams as PNG/SVG images
- **Export** PowerPoint (PPTX) with vector shapes
- Supports branching, repeating units (`/n=N/`), modifiers (Me, Ac)

### Current Limitations

- Only standard CSDB syntax and `repeat=n` are supported. Fuzzy/XOR alternatives (`<...|...>`, `<<...|...>>`) are **not yet supported**.
- Only **orthogonal (horizontal/vertical) chain layout** is supported. Diagonal or angled linkages are not available.

## Installation

From PyPI (stable):

```bash
pip install glyco-csdb2snfg
```

From source (development):

```bash
pip install git+https://github.com/sosyphe/glyco-csdb2snfg.git
```

## Quick Start

```bash
# Render to PNG
csdb2snfg image -c="-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-" --format png -o output/

# Export to PowerPoint
csdb2snfg pptx -c="-4)βDGalp(1-4)βDGalp(1-3)αDGalp(1-" -o output/

# Parse to JSON AST
csdb2snfg parse -c="-4)βDGlcp(1-4)αDGlcp(1-"

# Batch processing (one CSDB string per line, # for comments)
csdb2snfg image -f glycans.txt --format png -o output/
```

> **Note:** Use `-c="..."` (with `=`) to prevent argparse from treating the leading `-` as a flag.

### Python API

```python
from csdb2snfg import parse_csdb_linear, draw_snfg, generate_snfg_pptx

tree = parse_csdb_linear("-4)βDGlcp(1-4)αDGlcp(1-")

# Render to matplotlib figure
fig, ax = draw_snfg(tree)
fig.savefig("glycan.png", dpi=300, bbox_inches="tight")

# Save SVG directly
draw_snfg(tree, save_svg="glycan.svg")

# Export to PowerPoint
buf = generate_snfg_pptx(["-4)βDGlcp(1-4)αDGlcp(1-"])
with open("glycans.pptx", "wb") as f:
    f.write(buf.read())
```

## Examples

**Simple linear chain**

`-4)βDGlcp(1-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/simple_linear.svg" width="400">

**Branched N-Glycan core**

`-4)[βDGalp(1-6)]αDManp(1-4)[βDGalp(1-3)]αDManp(1-4)βDGlcNAcp(1-4)βDGlcNAcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/branched.svg" width="500">

**Repeating unit** (`/n=3/`)

`-4)βDGalp(1-4)/βDGalp(1-4)/n=3/βDGalp(1-4)αDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/repeating.svg" width="500">

**With modifiers** (Me, Ac)

`-4)[Me(1-3)]αDGalp(1-6)[Ac(1-3)]αDGalp(1-6)αDGalp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/with_modifiers.svg" width="400">

**Complex multi-branched**

`-3)[[αDGalp(1-6)]αLArap(1-3)αLAraf(1-6)]βDGalp(1-3)[Me(1-4)βDGalp(1-4)βDGalp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDXylp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDManp(1-6)]βDGalp(1-3)βDGalp(1-3)βDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/complex_branched.svg" width="500">

## License

MIT License - see [LICENSE](LICENSE) for details.
