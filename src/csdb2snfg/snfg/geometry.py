"""Backend-agnostic drawing geometry over layout_tree's abstract space.

numpy-only(经 symbols.get_shape_coords)；无 matplotlib / python-pptx 依赖.
依赖链: symbols ← layout ← geometry ← export.{image,pptx}.

坐标约定: 共享函数定义在抽象布局坐标(y-up)或与之同构的任意笛卡尔空间；
设备量(perp/margin/pad)以调用方空间的单位传入.
"""

from collections import namedtuple

from csdb2snfg.snfg.symbols import glycan_color, glycan_dict, get_shape_coords
from csdb2snfg.snfg.layout import OPEN_HEAD, OPEN_TAIL

DEFAULT_COMP = 'FCircle'
DEFAULT_COLOR_NAME = 'White'
DEFAULT_COLOR_HEX = '#FFFFFF'

# 两后端统一的视觉常量
LABEL_PERP_RATIO = 0.55   # 边标签相对节点尺寸的垂直偏移比例
BRACKET_CAP_RATIO = 0.4   # 重复单元括号横线长度 = BRACKET_CAP_RATIO * PAD


def resolve_mono(mono):
    """mono -> (comp, color_hex)，统一 glycan_dict/glycan_color 查表与缺省兜底."""
    comp, color_name = glycan_dict.get(mono, (DEFAULT_COMP, DEFAULT_COLOR_NAME))
    return comp, glycan_color.get(color_name, DEFAULT_COLOR_HEX)


# ------------------------------
# 半填充顶点索引决策表
# ------------------------------
# sel 中的索引指向 get_shape_coords(comp, size=1.0) 的顶点(y-up 局部坐标).
# 顶点序: FSquare/CSquare = [左下, 右下, 右上, 左上].
ALL = object()  # 哨兵: 整轮廓单色填充

_FILL_POLY_TABLE = {
    'DDiamond': [('color', [3, 0, 1]), ('white', [3, 2, 1])],
    'DDiamondInv': [('white', [3, 0, 1]), ('color', [3, 2, 1])],
    'CSquare': [('color', [1, 2, 3]), ('white', [0, 1, 3])],
    'DTriangle': [('color', [0, 2, 1])],
}


def node_fill_polys(comp):
    """-> (xs, ys, entries): 单位局部坐标 + 填充多边形条目表.

    entries = [(role, sel)]，role ∈ {'color', 'white'}，sel = 顶点索引列表或
    ALL.CSquare 恒为对角分割正方形(右上着色 + 左下白).
    后端负责设备映射: 
      image: XS = xs*size + x
      pptx : (int(x_emu + xs[i]*size_emu), int(y_emu - ys[i]*size_emu))
    """
    xs, ys = get_shape_coords(comp, size=1.0)
    if comp in _FILL_POLY_TABLE:
        entries = _FILL_POLY_TABLE[comp]
    else:
        entries = [('color', ALL)]
    return xs, ys, entries


def shape_vcenter_offset(comp, size):
    """形状 bbox 中心相对绘制锚点的垂直偏移.

    圆/方/菱形等上下对称形状为 0；三角形(y ∈ [-0.5s, s])、星形等
    非对称形状不为 0 —— 同行混排时若不做补偿，各形状 bbox 上端齐平
    ("上端对齐")，视觉上就不居中.legend 绘制时用 y - offset 补偿.
    """
    _, ys = get_shape_coords(comp, size)
    return (ys.max() + ys.min()) / 2


# ------------------------------
# 重复单元括号几何
# ------------------------------
BracketGeom = namedtuple('BracketGeom',
                         ['left_x', 'right_x', 'y_center', 'v_extent',
                          'y_top', 'y_bot', 'cap', 'pad'])


def bracket_pad(size):
    """括号与节点的间距 PAD = size * 1.65."""
    return size * 1.65


def bracket_geometry(x_min, y_min, x_max, y_max, size, *, pad=None):
    """括号几何(表达式与原 matplotlib 实现逐位一致).

    y-up 空间: y_top > y_bot.pptx 后端在 EMU y-down 空间消费时取
    top=geom.y_bot、bottom=geom.y_top(数值小者为上).
    """
    if pad is None:
        pad = bracket_pad(size)
    left_x = x_min - pad
    right_x = x_max + pad
    v_extent = max((y_max - y_min) / 2 + pad, size * 2)
    y_center = (y_min + y_max) / 2
    y_top = y_center + v_extent
    y_bot = y_center - v_extent
    cap = pad * BRACKET_CAP_RATIO
    return BracketGeom(left_x, right_x, y_center, v_extent,
                       y_top, y_bot, cap, pad)


def bracket_bounds(repeat_groups, *, pad, cap=None, positions=None):
    """-> [{'left', 'right', 'node_ids'[, 'cap']}]，跨括号标签避让用.

    positions=None: 用 rg['bbox'](抽象空间旧路径)；
    positions 给定: 从 rg['node_ids'] 在该空间重算 x 范围(pptx EMU 旧路径)，
    空组跳过；cap 非 None 时写入条目.
    """
    out = []
    for rg in repeat_groups:
        if positions is None:
            bx_min, _by_min, bx_max, _by_max = rg['bbox']
            left = bx_min - pad
            right = bx_max + pad
        else:
            group_ids = rg.get('node_ids', [])
            group_x = [positions[nid][0]
                       for nid in group_ids
                       if nid in positions]
            if not group_x:
                continue
            left = min(group_x) - pad
            right = max(group_x) + pad
        entry = {
            'left': left,
            'right': right,
            'node_ids': set(rg.get('node_ids', [])),
        }
        if cap is not None:
            entry['cap'] = cap
        out.append(entry)
    return out


# ------------------------------
# 开放边与边标签槽位
# ------------------------------
def open_edge_flags(parent_id, child_id):
    """-> (is_open_tail, is_open_head, is_open_edge)."""
    is_open_tail = child_id == OPEN_TAIL or parent_id == OPEN_TAIL
    is_open_head = child_id == OPEN_HEAD or parent_id == OPEN_HEAD
    return is_open_tail, is_open_head, (is_open_tail or is_open_head)


def edge_label_slots(parent_id, child_id, p1, p2, *, perp,
                     y_up=True, along_mode='sign',
                     open_ratio=0.6, close_ratio=0.4,
                     bounds=(), avoid_margin=0.0, avoid_floor=False):
    """一条边的两个标签槽位 (x_l, y_l, x_r, y_r).

    left=位点(受体侧, 靠父)、right=端基构型(供体侧, 靠子)；p1=父端、p2=子端，
    任意笛卡尔空间；perp=垂距(调用方空间单位).
    y_up=False 时水平边标签取 y1-perp(EMU y-down 约定).
    along_mode: 
      'sign': 沿线偏移 = ±ratio 绝对单位(含 dx==0 → 0 的三态)；
      'frac': 沿线偏移 = ratio × 边向量分量(仿射不变量)，
              常规水平/开放竖直保留 legacy 表达式 dx/2-dx/10 等
              (与 ratio*dx 有亚 ulp 差异，int() 截断后可能差 1 EMU).
    bounds+avoid_margin: OPEN_TAIL 跨括号外推(p 在内 c 在外时推 x_l)；
    avoid_floor=True 时外推结果取 int(pptx 旧行为).
    """
    x1, y1 = p1
    x2, y2 = p2
    dx_line = x2 - x1
    dy_line = y2 - y1
    _t, _h, is_open_edge = open_edge_flags(parent_id, child_id)
    is_open_tail = _t

    if dy_line == 0:
        # 水平线: 标签在上方(y_up)/上方即 y 减小(y-down)，沿 X 轴分布
        if along_mode == 'sign':
            if is_open_edge:
                sx = open_ratio if dx_line > 0 else -open_ratio
                x_l = x2 - sx    # 子节点侧
                x_r = x1 + sx    # 父节点侧
            else:
                sx = close_ratio if dx_line > 0 else (-close_ratio if dx_line < 0 else 0)
                x_l = x1 + sx    # 父节点侧
                x_r = x2 - sx    # 子节点侧
        else:
            if is_open_edge:
                x_l = x2 - dx_line * open_ratio    # 子节点侧
                x_r = x1 + dx_line * open_ratio    # 父节点侧
            else:
                x_l = x1 + dx_line / 2 - dx_line / 10
                x_r = x2 - dx_line / 2 + dx_line / 10
        if y_up:
            y_l = y1 + perp
            y_r = y1 + perp
        else:
            y_l = y1 - perp
            y_r = y1 - perp
    else:
        # 非水平线(垂直或倾斜): 标签在右侧，沿 Y 轴分布
        x_l = x2 + perp
        x_r = x2 + perp
        if along_mode == 'sign':
            if is_open_edge:
                sy = open_ratio if dy_line > 0 else -open_ratio
                y_l = y2 - sy    # 子节点侧
                y_r = y1 + sy    # 父节点侧
            else:
                sy = close_ratio if dy_line > 0 else (-close_ratio if dy_line < 0 else 0)
                y_l = y1 + sy    # 父节点侧
                y_r = y2 - sy    # 子节点侧
        else:
            if is_open_edge:
                y_l = y2 - dy_line / 2 - dy_line / 10   # 子节点侧
                y_r = y1 + dy_line / 2 + dy_line / 10   # 父节点侧
            else:
                y_l = y1 + dy_line * close_ratio
                y_r = y2 - dy_line * close_ratio

    # 跨括号边的标签避让: 仅 OPEN_TAIL 开放边需要外推——
    # 左开放边的连接位点数字自然位落在括号内，需推到括号外的开放端.
    # 真实-真实跨括号边与 OPEN_HEAD 边的默认侧放置已化学正确
    # (位点数字靠受体侧、端基构型靠供体侧、开放端自然在括号之外)，
    # 不再做任何推送.
    if is_open_tail:
        for bb in bounds:
            p_in = parent_id in bb['node_ids']
            c_in = child_id in bb['node_ids']
            if p_in and not c_in:
                # EXIT: 残基在内、开放端在外 → x_l 推到括号外
                if x2 < bb['left']:
                    x_l = bb['left'] - avoid_margin
                elif x2 > bb['right']:
                    x_l = bb['right'] + avoid_margin
                if avoid_floor:
                    x_l = int(x_l)

    return x_l, y_l, x_r, y_r
