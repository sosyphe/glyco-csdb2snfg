"""SNFG diagram renderer using matplotlib."""

import re
import copy
from math import pi
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.legend_handler import HandlerBase

from csdb2snfg.parser import parse_csdb_linear
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
    'AltA':['DDiamond','Pink'],
    'AllA':['DDiamond','Purple'],
    'TalA':['DDiamond','LightBlue'],
    'IdoA':['DDiamond','Brown'],

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
        half_side = size / np.sqrt(2)  # 外接圆半径 = size
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
    elif shape in ['FDiamond','DDiamond','DDiamondFlat']:
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

# ------------------------------
# 预计算形状坐标
# ------------------------------
def draw_shape(ax, comp, x, y, size, color):
    """
    绘制 SNFG 单糖节点
    ax: matplotlib Axes
    comp: glycan_dict 中的形状类型（FCircle, FSquare, DDiamond ...）
    x, y: 中心坐标
    size: 外接圆半径
    color: 填充颜色
    """
    unique_shapes = set([v[0] for v in glycan_dict.values()])
    glycan_shape = {shape: {'x': get_shape_coords(shape)[0], 'y': get_shape_coords(shape)[1]} for shape in unique_shapes}

    shape = glycan_shape[comp]  # 预先生成的形状坐标字典
    xs = shape['x']*size + x
    ys = shape['y']*size + y

    if comp == 'DDiamond':
        ax.fill([xs[3], xs[0], xs[1]], [ys[3], ys[0], ys[1]], color=color, edgecolor='black', zorder=2)
        ax.fill([xs[3], xs[2], xs[1]], [ys[3], ys[2], ys[1]], color='white', edgecolor='black', zorder=2)
    elif comp == 'CSquare':
        ax.fill([x, xs[1], xs[2]], [y, ys[1], ys[2]], color=color, edgecolor='black', zorder=2)
    elif comp == 'DTriangle':
        ax.fill([xs[0], xs[2], xs[1]], [ys[0], ys[2], ys[1]], color=color, edgecolor='black', zorder=2)
    else:
        ax.fill(xs, ys, color=color, edgecolor='black', zorder=2)

# ------------------------------
# 自定义 legend handler
# ------------------------------
class GlycanLegendHandler(HandlerBase):
    def __init__(self, comp, color, size=0.3):
        self.comp = comp
        self.color = color
        self.size = size
        super().__init__()

    def create_artists(self, legend, orig_handle,
                       xdescent, ydescent, width, height, fontsize, trans):
        # legend 中中心位置
        cx = width / 2
        cy = height / 2
        xs, ys = get_shape_coords(self.comp, self.size)
        xs = xs + cx
        ys = ys + cy
        poly = Polygon(
            np.column_stack([xs, ys]),
            facecolor=self.color,
            edgecolor='black',
            lw=0.5
        )
        poly.set_transform(trans)
        return [poly]

def add_snfg_legend(ax, used_monos, mono_size=0.3, font_size=8):
    if not used_monos:
        return
    fig = ax.get_figure()
    n = len(used_monos)
    
    # 根据单糖数量计算 legend 高度
    legend_height = mono_size * 2
    legend_width = n * mono_size * 8

    legend_ax = fig.add_axes([(1 - legend_width / fig.get_figwidth()) / 2, 0.05,
                              legend_width / fig.get_figwidth(), legend_height/fig.get_figheight()])
    legend_ax.axis('off')
    legend_ax.set_aspect('equal')

    for i, mono in enumerate(sorted(used_monos)):
        comp, color = glycan_dict.get(mono, ('FCircle','White'))
        x = i * mono_size * 4
        y = 0.5
        draw_shape(legend_ax, comp, x, y, mono_size, glycan_color[color])
        legend_ax.text(x+mono_size, y,
                       mono, fontsize=font_size, va='center', ha='left')

# ------------------------------
# Repeat展开
# ------------------------------
def expand_repeat(nodes):
    new_nodes = []
    for item in nodes:
        if isinstance(item, dict) and 'Repeat' in item:
            repeat_data = item['Repeat']
            unit = repeat_data.get('Unit', [])
            try:
                count = int(repeat_data.get('Count', 1))
            except (ValueError, TypeError):
                count = 1

            # 如果 unit 是单个 dict 或 str，统一转换成列表
            if isinstance(unit, (dict, str)):
                unit = [unit]

            # 展开 Repeat 单元 count 次
            for _ in range(count):
                for u in unit:
                    if isinstance(u, dict):
                        # 递归处理 Branch 内部的 Repeat
                        new_u = copy.deepcopy(u)
                        if 'Branch' in new_u:
                            new_u['Branch'] = expand_repeat(new_u['Branch'])
                        new_nodes.append(new_u)
                    else:
                        # 字符串节点直接加入
                        new_nodes.append(u)
        else:
            # 非 Repeat 节点
            if isinstance(item, dict) and 'Branch' in item:
                item = copy.deepcopy(item)
                item['Branch'] = expand_repeat(item['Branch'])
                new_nodes.append(item)
            else:
                # 字符串节点或普通 dict
                new_nodes.append(item)
    return new_nodes

# ------------------------------
# 树布局
# ------------------------------
def layout_tree(nodes, dx=1.5, dy=1.5, depth=0, x=0, y=0, ratio=1,
                positions=None, edges=None, labels=None,
                parent_id=None):
    if positions is None: positions = {}
    if edges is None: edges = []
    if labels is None: labels = {}

    current_x = x
    current_y = y
    branch_counter = 0
    last_node_id = parent_id 
    first_node_id = None

    for item in reversed(nodes):
        # 情况 A: 当前项是 Residue 节点
        if "Residue" in item:
            node_id = id(item)
            labels[node_id] = item.get("Residue", "Unknown")
            # 建立主轴线连接
            if labels[node_id] in MODIFIERS and last_node_id is not None:
                px, py = positions[last_node_id]
                if depth % 2 == 0:
                    positions[node_id] = (px - dx*0.5, py)
                else:
                    positions[node_id] = (px, py - dy*0.5)
                continue
            # ===== 情况 B：正常糖 Residue =====
            positions[node_id] = (current_x, current_y)
            if depth == 0 and first_node_id is None:
                first_node_id = node_id
                anomeric = item.get('Anomeric')
                if anomeric is None or anomeric.lower() == "none": anomeric = "-"
                first_node_linkage = f"{anomeric}-"
            if last_node_id is not None:
                linkage = item.get("Linkage", "(?-?)")
                try:
                    ilink = linkage[1:-1].split("-")
                    if len(ilink) != 2 or ilink[0].lower() == "none" or ilink[1].lower() == "none":
                        ilink = ["", ""]
                except:
                    ilink = ["", ""]
                anomeric = item.get("Anomeric")
                if anomeric is None or anomeric.lower() == "none": anomeric = ""
                if depth % 2 == 0 :
                    # edge_label = f"{anomeric}{ilink[0]}-{ilink[1]}"
                    edge_label = f"{ilink[1]}-{anomeric}"
                else :
                    edge_label = f"{anomeric}-{ilink[1]}"
                    # edge_label = f"{ilink[1]}-{anomeric}{ilink[0]}"
                edges.append((last_node_id, node_id, edge_label))
            # 更新当前链的指针和坐标
            last_node_id = node_id
            last_item = item
            if depth % 2 == 0:
                current_x -= dx
            else:
                current_y -= dy
        # 情况 B: 当前项是支链容器
        elif "Branch" in item and item["Branch"]:
            if last_node_id is not None:
                side_sign = -1 if branch_counter % 2 == 0 else 1
                rdx = side_sign * dx * (ratio ** (depth + 1 ))
                rdy = side_sign * dy * (ratio ** (depth + 1 )) 
                if depth % 2 == 0:
                    bx, by = positions[last_node_id][0], positions[last_node_id][1] - rdy
                elif depth % 2 == 1:
                    bx, by = positions[last_node_id][0] - rdx , positions[last_node_id][1]
                # 递归处理支链，parent_id 传入当前的 last_node_id
                layout_tree(item["Branch"], rdx, rdy, depth + 1, bx, by, ratio,
                            positions, edges, labels, last_node_id)
                branch_counter += 1

    # --- 添加开放边 ---
    if depth == 0:
        if first_node_id:
            fx, fy = positions[first_node_id]
            head_id = "OPEN_HEAD"
            positions[head_id] = (fx + dx, fy)
            edges.append((head_id, first_node_id, first_node_linkage))
        if last_node_id:
            lx, ly = positions[last_node_id]
            tail_id = "OPEN_TAIL"
            positions[tail_id] = (lx - dx, ly)
            last_node_ns = str(last_item.get("NonStoichiometric"))
            if last_node_ns is None or last_node_ns.lower() == "none": last_node_ns = ""
            last_node_linkage = f"{last_node_ns}-"
            edges.append((last_node_id, tail_id, last_node_linkage))

    return None, positions, edges, labels

# ------------------------------
# 主绘图
# ------------------------------
def draw_snfg(tree, dx=1, dy=1, mono_size=0.3, ratio=1,
              font_size=12, font_family="sans-serif",save_svg=None, add_legend=True):

    # print(expand_repeat(tree.to_dict()))
    _, pos, edges, labels = layout_tree(expand_repeat(tree.to_dict()), dx, dy, ratio=ratio)
    xs = [x for x, y in pos.values()]
    ys = [y for x, y in pos.values()]
    width = max(xs) - min(xs) + 2
    height = max(ys) - min(ys) + 2

    plt.rcParams['font.family'] = font_family
    # 根据节点数量动态调整图形大小
    node_count = len(pos)
    min_width = max(4, min(12, node_count * 1.5))
    min_height = max(3, min(6, node_count * 0.8))
    fig, ax = plt.subplots(
        figsize=(max(min_width, width * 1.2), max(min_height, height * 1.2)),
    )

    # ---------- 绘制边 ----------
    for p, c, lk in edges:
        x1, y1 = pos[p]
        x2, y2 = pos[c]

        ax.plot([x1, x2], [y1, y2],
                color='black', lw=1, zorder=1)

        if lk:
            left, right = lk.split("-")[0],lk.split("-")[1]
            dx_line = x2 - x1
            dy_line = y2 - y1
            angle = 0
            if dy_line == 0:
                x_l = x1 + dx_line / 2 - dx_line / 10
                x_r = x2 - dx_line / 2 + dx_line / 10
                y_l = y1 + 0.1
                y_r = y1 + 0.1
            else:
                x_l = x2 + 0.1
                x_r = x2 + 0.1
                y_l = y1 + dy_line / 2 + dy_line / 10
                y_r = y2 - dy_line / 2 - dy_line / 10
            if left:
                ax.text(x_l, y_l, left,
                        fontsize=font_size - 1,
                        rotation=angle,
                        rotation_mode='anchor',
                        ha='center', va='center',
                        zorder=4)
            if right:
                ax.text(x_r, y_r, right,
                        fontsize=font_size - 1,
                        rotation=angle,
                        rotation_mode='anchor',
                        ha='center', va='center',
                        zorder=4)

    # ---------- 绘制节点 ----------
    used_monos = set()
    for i, (x, y) in pos.items():
        if i in ["OPEN_HEAD","OPEN_TAIL"] :
            pass
        else :
            mono = labels[i]
            used_monos.add(mono)
            comp, color = glycan_dict.get(mono, ('FCircle','White'))
            draw_shape(ax, comp, x, y, mono_size, glycan_color[color])
            # ax.text(x, y, mono, fontsize=font_size,
            #         ha='center', va='center', zorder=3)

    # ---------- 绘制图例 ----------
    if add_legend:
        add_snfg_legend(ax, used_monos, mono_size, font_size)

    ax.set_aspect('equal')
    ax.axis('off')

    if save_svg:
        fig.savefig(save_svg, bbox_inches='tight')
        plt.close(fig)
        return None, None

    return fig, ax
