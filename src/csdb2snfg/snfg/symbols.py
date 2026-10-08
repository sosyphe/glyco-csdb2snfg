"""SNFG symbol tables: colors, monosaccharide→shape mapping and shape geometry.

Backend-agnostic (numpy only); shared by the matplotlib renderer and the
python-pptx exporter. Extracted verbatim from the former flat renderer module.
"""

from math import pi

import numpy as np

# ------------------------------
# 颜色映射
# ------------------------------
glycan_color = {
    'White': '#FFFFFF',
    'Blue': '#0072BC',
    'Green': '#00A651',
    'Yellow': '#FFD400',
    'LightBlue': '#8FCCE9',
    'Pink': '#F69EA1',
    'Purple': '#A54399',
    'Brown': '#A17A4D',
    'Orange': '#F47920',
    'Red': '#ED1C24',
    "CRed": "#c81d3182",
    "COrange" : "#f5b48284",
}

# ------------------------------
# SNFG 单糖映射: [形状, 颜色]
# ------------------------------
glycan_dict = {
    # Filled Circle
    'Hexose':['FCircle','White'],
    'Glc':['FCircle','Blue'],
    'Man':['FCircle','Green'],
    'Gal':['FCircle','Yellow'],
    'Gul':['FCircle','Orange'],
    'Alt':['FCircle','Pink'],
    'All':['FCircle','Purple'],
    'Tal':['FCircle','LightBlue'],
    'Ido':['FCircle','Brown'],

    # Filled Square
    'HexNAc':['FSquare','White'],
    'GlcNAc':['FSquare','Blue'],
    'ManNAc':['FSquare','Green'],
    'GalNAc':['FSquare','Yellow'],
    'GulNAc':['FSquare','Orange'],
    'AltNAc':['FSquare','Pink'],
    'AllNAc':['FSquare','Purple'],
    'TalNAc':['FSquare','LightBlue'],
    'IdoNAc':['FSquare','Brown'],

    # Crossed Square
    'Hexosamine':['CSquare','White'],
    'GlcN':['CSquare','Blue'],
    'ManN':['CSquare','Green'],
    'GalN':['CSquare','Yellow'],
    'GulN':['CSquare','Orange'],
    'AltN':['CSquare','Pink'],
    'AllN':['CSquare','Purple'],
    'TalN':['CSquare','LightBlue'],
    'IdoN':['CSquare','Brown'],

    # Divided Diamond
    'Hexuronate':['DDiamond','White'],
    'GlcA':['DDiamond','Blue'],
    'ManA':['DDiamond','Green'],
    'GalA':['DDiamond','Yellow'],
    'GulA':['DDiamond','Orange'],
    'AltA':['DDiamondInv','Pink'],
    'AllA':['DDiamond','Purple'],
    'TalA':['DDiamond','LightBlue'],
    'IdoA':['DDiamondInv','Brown'],

    # Filled Triangle
    'Deoxyhexose':['FTriangle','White'],
    'Qui':['FTriangle','Blue'],
    'Rha':['FTriangle','Green'],
    '6dGul':['FTriangle','Orange'],
    '6dAlt':['FTriangle','Pink'],
    '6dTal':['FTriangle','LightBlue'],
    'Fuc':['FTriangle','Red'],

    # Divided Triangle
    'DeoxyhexNAc':['DTriangle','White'],
    'QuiNAc':['DTriangle','Blue'],
    'RhaNAc':['DTriangle','Green'],
    '6dAltNAc':['DTriangle','Pink'],
    '6dTalNAc':['DTriangle','LightBlue'],
    'FucNAc':['DTriangle','Red'],

    # Flat Rectangle
    'Di-deoxyhexose':['FRect','White'],
    'Oli':['FRect','Blue'],
    'Tyv':['FRect','Green'],
    'Abe':['FRect','Orange'],
    'Par':['FRect','Pink'],
    'Dig':['FRect','Purple'],
    'Col':['FRect','LightBlue'],

    # Filled Star
    'Pentose':['FStar','White'],
    'Ara':['FStar','Green'],
    'Lyx':['FStar','Yellow'],
    'Xyl':['FStar','Orange'],
    'Rib':['FStar','Pink'],

    # Filled Diamond
    '3-deoxy-nonulosonic acids':['FDiamond','White'],
    'Kdn':['FDiamond','Green'],
    'Neu5Ac':['FDiamond','Purple'],
    'Neu5Gc':['FDiamond','LightBlue'],
    'Neu':['FDiamond','Brown'],
    'Sia':['FDiamond','Red'],

    # Flat Diamond
    '3,9-dideoxy-nonulosonic acids':['DDiamondFlat','White'],
    'Pse':['DDiamondFlat','Green'],
    'Leg':['DDiamondFlat','Yellow'],
    'Aci':['DDiamondFlat','Pink'],
    '4eLeg':['DDiamondFlat','LightBlue'],

    # Flat Hexagon
    'Unknown':['FHexFlat','White'],
    'Bac':['FHexFlat','Blue'],
    'LDmanHep':['FHexFlat','Green'],
    'Kdo':['FHexFlat','Yellow'],
    'Dha':['FHexFlat','Orange'],
    'DDmanHep':['FHexFlat','Pink'],
    'MurNAc':['FHexFlat','Purple'],
    'MurNGc':['FHexFlat','LightBlue'],
    'Mur':['FHexFlat','Brown'],

    # Pentagon
    'Assigned':['FPentagon','White'],
    'Api':['FPentagon','Blue'],
    'Fru':['FPentagon','Green'],
    'Tag':['FPentagon','Yellow'],
    'Sor':['FPentagon','Orange'],
    'Psi':['FPentagon','Pink'],

    # 修饰基团
    "Me":["FStar4","CRed"],
    "Ac":["FDiamondFlat","COrange"],
}
MODIFIERS = {"Me", "Ac"}

# ------------------------------
# SNFG 基本形状绘制坐标
# ------------------------------
def get_shape_coords(shape, size=1.0):
    if shape == 'FCircle':
        theta = np.linspace(0, 2*pi, 50)
        return np.cos(theta)*size, np.sin(theta)*size
    elif shape in ['FSquare', 'CSquare']:
        # 内切圆半径 = size, 正方形恰好包裹同半径的圆(FCircle)
        half_side = size * 0.9
        xs = np.array([-half_side, half_side, half_side, -half_side])
        ys = np.array([-half_side, -half_side, half_side, half_side])
        return xs, ys
    elif shape in ['FTriangle','DTriangle']:
        # 等边三角形，外接圆半径 = size
        angles = np.deg2rad([90, 210, 330])  # 顶点朝上
        xs = size * np.cos(angles)
        ys = size * np.sin(angles)
        return xs, ys
    elif shape == 'FStar':
        # 正确 SNFG 五角星比例
        angles = np.linspace(0, 2*pi, 11)[:-1] + pi/2  # 10 个点，起始角 pi/2
        r_outer = size
        r_inner = size * np.sin(np.deg2rad(18)) / np.sin(np.deg2rad(54))  # 内半径比例
        xs, ys = [], []
        for i, a in enumerate(angles):
            r = r_outer if i % 2 == 0 else r_inner
            xs.append(r * np.cos(a))
            ys.append(r * np.sin(a))
        return np.array(xs), np.array(ys)
    elif shape in ['FDiamond','DDiamond','DDiamondInv','DDiamondFlat']:
        return np.array([0,1,0,-1])*size, np.array([1,0,-1,0])*size
    elif shape == 'FHexFlat':
        theta = np.linspace(0, 2*pi, 7)
        return np.cos(theta)*size, np.sin(theta)*size*0.866
    elif shape == 'FRect':
        return np.array([-1,1,1,-1])*size, np.array([-0.5,-0.5,0.5,0.5])*size
    elif shape == 'FPentagon':
        theta = np.linspace(0,2*pi,6) + pi/2
        return np.cos(theta)*size, np.sin(theta)*size
    elif shape in ['FStar4', 'CStar4']:
        angles = np.linspace(0, 2*np.pi, 8, endpoint=False)
        r_outer = size
        r_inner = size * 0.5
        rs = np.array([r_outer if i % 2 == 0 else r_inner for i in range(8)])
        xs = rs * np.cos(angles) * 0.5
        ys = rs * np.sin(angles) * 0.5
        return xs, ys
    elif shape in ['FDiamondFlat', 'CDiamondFlat']:
        width = size
        height = size * 0.5
        xs = np.array([0, width, 0, -width]) * 0.5
        ys = np.array([height, 0, -height, 0]) * 0.5
        return xs, ys
    else:
        return np.array([0]), np.array([0])
