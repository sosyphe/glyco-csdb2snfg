"""CSDB linear notation parser producing an AST for glycan structures."""

import re
import json
from typing import List, Optional

# =========================
# AST Nodes
# =========================

class Node:
    def children(self): return []
    def to_dict(self): raise NotImplementedError

class ChainNode(Node):
    def __init__(self, nodes: List[Node]): self.nodes = nodes
    def children(self): return self.nodes
    def to_dict(self): return [n.to_dict() for n in self.nodes]

class BranchNode(Node):
    def __init__(self, chain: ChainNode): self.chain = chain
    def children(self): return [self.chain]
    def to_dict(self): return {"Branch": self.chain.to_dict()}

class FuzzyNode(Node):
    def __init__(self, options: List[Node], xor=False): self.options = options; self.xor = xor
    def children(self): return self.options
    def to_dict(self): return {"XOR" if self.xor else "OR": [o.to_dict() for o in self.options]}

class RepeatNode(Node):
    def __init__(self, unit: Node, count): self.unit = unit; self.count = count
    def children(self): return [self.unit]
    def to_dict(self): return {"Repeat": {"Unit": self.unit.to_dict(), "Count": self.count}}

class LinkageNode(Node):
    def __init__(self, by=None, to=None): self.by=by; self.to=to
    def to_dict(self): return f"({self.by}-{self.to})" if self.by or self.to else None

class ResidueNode(Node):
    def __init__(self, name,anomeric=None, absolute=None, ring=None, linkage=None, non_stoichiometric=None, raw=None):
        self.name=name; self.anomeric=anomeric; self.absolute=absolute; self.ring=ring
        self.linkage=linkage; self.non_stoichiometric=non_stoichiometric; self.raw=raw
    def children(self): return [self.linkage] if self.linkage else []
    def to_dict(self):
        return {
            "Residue": self.name,
            "Anomeric": self.anomeric,
            "Absolute": self.absolute,
            "Ring": self.ring,
            "Linkage": self.linkage.to_dict() if self.linkage else None,
            "NonStoichiometric": self.non_stoichiometric,
            "Raw": self.raw
        }

# =========================
# Residue Parser
# =========================
sugar_list = [
    # 修饰基团与特殊前缀
    "Me", "Ac", "Gc", "P", "S", "T",
    # 复杂长缩写 (优先匹配)
    "LDmanHep", "DDmanHep", "6dAltNAc", "6dTalNAc", "8eAci", "8eLeg", "4eLeg",
    "MurNAc", "MurNGc", "Neu5Ac", "Neu5Gc", "RhaNAc", "GalNAc", "GlcNAc", 
    "ManNAc", "AllNAc", "AltNAc", "GulNAc", "IdoNAc", "TalNAc", "QuiNAc",
    "FucNAc",
    # 带有修饰符的缩写
    "AllA", "AllN", "AltA", "AltN", "GalA", "GalN", "GlcA", "GlcN", 
    "GulA", "GulN", "IdoA", "IdoN", "ManA", "ManN", "TalA", "TalN",
    # 6-脱氧系列
    "6dAlt", "6dGul", "6dTal",
    # 基础三字符缩写
    "Abe", "Aci", "All", "Alt", "Api", "Ara", "Bac", "Col", "Dha", "Dig", 
    "Fru", "Fuc", "Gal", "Glc", "Gul", "Ido", "Kdn", "Kdo", "Leg", "Lyx", 
    "Man", "Mur", "Neu", "Oli", "Par", "Pse", "Psi", "Qui", "Rha", "Rib", 
    "Sia", "Sor", "Tag", "Tal", "Tyv", "Xyl"
]
sugar_list.sort(key=len, reverse=True)
sugar_pattern = "|".join(map(re.escape, sugar_list))
RES_RE = re.compile(
    rf"""
    (?P<ns>-\d+\)|%\d+)?                       # 可选编号
    (?P<anomeric>[αβablx]?)                    # α/β
    (?P<absolute>[DLRXS]?)                     # D/L/R/X/S
    (?P<name>{sugar_pattern})                  # 基础糖名 (如 Gal, Rha, Glc)
    (?P<ring>[pf])?                            # 环型 (p 吡喃 / f 呋喃)
    (?P<modifier>[ANS])?                       # 关键修饰: A(酸), N(胺), S(硫酸基)
    (?:\((?P<by>\d*)-(?P<to>\d*)?\)? )?           # 连接位置 (1-4)
    """,
    re.VERBOSE
)

def parse_residue(token: str) -> List[ResidueNode]:
    nodes=[]
    pos=0
    while pos<len(token):
        m = RES_RE.match(token,pos)
        if not m: break
        ns = m.group("ns")
        if ns: ns = int(ns.strip("-)%")) if ns.startswith("-") else int(ns.strip("%"))
        anomeric = m.group("anomeric") or None
        absolute = m.group("absolute") or None
        name = m.group("name")
        mod = m.group("modifier") or ""
        fullname = f"{name}{mod}"
        ring = m.group("ring") or None
        by = m.group("by")
        to = m.group("to")
        linkage = LinkageNode(by=int(by) if by else None, to=int(to) if to else None) if by or to else None
        raw = token[m.start():m.end()]
        nodes.append(ResidueNode(fullname, anomeric, absolute, ring, linkage, ns, raw))
        pos = m.end()
    return nodes

# =========================
# Stack-based Parser with Repeat
# =========================

def parse_csdb_linear(code: str) -> Node:
    code = code.strip()
    i=0; n=len(code)
    stack=[[]]
    pending_ns = None

    while i<n:
        c = code[i]
        m = re.match(r"-?(\d+)\)", code[i:])
        if m:
            pending_ns = int(m.group(1))
            i += m.end()
            continue

        # Repeat detection
        if code[i:i+3] == "/n=":
            # 匹配 /n=?/
            m = re.match(r"/n=([^/]+)/?", code[i:])
            count = m.group(1) if m else None

            # 找重复单元起点：向左找到最近的 '/'，或者从头开始
            unit_start = code.rfind("/", 0, i)
            if unit_start == -1:
                unit_start = 0
            unit_str = code[unit_start+1:i]  # 只取重复单元字符串

            # 解析重复单元
            unit_node = parse_csdb_linear(unit_str)

            # 替换 stack[-1] 中重复单元对应的节点
            # 假设 stack[-1] 中最后一部分正好对应 unit_node 的长度
            # 这里为了保险，可以直接删除 stack[-1] 中最后 len(unit_node.children()) 个节点
            if isinstance(unit_node, ChainNode):
                n_remove = len(unit_node.children())
            else:
                n_remove = 1
            stack[-1] = stack[-1][:-n_remove] + [RepeatNode(unit_node, count)]

            # 移动指针
            i += m.end() if m else 3
            continue

        # Branch
        elif c=="[":
            stack.append([])
            i+=1
        elif c=="]":
            nodes = stack.pop()
            branch = BranchNode(ChainNode(nodes))
            stack[-1].append(branch)
            i+=1

        # Fuzzy
        elif c=="<":
            xor=False
            if i+1<n and code[i+1]=="<": xor=True; i+=1
            depth=1; j=i+1
            while j<n and depth>0:
                if code[j]=="<": depth+=1
                elif code[j]==">": depth-=1
                j+=1
            inner = code[i+1:j-1]
            options = [parse_csdb_linear(x.strip()) for x in inner.split("|")]
            stack[-1].append(FuzzyNode(options, xor))
            i=j+(1 if xor else 0)

        # Chain separator
        elif c=="/":
            i+=1

        # Residue / Alias
        else:
            residues = parse_residue(code[i:])
            if residues:
                if (
                    residues[0].non_stoichiometric is not None
                    and pending_ns is None
                    and len(stack[-1]) == 0
                ):
                    pending_ns = residues[0].non_stoichiometric
                    residues[0].non_stoichiometric = None
                if pending_ns is not None and len(stack) == 1:
                    residues[0].non_stoichiometric = pending_ns
                    pending_ns = None
                stack[-1].extend(residues)
                i += sum(len(r.raw) for r in residues)
            else:
                i += 1
    return ChainNode(stack[0]) if len(stack[0])>1 else stack[0][0] if stack[0] else None

# =========================
# AST Printer
# =========================
def print_ast(node: Node, indent=0):
    prefix="  "*indent
    if isinstance(node, ChainNode):
        print(f"{prefix}ChainNode")
        for c in node.children(): print_ast(c, indent+1)
    elif isinstance(node, BranchNode):
        print(f"{prefix}BranchNode")
        print_ast(node.chain, indent+1)
    elif isinstance(node, FuzzyNode):
        print(f"{prefix}FuzzyNode({'XOR' if node.xor else 'OR'})")
        for o in node.options: print_ast(o, indent+1)
    elif isinstance(node, RepeatNode):
        print(f"{prefix}RepeatNode(count={node.count})")
        print(f"{prefix}  Unit:")
        print_ast(node.unit, indent+2)
    elif isinstance(node, ResidueNode):
        print(f"{prefix}ResidueNode({node.raw})")

