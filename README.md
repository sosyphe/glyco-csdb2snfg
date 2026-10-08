# csdb2snfg

[![PyPI Version](https://img.shields.io/pypi/v/glyco-csdb2snfg)](https://pypi.org/project/glyco-csdb2snfg)
[![PyPI Downloads](https://static.pepy.tech/badge/glyco-csdb2snfg)](https://pepy.tech/project/glyco-csdb2snfg)
[![Bioconda Version](https://img.shields.io/conda/vn/bioconda/glyco-csdb2snfg.svg)](https://anaconda.org/bioconda/glyco-csdb2snfg)
[![Bioconda Downloads](https://img.shields.io/conda/dn/bioconda/glyco-csdb2snfg.svg)](https://anaconda.org/bioconda/glyco-csdb2snfg)

> Convert [CSDB](https://csdb.glycoscience.ru/) linear notation to SNFG (Symbol Nomenclature for Glycans) diagrams.

## Features

- **Parse** CSDB linear strings into structured AST (JSON output)
- **Render** SNFG diagrams as PNG/SVG images
- **Export** PowerPoint (PPTX) with vector shapes
- Supports branching, repeating units (`/n=N/`, expanded or compact `[unit]n` display), modifiers (Me, Ac)

### Current Limitations

- Only standard CSDB syntax and repeating units (`/n=N/`) are supported. Fuzzy/XOR alternatives (`<...|...>`, `<<...|...>>`) are **not yet supported**.
- Only **orthogonal (horizontal/vertical) chain layout** is supported. Diagonal or angled linkages are not available.

## Installation

From PyPI (stable):

```bash
pip install glyco-csdb2snfg
```

With [uv](https://docs.astral.sh/uv/):

```bash
# Install as a global CLI tool
uv tool install glyco-csdb2snfg

# Or run directly without installing
uvx --from glyco-csdb2snfg csdb2snfg parse -c="-4)βDGlcp(1-4)αDGlcp(1-"
```

From source:

```bash
pip install git+https://github.com/sosyphe/glyco-csdb2snfg.git
```

### Development (uv)

This project uses [uv](https://docs.astral.sh/uv/) for dependency management (`pyproject.toml` + `uv.lock`).

```bash
git clone https://github.com/sosyphe/glyco-csdb2snfg.git
cd glyco-csdb2snfg

# Create .venv and install all dependencies (including dev extras)
uv sync --extra dev

# Run the CLI inside the project environment
uv run csdb2snfg --version
```

## Quick Start

```bash
# Render to PNG
csdb2snfg image -c="-4)βDGlcp(1-4)βDGlcp(1-4)αDGlcp(1-" --format png -o output/

# Export to PowerPoint
csdb2snfg pptx -c="-4)βDGalp(1-4)βDGalp(1-3)αDGalp(1-" -o output/

# Parse to JSON AST
csdb2snfg parse -c="-4)βDGlcp(1-4)αDGlcp(1-"

# Repeating unit in compact mode ([unit]n instead of expanding)
csdb2snfg image -c="-4)βDGalp(1-4)/βDGalp(1-4)/n=3/βDGalp(1-4)αDGlcp(1-" --compact-repeat -o output/

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

**Branched unit**

`-4)[βDGalp(1-6)]αDManp(1-4)[βDGalp(1-3)]αDManp(1-4)βDGlcNAcp(1-4)βDGlcNAcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/branched.svg" width="500">

**Repeating unit** (`/n=3/`)

`-4)βDGalp(1-4)/βDGalp(1-4)/n=3/βDGalp(1-4)αDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/repeating.svg" width="500">

> The image above shows the compact display: the repeat unit is drawn once with an `n=` annotation. The CLI expands the unit N times by default — pass `--compact-repeat` for the compact display (which is the default in the Python API: `draw_snfg(tree, compact_repeat=True)`).

**With modifiers** (Me, Ac)

`-4)[Me(1-3)]αDGalp(1-6)[Ac(1-3)]αDGalp(1-6)αDGalp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/with_modifiers.svg" width="400">

**Complex multi-branched**

`-3)[[αDGalp(1-6)]αLArap(1-3)αLAraf(1-6)]βDGalp(1-3)[Me(1-4)βDGalp(1-4)βDGalp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDXylp(1-6)]βDGalp(1-3)[αLAraf(1-4)βDManp(1-6)]βDGalp(1-3)βDGalp(1-3)βDGlcp(1-`

<img src="https://raw.githubusercontent.com/sosyphe/glyco-csdb2snfg/main/examples/svg/complex_branched.svg" width="500">

## License

MIT License - see [LICENSE](LICENSE) for details.
