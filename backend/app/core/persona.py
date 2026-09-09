"""机构设计人格（Institutional Design Persona）：加载、令牌索引与注册。

persona.yaml 按 McAdams 三层编码，各层计算职责：
- L1_signature（气质签名）: tokens + 无条件规则 → 编译为快道检测器与终检不变量
- L2_adaptations（特征适应）: when→then 条件规范 → 快道条件求值 + 动作编译
- L3_narrative（叙事认同）: 哲学/理由故事 → 慢道裁决的担保语料 + 修改标签解释语言

内置 persona 读取仓库根 data/*-persona.yaml；Parser Agent 现场解析的自定义
persona 存 backend/storage/personas/，两者装配后走完全相同的四拍推理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


@dataclass
class Rule:
    id: str
    rule: str
    strength: str = "should"
    check: str = "llm"
    story: str = ""
    src: list[str] = field(default_factory=list)
    derived: bool = False
    requires: list[str] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class Adaptation:
    id: str
    when: dict = field(default_factory=dict)
    then: Any = None
    strength: str = "should"
    check: str = "llm"
    story: str = ""
    src: list[str] = field(default_factory=list)
    derived: bool = False
    scope: str = "chart"
    overrides: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class Philosophy:
    id: str
    title: str = ""
    quote: str = ""
    src: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Story:
    id: str
    story: str = ""
    src: list[str] = field(default_factory=list)


# 内置机构的 UI 提示（badge 品牌色等展示层信息，不属于研究表示本身）
UI_HINTS: dict[str, dict] = {
    "bbc": {
        "category": "News",
        "brand_color": "#BB1919",
        "full_name": "BBC Visual Journalism",
        "abbr": "BBC",
        "palette": ["#1380A1", "#FAAB18", "#007f7f", "#333333", "#990000"],
    },
    "economist": {
        "category": "News",
        "brand_color": "#E3120B",
        "full_name": "The Economist",
        "abbr": "ECO",
        "palette": ["#141F52", "#E3120B", "#F5F4EF", "#1DC9A4", "#B3B3B3"],
    },
    "cmu": {
        "category": "Education",
        "brand_color": "#C41230",
        "full_name": "Carnegie Mellon University",
        "abbr": "CMU",
        "palette": ["#c41230", "#4d5051", "#008285", "#043673", "#007bc0"],
    },
    "cfpb": {
        "category": "Government",
        "brand_color": "#20AA3F",
        "full_name": "Consumer Financial Protection Bureau",
        "abbr": "CFPB",
        "palette": ["#20aa3f", "#254b87", "#7eb7e8", "#ffb858", "#c55998"],
    },
    "who": {
        "category": "Non-profit",
        "brand_color": "#008DC9",
        "full_name": "World Health Organization",
        "abbr": "WHO",
        "palette": ["#008dc9", "#f4a81d", "#f26829", "#6363c0", "#40bf73"],
    },
    "ibm": {
        "category": "Profit",
        "brand_color": "#0F62FE",
        "full_name": "IBM Design Language",
        "abbr": "IBM",
        "palette": ["#6929c4", "#1192e8", "#005d5d", "#9f1853", "#fa4d56"],
    },
    "ebay": {
        "category": "Profit",
        "brand_color": "#3665F3",
        "full_name": "eBay Evo Design System",
        "abbr": "EBAY",
        "palette": ["#3665f3", "#05823f", "#f7b100", "#e0103a", "#707070"],
    },
    "shopify": {
        "category": "Profit",
        "brand_color": "#008060",
        "full_name": "Shopify Polaris",
        "abbr": "SHOP",
        "palette": ["#9c6ade", "#47c1bf", "#5c6ac4", "#50b83c", "#c4cdd5"],
    },
}
CUSTOM_COLOR_POOL = ["#7C3AED", "#0891B2", "#059669", "#D97706", "#DB2777", "#4338CA", "#0D9488"]


@dataclass
class Persona:
    id: str
    name: str
    domain: str = ""
    source_file: str = ""
    kind: str = "builtin"  # builtin | custom
    applicability: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    adaptations: list[Adaptation] = field(default_factory=list)
    philosophy: list[Philosophy] = field(default_factory=list)
    stories: dict[str, Story] = field(default_factory=dict)
    ui: dict = field(default_factory=dict)
    diagnostics: list[dict] = field(default_factory=list)
    chart_type_guidance: list[dict] = field(default_factory=list)
    palette_guidance: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    _token_idx: dict | None = None

    # ---------- 令牌索引与解析（快道"令牌直注"的基础） ----------

    def token_index(self) -> dict[str, Any]:
        """扁平化令牌树：叶子与子树均按完整点路径可查，叶子名亦可短查。"""
        if self._token_idx is None:
            idx: dict[str, Any] = {}

            def walk(node, path: list[str]):
                if isinstance(node, dict):
                    if path:
                        idx[".".join(path)] = node  # 子树本身（如 color.canvas / font.scale.steps）
                    for k, v in node.items():
                        walk(v, path + [str(k)])
                else:
                    dotted = ".".join(path)
                    idx[dotted] = node
                    leaf = path[-1] if path else ""
                    idx.setdefault(leaf, node)

            walk(self.tokens, [])
            self._token_idx = idx
        return self._token_idx

    def resolve_token(self, ref: Any) -> Any:
        """解析令牌引用："{color.bbc-blue}" / "{palette.categorical}" / "chicago-20" / "#hex"。"""
        if isinstance(ref, list):
            return [self.resolve_token(r) for r in ref]
        if not isinstance(ref, str):
            return ref
        s = ref.strip()
        braced = re.fullmatch(r"\{([^{}]+)\}", s)
        if braced:
            s = braced.group(1).strip()
        if _HEX.match(s):
            return s
        seen: set[str] = set()
        while s not in seen:
            seen.add(s)
            val = self.token_index().get(s)
            if isinstance(val, list):
                return [self.resolve_token(v) for v in val]
            if val is None:
                break
            if not isinstance(val, str):
                return val
            alias = re.fullmatch(r"\{([^{}]+)\}", val.strip())
            target = alias.group(1).strip() if alias else val.strip()
            if _HEX.match(target):
                return target
            if target in self.token_index():
                s = target
                continue
            return val
        return None if braced else s

    def resolve_color(self, ref: Any) -> str | None:
        """解析为单个 hex 颜色，失败返回 None（绝不让 LLM 转写颜色值）。"""
        v = self.resolve_token(ref)
        if isinstance(v, str) and _HEX.match(v.strip()):
            return v.strip()
        return None

    def resolve_color_list(self, ref: Any) -> list[str]:
        v = self.resolve_token(ref)
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return []
        out = []
        for item in v:
            c = self.resolve_color(item)
            if c:
                out.append(c)
        return out

    # ---------- 叙事检索 ----------

    def story_text(self, story_id: str) -> str:
        st = self.stories.get(story_id)
        return st.story if st else ""

    def philosophy_text(self) -> str:
        return "\n".join(
            f"- [{p.id}] {p.title + ': ' if p.title else ''}{p.quote}" for p in self.philosophy
        )

    # ---------- API 元信息 ----------

    def meta(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "full_name": self.ui.get("full_name", self.name),
            "domain": self.domain,
            # taxonomy 分类（Government/Education/Non-profit/News/Profit）；自定义 persona 落 Other
            "category": self.ui.get("category") or "Other",
            "kind": self.kind,
            "source": self.source_file,
            "brand_color": self.ui.get("brand_color", "#4338CA"),
            "palette": self.ui.get("palette", []),
            "abbr": self.ui.get("abbr", self.name[:3].upper()),
            "layers": {
                "l1_rules": len(self.rules),
                "l2_adaptations": len(self.adaptations),
                "l3_philosophy": len(self.philosophy),
                "l3_stories": len(self.stories),
            },
            "applicability": self.applicability,
        }


def _first_hexes(tokens: dict, limit: int = 5) -> list[str]:
    found: list[str] = []

    def walk(node):
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and _HEX.match(node.strip()):
            if node.strip() not in found:
                found.append(node.strip())

    walk(tokens)
    return found


def load_persona_dict(data: dict, source_file: str = "", kind: str = "builtin") -> Persona:
    inst = data.get("institution") or {}
    l1 = data.get("L1_signature") or {}
    l3 = data.get("L3_narrative") or {}

    rules = []
    for r in l1.get("rules") or []:
        if not isinstance(r, dict) or "id" not in r:
            continue
        rules.append(
            Rule(
                id=str(r["id"]),
                rule=str(r.get("rule", "")),
                strength=str(r.get("strength", "should")),
                check=str(r.get("check", "llm")),
                story=str(r.get("story", "")),
                src=_as_list(r.get("src")),
                derived=bool(r.get("derived", False)),
                requires=_as_list(r.get("requires")),
                overrides=_as_list(r.get("overrides")),
                raw=r,
            )
        )

    adaptations = []
    for a in data.get("L2_adaptations") or []:
        if not isinstance(a, dict) or "id" not in a:
            continue
        adaptations.append(
            Adaptation(
                id=str(a["id"]),
                when=a.get("when") if isinstance(a.get("when"), dict) else {},
                then=a.get("then"),
                strength=str(a.get("strength", "should")),
                check=str(a.get("check", "llm")),
                story=str(a.get("story", "")),
                src=_as_list(a.get("src")),
                derived=bool(a.get("derived", False)),
                scope=str(a.get("scope", "chart")),
                overrides=_as_list(a.get("overrides")),
                raw=a,
            )
        )

    philosophy = []
    for p in l3.get("philosophy") or []:
        if not isinstance(p, dict) or "id" not in p:
            continue
        philosophy.append(
            Philosophy(
                id=str(p["id"]),
                title=str(p.get("title", "")),
                quote=str(p.get("quote", "")),
                src=_as_list(p.get("src")),
                note=str(p.get("note", "")),
            )
        )

    stories = {}
    for s in l3.get("stories") or []:
        if not isinstance(s, dict) or "id" not in s:
            continue
        stories[str(s["id"])] = Story(id=str(s["id"]), story=str(s.get("story", "")), src=_as_list(s.get("src")))

    pid = str(inst.get("id") or "persona")
    persona = Persona(
        id=pid,
        name=str(inst.get("name") or pid),
        domain=str(inst.get("domain") or ""),
        source_file=source_file or str(inst.get("source") or ""),
        kind=kind,
        applicability=data.get("applicability") or {},
        tokens=l1.get("tokens") or {},
        rules=rules,
        adaptations=adaptations,
        philosophy=philosophy,
        stories=stories,
        diagnostics=data.get("diagnostics") if isinstance(data.get("diagnostics"), list) else [],
        chart_type_guidance=data.get("chart_type_guidance") if isinstance(data.get("chart_type_guidance"), list) else [],
        palette_guidance=data.get("palette_guidance") if isinstance(data.get("palette_guidance"), list) else [],
        conflicts=data.get("conflicts") if isinstance(data.get("conflicts"), list) else [],
        raw=data,
    )
    return persona


def load_persona_yaml_file(path: Path, kind: str = "builtin") -> Persona:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"persona 文件格式错误: {path.name}")
    return load_persona_dict(data, source_file=path.name, kind=kind)


class PersonaRegistry:
    """内置（data/*-persona.yaml）与自定义（storage/personas/）persona 注册表。"""

    def __init__(self, data_dir: Path, custom_dir: Path):
        self.data_dir = data_dir
        self.custom_dir = custom_dir
        # 兼容早期原型约定的 backend/app/storage/personas；新建的人工 persona
        # 可放此处，运行时与 backend/storage/personas 一样被加载。
        self.app_custom_dir = BACKEND_DIR / "app" / "storage" / "personas"
        self._personas: dict[str, Persona] = {}
        self.reload()

    def _assign_ui(self, persona: Persona, custom_index: int) -> None:
        hint = UI_HINTS.get(persona.id, {})
        hexes = _first_hexes(persona.tokens)
        persona.ui = {
            "brand_color": hint.get(
                "brand_color",
                CUSTOM_COLOR_POOL[custom_index % len(CUSTOM_COLOR_POOL)]
                if persona.kind == "custom"
                else (hexes[0] if hexes else "#4338CA"),
            ),
            "full_name": hint.get(
                "full_name",
                f"{persona.name} · Custom Persona" if persona.kind == "custom" else persona.name,
            ),
            "palette": hint.get("palette", hexes),
            "abbr": hint.get("abbr", persona.name[:3].upper()),
            # taxonomy 分类；无内置提示（自定义 persona）时落 Other
            "category": hint.get("category", "Other"),
        }

    def reload(self) -> None:
        self._personas.clear()
        custom_index = 0
        if self.data_dir.is_dir():
            for path in sorted(self.data_dir.glob("*-persona.yaml")):
                try:
                    p = load_persona_yaml_file(path, kind="builtin")
                    self._assign_ui(p, 0)
                    self._personas[p.id] = p
                except Exception as exc:  # noqa: BLE001 — 单文件损坏不拖垮整表
                    print(f"[personas] 跳过 {path.name}: {exc}")
        for directory in (self.custom_dir, self.app_custom_dir):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*-persona.yaml")):
                try:
                    with open(path, encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if not isinstance(data, dict):
                        raise ValueError("persona 文件不是 YAML object")
                    # 手工 persona 可基于一个内置 persona 继承，避免复制后漂移。
                    base_id = data.pop("extends", None)
                    if base_id:
                        base_path = self.data_dir / f"{base_id}-persona.yaml"
                        if not re.fullmatch(r"[a-z0-9-]+", str(base_id)) or not base_path.is_file():
                            raise ValueError(f"非法或不存在的 extends: {base_id}")
                        with open(base_path, encoding="utf-8") as bf:
                            base = yaml.safe_load(bf)
                        if not isinstance(base, dict):
                            raise ValueError(f"继承基底无效: {base_path.name}")
                        def merge(left: dict, right: dict) -> dict:
                            out = dict(left)
                            for key, value in right.items():
                                if key == "L2_adaptations" and isinstance(value, list) and isinstance(out.get(key), list):
                                    out[key] = list(out[key]) + list(value)
                                else:
                                    out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
                            return out
                        data = merge(base, data)
                    p = load_persona_dict(data, source_file=path.name, kind="custom")
                    self._assign_ui(p, custom_index)
                    custom_index += 1
                    self._personas[p.id] = p
                except Exception as exc:  # noqa: BLE001
                    print(f"[personas] 跳过自定义 {path.name}: {exc}")

    def list(self) -> list[Persona]:
        return list(self._personas.values())

    def get(self, pid: str) -> Persona | None:
        return self._personas.get(pid)

    def register_custom(self, data: dict, source_name: str = "") -> Persona:
        """注册 Parser Agent 产出的自定义 persona 并落盘。

        主文件 `*-persona.yaml` 仅含范例形态三层正文；审计写入
        `*-parser-audit.yaml` sidecar，避免污染机构人格表示。
        """
        from .parser_agent import split_persona_documents

        persona_doc, audit_doc = split_persona_documents(data)
        # 装载用完整 data（含审计），便于 raw/provenance；落盘正文与 sidecar 分离
        persona = load_persona_dict(data, source_file=source_name, kind="custom")
        base_id = persona.id
        n = 2
        while persona.id in self._personas:
            persona.id = f"{base_id}-{n}"
            n += 1
        if persona.id != base_id:
            data.setdefault("institution", {})["id"] = persona.id
            persona_doc.setdefault("institution", {})["id"] = persona.id
        custom_count = sum(1 for p in self._personas.values() if p.kind == "custom")
        self._assign_ui(persona, custom_count)
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        out = self.custom_dir / f"{persona.id}-persona.yaml"
        with open(out, "w", encoding="utf-8") as f:
            yaml.safe_dump(persona_doc, f, allow_unicode=True, sort_keys=False)
        if audit_doc:
            audit_path = self.custom_dir / f"{persona.id}-parser-audit.yaml"
            with open(audit_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(audit_doc, f, allow_unicode=True, sort_keys=False)
        self._personas[persona.id] = persona
        return persona
