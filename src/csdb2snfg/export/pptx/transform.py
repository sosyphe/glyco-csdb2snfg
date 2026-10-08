"""抽象布局坐标 → PPT EMU 的仿射变换与节点尺寸计算。"""

from csdb2snfg.snfg.layout import is_open_node
from csdb2snfg.snfg.symbols import MODIFIERS

PADDING_EMU = 360000    # 1cm fixed padding
MAX_SCALE = 450000
MIN_SCALE = 360000
EXTRA_MARGIN = 900000
MAX_NODE_SIZE_EMU = 180000  # 0.5cm radius = 1cm diameter max
MIN_NODE_SIZE_EMU = 90000   # 0.25cm radius = 0.5cm diameter min


class EmuTransform:
    """抽象 y-up 布局坐标 → EMU y-down 的仿射映射。

    x' = ((base_x + (x-min_x)*scale) + off_x)
    y' = ((base_y + (max_y-y)*scale) + off_y)
    x()/y() 的括号求值序与原实现逐位一致（改序会漂 ulp → XML 字节变）。
    """
    __slots__ = ('base_x', 'base_y', 'min_x', 'max_y', 'off_x', 'off_y', 'scale')

    def __init__(self, base_x, base_y, min_x, max_y, off_x, off_y, scale):
        self.base_x = base_x
        self.base_y = base_y
        self.min_x = min_x
        self.max_y = max_y
        self.off_x = off_x
        self.off_y = off_y
        self.scale = scale

    def x(self, v):
        return self.base_x + (v - self.min_x) * self.scale + self.off_x

    def y(self, v):
        return self.base_y + (self.max_y - v) * self.scale + self.off_y

    def p(self, pt):
        return (self.x(pt[0]), self.y(pt[1]))

    def length(self, v):
        return v * self.scale          # 无原点的长度映射

    def inv_x(self, v):
        return (v - self.off_x - self.base_x) / self.scale + self.min_x

    def inv_y(self, v):
        return self.max_y - (v - self.off_y - self.base_y) / self.scale


def transform_positions(positions, ph_bounds, fixed_scale=None):
    """Map layout_tree abstract coords to PPT EMU coords within placeholder.

    Y axis is flipped (matplotlib up -> PPT down).

    Args:
        fixed_scale: If provided, use this scale instead of calculating (for re-centering).

    Returns:
        tuple: (positions_emu dict, needed_bounds tuple, scale float, EmuTransform)
        needed_bounds = (needed_width, needed_height) in EMU, may exceed ph_bounds
    """
    ph_left, ph_top, ph_width, ph_height = ph_bounds

    xs = [x for x, y in positions.values()]
    ys = [y for x, y in positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    data_w = max_x - min_x if max_x != min_x else 1
    data_h = max_y - min_y if max_y != min_y else 1

    avail_w = ph_width - 2 * PADDING_EMU
    avail_h = ph_height - 2 * PADDING_EMU

    if fixed_scale is not None:
        scale = fixed_scale
    else:
        base_scale = min(avail_w / data_w, avail_h / data_h)
        scale = max(min(base_scale, MAX_SCALE), MIN_SCALE)

    drawn_w = data_w * scale
    drawn_h = data_h * scale

    needed_w = int(drawn_w + 2 * PADDING_EMU + EXTRA_MARGIN)
    needed_h = int(drawn_h + 2 * PADDING_EMU + EXTRA_MARGIN)

    # 居中时包含图例空间，使节点+图例整体居中
    offset_x = (avail_w - drawn_w) / 2
    offset_y = (avail_h - drawn_h - EXTRA_MARGIN) / 2

    tf = EmuTransform(ph_left + PADDING_EMU, ph_top + PADDING_EMU,
                      min_x, max_y, offset_x, offset_y, scale)
    result = {}
    for node_id, (x, y) in positions.items():
        result[node_id] = tf.p((x, y))

    return result, (needed_w, needed_h), scale, tf


def compute_node_size(positions_emu, labels=None):
    """Compute node radius based on minimum inter-node distance, excluding modifiers.

    Max shape size is capped at 1cm (diameter) = 180,000 EMU (radius).
    Min shape size is 0.25cm (diameter) = 90,000 EMU (radius) as fallback.
    """
    real_ids = [k for k in positions_emu if not is_open_node(k)]
    if labels is not None:
        real_ids = [k for k in real_ids if labels.get(k) not in MODIFIERS]
    if len(real_ids) < 2:
        return int(min(200000, MAX_NODE_SIZE_EMU))  # default, capped

    min_dist = float('inf')
    for i in range(len(real_ids)):
        for j in range(i + 1, len(real_ids)):
            x1, y1 = positions_emu[real_ids[i]]
            x2, y2 = positions_emu[real_ids[j]]
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            # 跳过完全重叠的节点（layout_tree 的 bug）
            if dist > 0 and dist < min_dist:
                min_dist = dist

    # 如果所有节点都重叠，使用最小尺寸
    if min_dist == float('inf'):
        return MIN_NODE_SIZE_EMU

    return int(min(min_dist * 0.36, MAX_NODE_SIZE_EMU))
