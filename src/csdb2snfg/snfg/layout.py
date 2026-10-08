"""Repeat expansion and backend-agnostic tree layout for glycan ASTs.

Pure functions over the dict/list AST produced by csdb2snfg.csdb.parser;
no matplotlib/pptx dependency. Extracted verbatim from the former flat
renderer module.
"""

import copy

from csdb2snfg.snfg.symbols import MODIFIERS

# 开放端节点 id：layout_tree 是这些键的唯一铸造者（生产者拥有协议词汇）
OPEN_HEAD = "OPEN_HEAD"
OPEN_TAIL = "OPEN_TAIL"


def is_open_node(node_id):
    """开放边端点（非真实残基）判定。"""
    return node_id == OPEN_HEAD or node_id == OPEN_TAIL

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
# Repeat紧凑展开
# ------------------------------
def expand_repeat_compact(nodes):
    """Compact mode: wrap repeats in RepeatGroup markers instead of expanding."""
    new_nodes = []
    for item in nodes:
        if isinstance(item, dict) and 'Repeat' in item:
            repeat_data = item['Repeat']
            unit = repeat_data.get('Unit', [])
            count = str(repeat_data.get('Count', '1'))
            if isinstance(unit, (dict, str)):
                unit = [unit]
            # 递归处理 unit 内部的 Repeat 和 Branch
            expanded_unit = expand_repeat_compact(unit)
            new_nodes.append({
                'RepeatGroup': {
                    'Unit': expanded_unit,
                    'Count': count
                }
            })
        else:
            if isinstance(item, dict) and 'Branch' in item:
                item = copy.deepcopy(item)
                item['Branch'] = expand_repeat_compact(item['Branch'])
                new_nodes.append(item)
            else:
                new_nodes.append(item)
    return new_nodes

# ------------------------------
# 树布局
# ------------------------------
def layout_tree(nodes, dx=1.5, dy=1.5, depth=0, x=0, y=0, ratio=1,
                positions=None, edges=None, labels=None,
                parent_id=None, repeat_groups=None, _top_level=True,
                _main_chain_ids=None):
    if positions is None: positions = {}
    if edges is None: edges = []
    if labels is None: labels = {}
    if repeat_groups is None: repeat_groups = []
    if _main_chain_ids is None: _main_chain_ids = set()

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
            if depth == 0:
                _main_chain_ids.add(node_id)
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
                # label 统一为 "位点-构型"：
                # left 槽（位点，受体侧）靠父节点，right 槽（端基构型，
                # 供体侧）靠子节点。水平边与竖直支链边的槽位几何一致
                # （export 两后端中 left=父侧、right=子侧），
                # 故两种深度使用同一顺序。
                edge_label = make_edge_label(ilink[1], anomeric)
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
            if last_node_id is None:
                # 退化输入：支链没有可挂靠的残基（如 CSDB 仅 "[X]"）。
                # 旧行为是静默跳过 → positions 为空 → draw_snfg 崩溃；
                # 这里退化为按顶层主链布局，保证至少有可渲染的内容。
                layout_tree(item["Branch"], dx, dy, depth, current_x, current_y,
                            ratio, positions, edges, labels, None,
                            repeat_groups, _top_level=False,
                            _main_chain_ids=_main_chain_ids)
            else:
                side_sign = -1 if branch_counter % 2 == 0 else 1
                rdx = side_sign * dx * (ratio ** (depth + 1 ))
                rdy = side_sign * dy * (ratio ** (depth + 1 ))
                if depth % 2 == 0:
                    bx, by = positions[last_node_id][0], positions[last_node_id][1] - rdy
                elif depth % 2 == 1:
                    bx, by = positions[last_node_id][0] - rdx , positions[last_node_id][1]
                # 递归处理支链，parent_id 传入当前的 last_node_id
                layout_tree(item["Branch"], rdx, rdy, depth + 1, bx, by, ratio,
                            positions, edges, labels, last_node_id, repeat_groups,
                            _top_level=False,
                            _main_chain_ids=_main_chain_ids)
                branch_counter += 1

        # 情况 C: 当前项是 RepeatGroup（紧凑模式的重复单元）
        elif "RepeatGroup" in item:
            rg = item['RepeatGroup']
            unit_nodes = rg.get('Unit', [])

            # 记录布局前的位置集合，用于计算包围盒
            ids_before = set(positions.keys())

            # 递归布局 unit 内部节点（与主链同级）
            layout_tree(unit_nodes, dx, dy, depth, current_x, current_y, ratio,
                        positions, edges, labels, last_node_id, repeat_groups,
                        _top_level=False,
                        _main_chain_ids=_main_chain_ids)

            # 找到 unit 内新添加的所有节点位置（排除 OPEN_HEAD/OPEN_TAIL）
            new_ids = [k for k in positions.keys()
                       if k not in ids_before and not is_open_node(k)]

            if new_ids:
                rg_xs = [positions[k][0] for k in new_ids]
                rg_ys = [positions[k][1] for k in new_ids]
                repeat_groups.append({
                    'bbox': (min(rg_xs), min(rg_ys), max(rg_xs), max(rg_ys)),
                    'count': rg['Count'],
                    'node_ids': list(new_ids),
                })

            # 更新指针：unit 正向第一个 Residue 即最左残基。
            # 反向遍历时，RepeatGroup 之后处理的是其左邻节点，
            # 应连接到 unit 的最左残基（而非最右残基）。
            # 坐标推进仍对每个 unit 残基执行一次。
            first_unit_res_id = None
            first_unit_item = None
            for rg_item in unit_nodes:
                if isinstance(rg_item, dict) and "Residue" in rg_item:
                    rg_item_id = id(rg_item)
                    if rg_item_id in positions:
                        if first_unit_res_id is None:
                            first_unit_res_id = rg_item_id
                            first_unit_item = rg_item
                        if depth % 2 == 0:
                            current_x -= dx
                        else:
                            current_y -= dy
            if first_unit_res_id is not None:
                last_node_id = first_unit_res_id
                last_item = first_unit_item

    # --- 添加开放边（仅顶层调用） ---
    if depth == 0 and _top_level:
        # 找到实际最右和最左节点（按 x 坐标），仅在主轴（depth==0）残基中选取
        # 以避免深层支链（depth≥2 水平布局）抢占端点。
        real_ids = [k for k in positions
                    if not is_open_node(k)]
        if real_ids:
            _chain = [k for k in real_ids if k in _main_chain_ids]
            _anchor = _chain if _chain else real_ids
            right_id = max(_anchor, key=lambda k: positions[k][0])
            left_id = min(_anchor, key=lambda k: positions[k][0])
            rx, ry = positions[right_id]
            lx, ly = positions[left_id]

            def _find_node(target_id, obj):
                """递归搜索节点 dict（遍历 dict 和 list）。"""
                if isinstance(obj, dict):
                    if id(obj) == target_id:
                        return obj
                    for v in obj.values():
                        r = _find_node(target_id, v)
                        if r:
                            return r
                elif isinstance(obj, list):
                    for item in obj:
                        r = _find_node(target_id, item)
                        if r:
                            return r
                return None

            # OPEN_HEAD: 右侧开放边
            # label 约定：left 槽(连接位点)画在开放端(括号之外)，
            #             right 槽(端基构型)画在残基端。
            # 最右节点的 Linkage "(1-6)" 描述其指向右侧开放端的连接，
            # to 位点(如 6)属于开放边，不能丢弃。
            head_id = OPEN_HEAD
            positions[head_id] = (rx + dx, ry)
            r_node = _find_node(right_id, nodes)
            r_anomeric = ""
            r_to = ""
            if r_node:
                a = r_node.get('Anomeric')
                if a and str(a).lower() != "none":
                    r_anomeric = str(a)
                linkage = r_node.get("Linkage")
                if linkage:
                    try:
                        parts = str(linkage).strip("()").split("-")
                        if len(parts) == 2 and parts[1].lower() != "none":
                            r_to = parts[1]
                    except Exception:
                        r_to = ""
            if r_to:
                edges.append((head_id, right_id, f"{r_to}-{r_anomeric}"))
            else:
                edges.append((head_id, right_id, f"{r_anomeric}-"))

            # OPEN_TAIL: 左侧开放边
            tail_id = OPEN_TAIL
            positions[tail_id] = (lx - dx, ly)
            l_node = _find_node(left_id, nodes)
            l_ns = ""
            if l_node:
                ns = l_node.get("NonStoichiometric")
                if ns is not None and str(ns).lower() != "none":
                    l_ns = str(ns)
            edges.append((left_id, tail_id, f"{l_ns}-"))

    return None, positions, edges, labels, repeat_groups


# ------------------------------
# 边标签协议（"位点-构型"串）
# ------------------------------
def make_edge_label(site, anomeric):
    """铸造边标签协议串：left 槽=连接位点(受体侧)，right 槽=端基构型(供体侧)。"""
    return f"{site}-{anomeric}"


def parse_edge_label(label_key):
    """解析边标签协议串 -> (left, right)。

    '4-1' -> ('4', '1')；'4-' -> ('4', '')；无 '-' 时 -> (label_key, '')。
    """
    parts = label_key.split('-')
    return (parts[0] if parts else ''), (parts[1] if len(parts) > 1 else '')


# ------------------------------
# 解析→展开→布局 管线
# ------------------------------
def prepare_layout(tree, dx=1.5, dy=1.5, ratio=1, compact_repeat=True):
    """AST（或 to_dict 结果）-> layout_tree 的原 5 元组。

    两个 export 后端共享的管线编排：compact_repeat 决定 repeat 展开方式。
    """
    nodes = tree.to_dict() if hasattr(tree, 'to_dict') else tree
    if compact_repeat:
        expanded = expand_repeat_compact(nodes)
    else:
        expanded = expand_repeat(nodes)
    return layout_tree(expanded, dx, dy, ratio=ratio)
