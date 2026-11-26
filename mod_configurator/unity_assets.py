"""Unity SerializedFile v22 解析器、汉化提取器与三层原地 4 字节补丁引擎（V2）。"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

KNOWN_VANILLA_D351_SHA256 = (
    "0B81412888B764991324E531949809786C3CB808C16FD3BB9902AD528E2B76ED"
)
KNOWN_LIMITED_MOD_1022_SHA256 = (
    "A20E9977E1714B02C34F4C53B9D13C16D6CD6BC2D849C8D4DA1D7787D67F5376"
)

TARGET_SCRIPTS: tuple[str, ...] = (
    "BuildConfig",
    "UnitConfig",
    "UpgradeConfig",
    "TacticalAbilityConfig",
)

SCRIPT_TAB_LABELS: dict[str, str] = {
    "BuildConfig": "建筑配置",
    "UnitConfig": "单位配置",
    "UpgradeConfig": "科技/学说升级",
    "TacticalAbilityConfig": "战术支援技能",
}

FACTION_NAMES: dict[int, str] = {
    0: "中立/雇佣兵",
    1: "帝国",
    2: "变种人",
    3: "机器人",
    4: "叛军",
}

# --- V2 F5: 实战归属分类常量与纠偏映射 ---
MERC_ASSET_NAMES: frozenset[str] = frozenset(
    {
        "merc_DreadMK0_Unit",
        "merc_LaserTank_Unit",
        "merc_Marauder_Unit",
        "merc_Mechbot_Unit",
        "merc_Rafa_Unit",
        "merc_Scorpion_Unit",
    }
)

ENEMY_TACTICAL_MUTANTS: frozenset[str] = frozenset(
    {
        "TacticalInfuse",
        "mutantBirdBombardment",
    }
)

AFFILIATION_LABELS: dict[str, str] = {
    "player_empire": "我方·帝国",
    "player_merc": "我方·雇佣兵",
    "enemy_mutants": "敌方·变种人",
    "enemy_rebels": "敌方·叛军",
    "enemy_robots": "敌方·机器人",
    "neutral": "中立/地图物件",
}

PLAYER_AFFILIATIONS: frozenset[str] = frozenset({"player_empire", "player_merc"})
ENEMY_AFFILIATIONS: frozenset[str] = frozenset(
    {"enemy_mutants", "enemy_rebels", "enemy_robots"}
)

AFFILIATION_FILTER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("player_empire", "我方（帝国）"),
    ("player_all", "我方 + 雇佣兵"),
    ("enemy_all", "敌方（全部敌方）"),
    ("enemy_mutants", "敌方·变种人"),
    ("enemy_rebels", "敌方·叛军"),
    ("enemy_robots", "敌方·机器人"),
    ("neutral", "中立/地图物件"),
    ("all", "全部（含敌我）"),
)

DEFAULT_AFFILIATION_FILTER = "player_empire"

READONLY_FIELDS: frozenset[str] = frozenset(
    {"faction", "onlyGlobalMinerals", "skipLoadIfBlocked"}
)

PRIMARY_FIELDS_BY_SCRIPT: dict[str, tuple[str, ...]] = {
    "BuildConfig": (
        "minerals",
        "energyPrice",
        "limitPrice",
        "gears",
        "timeCreation",
        "energyProduce",
        "limitProduce",
        "siloProduce",
        "maxCount",
    ),
    "UnitConfig": (
        "minerals",
        "energyPrice",
        "limitPrice",
        "gears",
        "timeCreation",
        "energyProduce",
        "limitProduce",
        "siloProduce",
        "maxCount",
    ),
    "UpgradeConfig": ("minerals", "limitPrice", "timeCreation"),
    "TacticalAbilityConfig": ("coolDown", "coolDownInStart", "useInFog"),
}

ADVANCED_FIELDS_BY_SCRIPT: dict[str, tuple[str, ...]] = {
    "BuildConfig": (),
    "UnitConfig": (),
    "UpgradeConfig": (
        "energyPrice",
        "gears",
        "energyProduce",
        "limitProduce",
        "siloProduce",
    ),
    "TacticalAbilityConfig": (
        "minerals",
        "energyPrice",
        "limitPrice",
        "gears",
        "timeCreation",
        "energyProduce",
        "limitProduce",
        "siloProduce",
    ),
}

EDITABLE_FIELDS_BY_SCRIPT: dict[str, tuple[str, ...]] = {
    script: PRIMARY_FIELDS_BY_SCRIPT[script] + ADVANCED_FIELDS_BY_SCRIPT[script]
    for script in TARGET_SCRIPTS
}

# --- V2 F6: 10 类挂载/地图组件剧本常量 ---
ATTACK_COMPONENT_CLASSES: tuple[str, ...] = (
    "AutoAttack_MG",
    "AutoAttack_Cannon",
    "AutoAttack_Projectile",
    "AutoAttack_Flamer",
    "AutoAttack_Laser",
)

MOVE_COMPONENT_CLASSES: tuple[str, ...] = (
    "TankPattern",
    "CarPattern",
    "SmoothPattern",
)

COMPONENT_SCRIPTS: tuple[str, ...] = (
    "HP",
    *ATTACK_COMPONENT_CLASSES,
    *MOVE_COMPONENT_CLASSES,
    "UnitComponent",
    "FogOfWarUnit",
    "Harvester",
    "OilPump",
    "Mineral",
    "Bunker",
    "HealRange",
    "Regeneration",
    "BuildComponent",
)

ALL_TARGET_SCRIPTS: tuple[str, ...] = TARGET_SCRIPTS + COMPONENT_SCRIPTS

READONLY_COMPONENT_FIELDS: frozenset[str] = frozenset({"hpType", "curHp"})

HP_TYPE_NAMES: dict[int, str] = {
    0: "载具 (0)",
    1: "步兵 (1)",
    2: "建筑 (2)",
}

ATTACK_DAMAGE_FIELDS: tuple[str, ...] = (
    "gun_cleanDamage",
    "gun_damageToVehicle",
    "gun_damageToInfantry",
    "gun_damageToBuild",
)

# 从已知 10 月 22 日 MOD (A20E9977...) 精确回填 10 个字段以重建 D-35-1 原版 (0B814128...)
LIMITED_MOD_1022_VANILLA_VALUES: dict[tuple[str, str], dict[str, int | float]] = {
    ("BuildConfig", "r_Barn_Build"): {"limitProduce": 30},
    ("BuildConfig", "r_BarnBig_Build"): {"gears": 40, "limitProduce": 180},
    ("BuildConfig", "r_Crane_Build"): {"gears": 50, "timeCreation": 40.0},
    ("UnitConfig", "r_Dreadnought_Unit"): {"gears": 50, "timeCreation": 90.0},
    ("UnitConfig", "r_MCV_BuildMobile"): {
        "energyProduce": 100,
        "limitProduce": 60,
        "siloProduce": 600,
    },
}

MAX_INT_VALUE = 999_999
MAX_FLOAT_VALUE = 99_999.0
MIN_NONZERO_BUILD_TIME = 0.5
LOCALIZATION_ASSET_NAME = "Localization_DUST_FRONT - Main"

ConfigKey = tuple[str, str]
ComponentKey = tuple[str, str, str, str, int]
WorldKey = tuple[str, str, str, int]


class AssetFormatError(ValueError):
    """Unity 资产文件格式或版本不符合预期，拒绝猜测偏移写入。"""


class ValidationError(ValueError):
    """字段名或参数数值校验未通过。"""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    fmt: str
    kind: str  # "int" | "float" | "bool"
    unit: str = ""
    min_val: int | float = 0
    max_val: int | float = MAX_INT_VALUE
    allow_zero_if_vanilla_zero: bool = False


FIELD_META: dict[str, FieldSpec] = {
    "minerals": FieldSpec("minerals", "矿物消耗", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "energyPrice": FieldSpec("energyPrice", "电力消耗", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "limitPrice": FieldSpec("limitPrice", "人口占用", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "gears": FieldSpec("gears", "零件需求", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "timeCreation": FieldSpec(
        "timeCreation",
        "建造/研发时间",
        "<f",
        "float",
        "秒",
        min_val=MIN_NONZERO_BUILD_TIME,
        max_val=MAX_FLOAT_VALUE,
        allow_zero_if_vanilla_zero=True,
    ),
    "energyProduce": FieldSpec("energyProduce", "提供电力", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "limitProduce": FieldSpec("limitProduce", "提供人口上限", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "siloProduce": FieldSpec("siloProduce", "提供储存上限", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "maxCount": FieldSpec("maxCount", "建造上限 (0=不限)", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "coolDown": FieldSpec("coolDown", "冷却时间", "<f", "float", "秒", min_val=0.0, max_val=MAX_FLOAT_VALUE),
    "coolDownInStart": FieldSpec("coolDownInStart", "开局进入冷却", "<i", "bool", min_val=0, max_val=1),
    "useInFog": FieldSpec("useInFog", "允许迷雾中使用", "<i", "bool", min_val=0, max_val=1),
}

# --- V2 组件字段 Spec 定义（含校验范围） ---
_HP_SPECS: dict[str, FieldSpec] = {
    "maxHp": FieldSpec("maxHp", "最大血量", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "maxExtraHp": FieldSpec("maxExtraHp", "额外护甲/护盾值", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "sidesArmore": FieldSpec("sidesArmore", "启用前后分面护甲", "<i", "bool", min_val=0, max_val=1),
    "frontArmore": FieldSpec("frontArmore", "正面护甲", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "rearArmore": FieldSpec("rearArmore", "背面护甲", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "fireResist": FieldSpec("fireResist", "火焰抗性", "<f", "float", min_val=-2.0, max_val=1.0),
    "gasResist": FieldSpec("gasResist", "毒气抗性", "<f", "float", min_val=-2.0, max_val=1.0),
    "areaResist": FieldSpec("areaResist", "爆炸范围抗性", "<f", "float", min_val=-2.0, max_val=1.0),
}

_ATTACK_SPECS: dict[str, FieldSpec] = {
    "MoveAttack": FieldSpec("MoveAttack", "允许移动射击", "<i", "bool", min_val=0, max_val=1),
    "SpeedTower": FieldSpec("SpeedTower", "炮塔转向速度", "<f", "float", "°/秒", min_val=0.0, max_val=5000.0),
    "fogCheck": FieldSpec("fogCheck", "受战争迷雾阻挡", "<i", "bool", min_val=0, max_val=1),
    "minRange": FieldSpec("minRange", "最小射程", "<f", "float", min_val=0.0, max_val=500.0),
    "range": FieldSpec("range", "基础射程", "<f", "float", min_val=0.0, max_val=500.0),
    "addRange": FieldSpec("addRange", "射程增量 (可负)", "<f", "float", min_val=-9.5, max_val=500.0),
    "coolDownShot": FieldSpec(
        "coolDownShot",
        "攻击冷却间隔",
        "<f",
        "float",
        "秒",
        min_val=0.05,
        max_val=60.0,
        allow_zero_if_vanilla_zero=True,
    ),
    "gun_range": FieldSpec("gun_range", "爆炸溅射半径", "<f", "float", min_val=0.0, max_val=100.0),
    "gun_cleanDamage": FieldSpec("gun_cleanDamage", "穿透保底伤害", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "gun_damageToVehicle": FieldSpec("gun_damageToVehicle", "对载具伤害", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "gun_damageToInfantry": FieldSpec("gun_damageToInfantry", "对步兵伤害", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "gun_damageToBuild": FieldSpec("gun_damageToBuild", "对建筑伤害", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
}

_MOVE_SPECS: dict[str, FieldSpec] = {
    "clearSpeed": FieldSpec("clearSpeed", "移动速度", "<f", "float", min_val=0.1, max_val=100.0),
    "angularSpeed": FieldSpec("angularSpeed", "车身转向角速度", "<f", "float", "°/秒", min_val=1.0, max_val=3600.0),
    "acceleration": FieldSpec("acceleration", "加速度", "<f", "float", min_val=0.1, max_val=500.0),
}

_UNIT_COMP_SPECS: dict[str, FieldSpec] = {
    "fowRadius": FieldSpec("fowRadius", "基础开雾视野半径", "<f", "float", min_val=1.0, max_val=200.0),
}

_FOW_UNIT_SPECS: dict[str, FieldSpec] = {
    "radius": FieldSpec("radius", "大视野组件开雾半径", "<f", "float", min_val=1.0, max_val=200.0),
}

_HARVESTER_SPECS: dict[str, FieldSpec] = {
    "onlyNormalMinerals": FieldSpec("onlyNormalMinerals", "仅采集普通矿石", "<i", "bool", min_val=0, max_val=1),
    "supplyMax": FieldSpec("supplyMax", "矿仓最大容量", "<i", "int", min_val=1, max_val=MAX_INT_VALUE),
}

_OIL_PUMP_SPECS: dict[str, FieldSpec] = {
    "cooldown": FieldSpec("cooldown", "产矿周期", "<f", "float", "秒", min_val=0.1, max_val=3600.0),
    "addRes": FieldSpec("addRes", "每次产矿量", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
}

_MINERAL_SPECS: dict[str, FieldSpec] = {
    "minerals": FieldSpec("minerals", "矿脉储量", "<i", "int", min_val=1, max_val=MAX_INT_VALUE),
}

_BUNKER_SPECS: dict[str, FieldSpec] = {
    "maxUnits": FieldSpec("maxUnits", "最大容纳小队数", "<i", "int", min_val=0, max_val=999),
    "addVision": FieldSpec("addVision", "驻军额外视野加成", "<i", "int", min_val=0, max_val=200),
    "canShootback": FieldSpec("canShootback", "允许舱内还击", "<i", "bool", min_val=0, max_val=1),
}

_HEAL_RANGE_SPECS: dict[str, FieldSpec] = {
    "coolDownScan": FieldSpec("coolDownScan", "治疗扫描间隔", "<f", "float", "秒", min_val=0.05, max_val=60.0),
    "range": FieldSpec("range", "治疗/修理半径", "<i", "int", min_val=0, max_val=200),
    "heal": FieldSpec("heal", "每次治疗/修复血量", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
}

_REGEN_SPECS: dict[str, FieldSpec] = {
    "RegenHP": FieldSpec("RegenHP", "每次被动回血量", "<i", "int", min_val=0, max_val=MAX_INT_VALUE),
    "timer": FieldSpec("timer", "被动回血周期", "<f", "float", "秒", min_val=0.1, max_val=3600.0),
}

_BUILD_COMP_SPECS: dict[str, FieldSpec] = {
    "discount": FieldSpec("discount", "生产费用折扣", "<f", "float", min_val=0.0, max_val=0.95),
    "timeMultiplier": FieldSpec("timeMultiplier", "队列生产速度倍率", "<f", "float", "倍", min_val=0.1, max_val=20.0),
    "maxBuildings": FieldSpec("maxBuildings", "同时队列/建筑上限", "<i", "int", min_val=0, max_val=999),
}

COMPONENT_FIELD_SPECS: dict[str, dict[str, FieldSpec]] = {
    "HP": _HP_SPECS,
    **{cls: _ATTACK_SPECS for cls in ATTACK_COMPONENT_CLASSES},
    **{cls: _MOVE_SPECS for cls in MOVE_COMPONENT_CLASSES},
    "UnitComponent": _UNIT_COMP_SPECS,
    "FogOfWarUnit": _FOW_UNIT_SPECS,
    "Harvester": _HARVESTER_SPECS,
    "OilPump": _OIL_PUMP_SPECS,
    "Mineral": _MINERAL_SPECS,
    "Bunker": _BUNKER_SPECS,
    "HealRange": _HEAL_RANGE_SPECS,
    "Regeneration": _REGEN_SPECS,
    "BuildComponent": _BUILD_COMP_SPECS,
}

# 统一 UI 展示辅助查找表（汇总 Config 与 Component 全部字段 Spec）
ALL_COMPONENT_FIELDS_FLAT: dict[str, FieldSpec] = {}
for _cls_specs in COMPONENT_FIELD_SPECS.values():
    for _fn, _sp in _cls_specs.items():
        ALL_COMPONENT_FIELDS_FLAT.setdefault(_fn, _sp)


def get_component_field_spec(comp_class: str, field_name: str) -> FieldSpec:
    """返回指定组件类字段的 FieldSpec。"""
    cls_specs = COMPONENT_FIELD_SPECS.get(comp_class)
    if cls_specs is None or field_name not in cls_specs:
        raise ValidationError(f"组件 {comp_class} 不支持字段 '{field_name}'")
    return cls_specs[field_name]


def resolve_affiliation(script: str, asset_name: str, raw_faction: int | None) -> str:
    """依据 PRD V2 规则判定配置对象的实战归属编码。"""
    if asset_name in MERC_ASSET_NAMES:
        return "player_merc"
    if script == "TacticalAbilityConfig":
        if asset_name in ENEMY_TACTICAL_MUTANTS:
            return "enemy_mutants"
        return "player_empire"
    if script == "UpgradeConfig":
        return "player_empire"
    if asset_name.startswith("r_"):
        return "player_empire"
    if asset_name.startswith("y_"):
        return "enemy_rebels"
    if asset_name.startswith("g_"):
        return "enemy_mutants"
    if asset_name.startswith("b_"):
        return "enemy_robots"

    fallback = {
        0: "neutral",
        1: "player_empire",
        2: "enemy_mutants",
        3: "enemy_robots",
        4: "enemy_rebels",
    }
    return fallback.get(raw_faction if raw_faction is not None else 0, "neutral")


def is_enemy_affiliation(affiliation: str) -> bool:
    """判定实战归属是否属于敌方 AI。"""
    return affiliation in ENEMY_AFFILIATIONS


def is_player_affiliation(affiliation: str) -> bool:
    """判定实战归属是否属于我方。"""
    return affiliation in PLAYER_AFFILIATIONS


def matches_affiliation_filter(affiliation: str, filter_code: str) -> bool:
    """根据顶部归属筛选编码判断给定实战归属是否可见。"""
    if filter_code == "all":
        return True
    if filter_code == "player_empire":
        return affiliation == "player_empire"
    if filter_code == "player_all":
        return affiliation in PLAYER_AFFILIATIONS
    if filter_code == "enemy_all":
        return affiliation in ENEMY_AFFILIATIONS
    return affiliation == filter_code


@dataclass(frozen=True)
class SerializedType:
    class_id: int
    is_stripped: int
    script_type_index: int


@dataclass(frozen=True)
class SerializedObject:
    path_id: int
    byte_start: int
    byte_size: int
    type_index: int
    class_id: int


@dataclass(frozen=True)
class ExternalRef:
    file_id: int  # 1-based index
    temp_empty: str
    guid: bytes
    ext_type: int
    asset_path: str


@dataclass(frozen=True)
class SerializedFileMeta:
    format_version: int
    meta_size: int
    file_size: int
    data_off: int
    endian: int
    unity_version: str
    target_platform: int
    enable_type_tree: bool
    types: list[SerializedType]
    objects: list[SerializedObject]
    script_types: list[tuple[int, int]]
    externals: list[ExternalRef]


@dataclass
class FieldLocation:
    name: str
    rel_offset: int
    abs_offset: int
    fmt: str
    kind: str
    value: int | float
    linked_abs_offsets: tuple[int, ...] = ()


@dataclass
class ComponentItem:
    key: ComponentKey
    config_script: str
    config_asset_name: str
    comp_class: str
    go_rel_path: str
    occ_index: int
    path_id: int
    byte_start: int
    byte_size: int
    body_abs: int
    fields: dict[str, FieldLocation]
    readonly_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def short_label(self) -> str:
        tail = self.go_rel_path.split("/")[-1] if "/" in self.go_rel_path else self.go_rel_path
        suffix = f" #{self.occ_index + 1}" if self.occ_index > 0 else ""
        return f"[{self.comp_class}] {tail}{suffix} ({self.go_rel_path})"


@dataclass
class WorldItem:
    key: WorldKey
    comp_class: str
    go_name: str
    occ_index: int
    display_name: str
    affiliation: str
    affiliation_name: str
    path_id: int
    byte_start: int
    byte_size: int
    body_abs: int
    fields: dict[str, FieldLocation]


@dataclass
class ConfigItem:
    script: str
    path_id: int
    byte_start: int
    byte_size: int
    asset_name: str
    name_key: str
    desc_key: str
    display_name: str
    display_desc: str
    faction: int | None
    faction_name: str
    fields: dict[str, FieldLocation]
    affiliation: str = "neutral"
    affiliation_name: str = "中立/地图物件"
    main_prefab_pid: int = 0
    components: list[ComponentItem] = field(default_factory=list)


@dataclass
class ParsedAssetsBundle:
    unity_version: str
    file_size: int
    data_off: int
    object_count: int
    ggm_file_id: int
    script_pids: dict[str, int]
    items: list[ConfigItem]
    by_key: dict[tuple[str, str], ConfigItem]
    localization_warning: str | None = None
    components: list[ComponentItem] = field(default_factory=list)
    components_by_key: dict[ComponentKey, ComponentItem] = field(default_factory=dict)
    world_items: list[WorldItem] = field(default_factory=list)
    world_by_key: dict[WorldKey, WorldItem] = field(default_factory=dict)
    component_script_pids: dict[str, int] = field(default_factory=dict)


def compute_sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    """计算内存字节块的 SHA-256（大写十六进制）。"""
    return hashlib.sha256(data).hexdigest().upper()


def compute_sha256_file(path: str | Path) -> str:
    """分块计算磁盘文件的 SHA-256（大写十六进制）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().upper()


def _read_c_string(buf: bytes | bytearray | memoryview, pos: int, limit: int) -> tuple[str, int]:
    """读取以 NUL 结尾的 ASCII/UTF-8 字符串。"""
    end = bytes(buf).find(b"\x00", pos, limit)
    if end < 0:
        raise AssetFormatError(f"C-String 未在边界 {limit} 内遇到终止符 (pos={pos})")
    text = bytes(buf[pos:end]).decode("utf-8", "replace")
    return text, end + 1


def _read_aligned_string(
    buf: bytes | bytearray | memoryview,
    pos: int,
    limit: int,
    *,
    allow_unpadded_tail: bool = False,
) -> tuple[str, int]:
    """读取 Unity 4 字节对齐长度前缀字符串。"""
    if pos + 4 > limit:
        raise AssetFormatError(f"AlignedString 长度字段越界: pos={pos}, limit={limit}")
    (length,) = struct.unpack_from("<i", buf, pos)
    pos += 4
    if length < 0 or pos + length > limit:
        raise AssetFormatError(
            f"AlignedString 长度异常: length={length}, pos={pos}, limit={limit}"
        )
    text = bytes(buf[pos : pos + length]).decode("utf-8", "replace")
    end_str = pos + length
    aligned = (end_str + 3) & ~3
    if aligned > limit:
        if allow_unpadded_tail:
            aligned = limit
        else:
            raise AssetFormatError(
                f"AlignedString 对齐后越界: aligned={aligned}, limit={limit}"
            )
    return text, aligned


def parse_serialized_file_meta(data: bytes | bytearray | memoryview) -> SerializedFileMeta:
    """按 Unity SerializedFile v22 规范解析文件头与元数据表。"""
    total_len = len(data)
    if total_len < 48:
        raise AssetFormatError(f"文件长度过短 ({total_len} B)，不是有效的 Unity SerializedFile")

    try:
        _, _, format_version, _ = struct.unpack_from(">IIII", data, 0)
        endian = data[16]
        if format_version != 22:
            raise AssetFormatError(
                f"不支持的 Unity SerializedFile 版本: v{format_version}（仅支持 v22）"
            )
        if endian != 0:
            raise AssetFormatError(
                f"不支持的字节序标识 endian={endian}（仅支持小端序 0）"
            )

        meta_size, file_size, data_off, _ = struct.unpack_from(">IQQQ", data, 20)
        if file_size != total_len:
            raise AssetFormatError(
                f"资产头 file_size={file_size} 与实际文件字节数 {total_len} 不一致"
            )
        if data_off > file_size:
            raise AssetFormatError(
                f"资产头 data_off={data_off} 超出文件大小 {file_size}"
            )

        pos = 48
        meta_limit = min(total_len, data_off if data_off > 48 else total_len)
        unity_version, pos = _read_c_string(data, pos, meta_limit)
        if pos + 5 > meta_limit:
            raise AssetFormatError("SerializedFile 平台与 TypeTree 标志位越界")
        target_platform, enable_type_tree = struct.unpack_from("<i?", data, pos)
        pos += 5
        if enable_type_tree:
            raise AssetFormatError(
                "检测到 enable_type_tree=True，当前工具仅支持无 TypeTree 的发行版资产"
            )

        (type_count,) = struct.unpack_from("<i", data, pos)
        pos += 4
        if type_count < 0 or type_count > 100_000:
            raise AssetFormatError(f"非法的 type_count={type_count}")
        types: list[SerializedType] = []
        for _ in range(type_count):
            if pos + 7 > meta_limit:
                raise AssetFormatError("m_Types 记录越界")
            class_id, is_stripped, script_type_index = struct.unpack_from("<iBh", data, pos)
            pos += 7
            if class_id == 114:
                pos += 16  # m_ScriptID
            pos += 16  # m_OldTypeHash
            if pos > meta_limit:
                raise AssetFormatError("m_Types 哈希区越界")
            types.append(SerializedType(class_id, is_stripped, script_type_index))

        (obj_count,) = struct.unpack_from("<i", data, pos)
        pos += 4
        if obj_count < 0 or obj_count > 5_000_000:
            raise AssetFormatError(f"非法的 obj_count={obj_count}")
        pos = (pos + 3) & ~3
        if pos + obj_count * 24 > meta_limit:
            raise AssetFormatError("m_Objects 对象表越界")

        objects: list[SerializedObject] = []
        for _ in range(obj_count):
            path_id, byte_start, byte_size, type_index = struct.unpack_from("<qQII", data, pos)
            pos += 24
            if type_index >= len(types):
                raise AssetFormatError(
                    f"对象 path_id={path_id} 引用了非法 type_index={type_index}"
                )
            objects.append(
                SerializedObject(
                    path_id=path_id,
                    byte_start=byte_start,
                    byte_size=byte_size,
                    type_index=type_index,
                    class_id=types[type_index].class_id,
                )
            )

        (script_count,) = struct.unpack_from("<i", data, pos)
        pos += 4
        if script_count < 0 or script_count > 100_000:
            raise AssetFormatError(f"非法的 script_count={script_count}")
        script_types: list[tuple[int, int]] = []
        for _ in range(script_count):
            if pos + 4 > meta_limit:
                raise AssetFormatError("m_ScriptTypes.fileID 越界")
            (fid,) = struct.unpack_from("<i", data, pos)
            pos = (pos + 4 + 3) & ~3
            if pos + 8 > meta_limit:
                raise AssetFormatError("m_ScriptTypes.pathID 越界")
            (pid,) = struct.unpack_from("<q", data, pos)
            pos += 8
            script_types.append((fid, pid))

        (ext_count,) = struct.unpack_from("<i", data, pos)
        pos += 4
        if ext_count < 0 or ext_count > 10_000:
            raise AssetFormatError(f"非法的 ext_count={ext_count}")
        externals: list[ExternalRef] = []
        for idx in range(1, ext_count + 1):
            temp_empty, pos = _read_c_string(data, pos, meta_limit)
            if pos + 20 > meta_limit:
                raise AssetFormatError("m_Externals GUID/type 越界")
            guid = bytes(data[pos : pos + 16])
            pos += 16
            (ext_type,) = struct.unpack_from("<i", data, pos)
            pos += 4
            asset_path, pos = _read_c_string(data, pos, meta_limit)
            externals.append(ExternalRef(idx, temp_empty, guid, ext_type, asset_path))

    except AssetFormatError:
        raise
    except (struct.error, IndexError, ValueError) as exc:
        raise AssetFormatError(f"SerializedFile v22 元数据解析失败: {exc}") from exc

    return SerializedFileMeta(
        format_version=format_version,
        meta_size=meta_size,
        file_size=file_size,
        data_off=data_off,
        endian=endian,
        unity_version=unity_version,
        target_platform=target_platform,
        enable_type_tree=enable_type_tree,
        types=types,
        objects=objects,
        script_types=script_types,
        externals=externals,
    )


def find_ggm_file_id(externals: list[ExternalRef]) -> int:
    """从 m_Externals 表动态定位 globalgamemanagers.assets 的 1-based fileID。"""
    for ext in externals:
        basename = PurePosixPath(ext.asset_path.replace("\\", "/")).name.lower()
        if basename == "globalgamemanagers.assets":
            return ext.file_id
    raise AssetFormatError(
        "m_Externals 外部依赖表中未找到 globalgamemanagers.assets"
    )


def resolve_all_script_pids(
    ggm_path: str | Path,
    required_classes: tuple[str, ...] = ALL_TARGET_SCRIPTS,
) -> dict[str, int]:
    """解析 globalgamemanagers.assets 中指定 Assembly-CSharp MonoScript 类对应的 PathID。"""
    ggm_path = Path(ggm_path)
    if not ggm_path.is_file():
        raise AssetFormatError(f"缺少 globalgamemanagers.assets: {ggm_path}")

    data = ggm_path.read_bytes()
    meta = parse_serialized_file_meta(data)
    target_set = set(required_classes)
    result: dict[str, int] = {}

    for obj in meta.objects:
        if obj.class_id != 115:
            continue
        obj_abs = meta.data_off + obj.byte_start
        obj_end = obj_abs + obj.byte_size
        if obj_end > len(data):
            raise AssetFormatError(
                f"globalgamemanagers MonoScript path_id={obj.path_id} 数据越界"
            )
        p = obj_abs
        _, p = _read_aligned_string(data, p, obj_end)  # m_Name
        if p + 20 > obj_end:
            raise AssetFormatError(
                f"MonoScript path_id={obj.path_id} 头部长度不足"
            )
        p += 4 + 16  # m_ExecutionOrder (<i) + m_PropertiesHash (16B)
        class_name, p = _read_aligned_string(data, p, obj_end)
        _, p = _read_aligned_string(data, p, obj_end)  # m_Namespace
        assembly_name, p = _read_aligned_string(
            data, p, obj_end, allow_unpadded_tail=True
        )
        if (
            class_name in target_set
            and assembly_name.removesuffix(".dll") == "Assembly-CSharp"
        ):
            if class_name in result:
                raise AssetFormatError(
                    f"发现重复的目标 MonoScript 类 {class_name}: "
                    f"pathID={result[class_name]} 与 {obj.path_id}"
                )
            result[class_name] = obj.path_id

    missing = [name for name in required_classes if name not in result]
    if missing:
        raise AssetFormatError(
            f"globalgamemanagers.assets 中未找到以下必需脚本: {', '.join(missing)}"
        )
    return result


def resolve_script_pids(ggm_path: str | Path) -> dict[str, int]:
    """解析 V1 的 4 个配置类对应的 MonoScript PathID（保留向下兼容签名）。"""
    return resolve_all_script_pids(ggm_path, TARGET_SCRIPTS)


def load_localization(resources_path: str | Path | None) -> tuple[dict[str, str], str | None]:
    """从 resources.assets 读取汉化/英文 CSV 词典，失败时优雅降级返回警告。"""
    if resources_path is None:
        return {}, "未提供 resources.assets 路径，界面将降级显示内部资产名"
    res_path = Path(resources_path)
    if not res_path.is_file():
        return {}, f"未找到汉化文件 {res_path.name}，已降级显示内部资产名"

    try:
        data = res_path.read_bytes()
        meta = parse_serialized_file_meta(data)
        for obj in meta.objects:
            if obj.class_id != 49:
                continue
            obj_abs = meta.data_off + obj.byte_start
            obj_end = obj_abs + obj.byte_size
            if obj_end > len(data):
                continue
            m_name, p = _read_aligned_string(data, obj_abs, obj_end)
            if m_name != LOCALIZATION_ASSET_NAME:
                continue
            csv_text, _ = _read_aligned_string(
                data, p, obj_end, allow_unpadded_tail=True
            )
            reader = csv.reader(io.StringIO(csv_text.lstrip("\ufeff")))
            header = next(reader, None)
            if not header or len(header) < 3:
                return {}, f"{LOCALIZATION_ASSET_NAME} CSV 表头列数异常，已降级显示内部名"
            loc_map: dict[str, str] = {}
            for row in reader:
                if len(row) >= 3:
                    key = row[0].strip()
                    if key:
                        loc_map[key] = row[2].strip()
            return loc_map, None
        return {}, f"resources.assets 中未找到 {LOCALIZATION_ASSET_NAME}，已降级显示内部名"
    except Exception as exc:
        return {}, f"读取汉化表失败（已降级显示内部名）: {exc}"


def _validate_by_spec(
    spec: FieldSpec,
    raw_value: Any,
    vanilla_value: int | float | None = None,
    *,
    context_name: str = "",
) -> int | float:
    """通用字段值校验（覆盖 V1 Config 与 V2 Component / World 全字段规则）。"""
    prefix = f"{context_name} " if context_name else ""
    if spec.kind == "bool":
        if isinstance(raw_value, bool):
            return 1 if raw_value else 0
        if isinstance(raw_value, int) and raw_value in (0, 1):
            return int(raw_value)
        if isinstance(raw_value, str):
            norm = raw_value.strip().lower()
            if norm in ("1", "true", "是"):
                return 1
            if norm in ("0", "false", "否"):
                return 0
        raise ValidationError(
            f"{prefix}布尔字段 '{spec.label}' 仅允许 0/1 或勾选开关，收到: {raw_value!r}"
        )

    if spec.kind == "int":
        if isinstance(raw_value, bool):
            raise ValidationError(f"{prefix}整数字段 '{spec.label}' 不接受布尔值: {raw_value!r}")
        if isinstance(raw_value, float):
            raise ValidationError(f"{prefix}整数字段 '{spec.label}' 禁止填入小数: {raw_value!r}")
        if isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                raise ValidationError(f"{prefix}整数字段 '{spec.label}' 不能为空")
            try:
                val = int(text, 10)
            except ValueError as exc:
                raise ValidationError(
                    f"{prefix}整数字段 '{spec.label}' 必须为有效整数，收到: {raw_value!r}"
                ) from exc
        elif isinstance(raw_value, int):
            val = int(raw_value)
        else:
            raise ValidationError(f"{prefix}整数字段 '{spec.label}' 类型非法: {raw_value!r}")

        if val < int(spec.min_val) or val > int(spec.max_val):
            raise ValidationError(
                f"{prefix}整数字段 '{spec.label}' 超出允许范围 [{int(spec.min_val)}, {int(spec.max_val)}]: {val}"
            )
        return val

    # float
    if isinstance(raw_value, bool):
        raise ValidationError(f"{prefix}浮点字段 '{spec.label}' 不接受布尔值: {raw_value!r}")
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            raise ValidationError(f"{prefix}浮点字段 '{spec.label}' 不能为空")
        try:
            val_f = float(text)
        except ValueError as exc:
            raise ValidationError(
                f"{prefix}浮点字段 '{spec.label}' 必须为有效数字，收到: {raw_value!r}"
            ) from exc
    elif isinstance(raw_value, (int, float)):
        val_f = float(raw_value)
    else:
        raise ValidationError(f"{prefix}浮点字段 '{spec.label}' 类型非法: {raw_value!r}")

    if not math.isfinite(val_f):
        raise ValidationError(f"{prefix}浮点字段 '{spec.label}' 禁止为 NaN 或 Inf")

    if spec.allow_zero_if_vanilla_zero:
        if val_f < 0.0 or val_f > float(spec.max_val):
            raise ValidationError(
                f"{prefix}浮点字段 '{spec.label}' 超出允许范围 [0, {float(spec.max_val):g}]: {val_f}"
            )
        if vanilla_value is not None and float(vanilla_value) > 0.0 and val_f < float(spec.min_val):
            raise ValidationError(
                f"{prefix}原版 '{spec.label}' > 0 的对象不能低于 {float(spec.min_val):g}（防除零或异常卡死），当前: {val_f}"
            )
        return val_f

    if val_f < float(spec.min_val) or val_f > float(spec.max_val):
        raise ValidationError(
            f"{prefix}浮点字段 '{spec.label}' 超出允许范围 [{float(spec.min_val):g}, {float(spec.max_val):g}]: {val_f}"
        )
    return val_f


def validate_field_value(
    script: str,
    field_name: str,
    raw_value: Any,
    vanilla_value: int | float | None = None,
) -> int | float:
    """按白名单和类型范围校验单个配置字段的值，返回规范化的 Python int/float。"""
    if script not in EDITABLE_FIELDS_BY_SCRIPT:
        raise ValidationError(f"不支持的脚本类型: {script}")
    if field_name in READONLY_FIELDS:
        raise ValidationError(f"字段 '{field_name}' 为只读字段，禁止修改")
    if field_name not in EDITABLE_FIELDS_BY_SCRIPT[script]:
        raise ValidationError(f"脚本 {script} 不允许编辑字段 '{field_name}'")

    spec = FIELD_META[field_name]
    return _validate_by_spec(spec, raw_value, vanilla_value=vanilla_value)


def validate_component_field_value(
    comp_class: str,
    field_name: str,
    raw_value: Any,
    vanilla_value: int | float | None = None,
) -> int | float:
    """按组件白名单和类型范围校验组件/地图资源字段值。"""
    if field_name in READONLY_COMPONENT_FIELDS:
        raise ValidationError(f"组件字段 '{field_name}' 为只读或自动联动字段，禁止直接修改")
    spec = get_component_field_spec(comp_class, field_name)
    return _validate_by_spec(spec, raw_value, vanilla_value=vanilla_value, context_name=comp_class)


def float32_roundtrip(val: float) -> float:
    """将 float 转为 IEEE-754 单精度后再解包为 Python float。"""
    return struct.unpack("<f", struct.pack("<f", float(val)))[0]


def _spec_values_equal(spec: FieldSpec, a: int | float, b: int | float) -> bool:
    if spec.kind in ("int", "bool"):
        return int(a) == int(b)
    return struct.pack("<f", float(a)) == struct.pack("<f", float(b))


def values_equal(field_name: str, a: int | float, b: int | float) -> bool:
    """比较两个配置字段值在写入二进制后是否完全等价。"""
    return _spec_values_equal(FIELD_META[field_name], a, b)


def component_values_equal(comp_class: str, field_name: str, a: int | float, b: int | float) -> bool:
    """比较两个组件字段值在写入二进制后是否完全等价。"""
    return _spec_values_equal(get_component_field_spec(comp_class, field_name), a, b)


def _read_game_object(
    data: bytes | bytearray | memoryview,
    meta: SerializedFileMeta,
    objs_by_pid: Mapping[int, SerializedObject],
    go_pid: int,
) -> tuple[str, list[int]]:
    """读取 Unity GameObject (ClassID=1) 的名称和同文件组件 PathID 列表。"""
    obj = objs_by_pid.get(go_pid)
    if obj is None or obj.class_id != 1:
        raise AssetFormatError(f"无效的 GameObject path_id={go_pid}")
    obj_abs = meta.data_off + obj.byte_start
    obj_end = obj_abs + obj.byte_size
    if obj_end > len(data) or obj.byte_size < 12:
        raise AssetFormatError(f"GameObject path_id={go_pid} 数据越界")
    p = obj_abs
    (comp_count,) = struct.unpack_from("<i", data, p)
    p += 4
    if comp_count < 0 or comp_count > 1000 or p + comp_count * 12 + 8 > obj_end:
        raise AssetFormatError(f"GameObject path_id={go_pid} 组件列表越界 (count={comp_count})")
    comp_pids: list[int] = []
    for _ in range(comp_count):
        fid, pid = struct.unpack_from("<iq", data, p)
        p += 12
        if fid == 0 and pid != 0:
            comp_pids.append(pid)
    p += 4  # m_Layer
    go_name, _ = _read_aligned_string(data, p, obj_end, allow_unpadded_tail=True)
    return go_name, comp_pids


def _read_transform_children(
    data: bytes | bytearray | memoryview,
    meta: SerializedFileMeta,
    objs_by_pid: Mapping[int, SerializedObject],
    tr_pid: int,
) -> list[int]:
    """读取 Transform/RectTransform (ClassID 4/224) 的同文件子 Transform PathID 列表。"""
    obj = objs_by_pid.get(tr_pid)
    if obj is None or obj.class_id not in (4, 224):
        return []
    obj_abs = meta.data_off + obj.byte_start
    obj_end = obj_abs + obj.byte_size
    if obj_end > len(data) or obj.byte_size < 56:
        raise AssetFormatError(f"Transform path_id={tr_pid} 数据越界")
    p = obj_abs + 52  # m_GameObject(12) + rot(16) + pos(12) + scale(12)
    (child_count,) = struct.unpack_from("<i", data, p)
    p += 4
    if child_count < 0 or child_count > 2000 or p + child_count * 12 > obj_end:
        raise AssetFormatError(f"Transform path_id={tr_pid} m_Children 越界 (count={child_count})")
    children: list[int] = []
    for _ in range(child_count):
        fid, pid = struct.unpack_from("<iq", data, p)
        p += 12
        if fid == 0 and pid in objs_by_pid:
            children.append(pid)
    return children


def _read_component_header(
    data: bytes | bytearray | memoryview,
    meta: SerializedFileMeta,
    obj: SerializedObject,
    ggm_file_id: int,
    pid_to_comp_script: Mapping[int, str],
) -> tuple[str, int, int, str, int, int, int] | None:
    """读取 MonoBehaviour 组件头，命中 18 个目标组件类之一时返回头部详情。"""
    if obj.class_id != 114 or obj.byte_size < 28:
        return None
    obj_abs = meta.data_off + obj.byte_start
    obj_end = obj_abs + obj.byte_size
    if obj_end > len(data):
        return None
    go_fid, go_pid = struct.unpack_from("<iq", data, obj_abs)
    sc_fid, sc_pid = struct.unpack_from("<iq", data, obj_abs + 16)
    if sc_fid != ggm_file_id or sc_pid not in pid_to_comp_script:
        return None
    comp_class = pid_to_comp_script[sc_pid]
    m_name, body_abs = _read_aligned_string(data, obj_abs + 28, obj_end, allow_unpadded_tail=True)
    return comp_class, go_fid, go_pid, m_name, obj_abs, body_abs, obj_end


def _extract_component_fields(
    data: bytes | bytearray | memoryview,
    comp_class: str,
    obj: SerializedObject,
    obj_abs: int,
    body_abs: int,
    obj_end: int,
    context_label: str,
) -> tuple[dict[str, FieldLocation], dict[str, Any]] | None:
    """按 PRD V2 实测偏移提取并严格校验组件字段。对于 Mineral 若为 36B MineralPrefabDeploy 则返回 None。"""
    body_len = obj_end - body_abs
    specs = COMPONENT_FIELD_SPECS[comp_class]
    fields: dict[str, FieldLocation] = {}
    readonly_meta: dict[str, Any] = {}

    def _add(fname: str, body_rel: int, *, linked_body_rels: tuple[int, ...] = ()) -> None:
        abs_off = body_abs + body_rel
        rel_off = abs_off - obj_abs
        if body_rel < 0 or abs_off + 4 > obj_end or rel_off < 0 or rel_off + 4 > obj.byte_size:
            raise AssetFormatError(
                f"{context_label} ({comp_class}.{fname}) 字段偏移越界: "
                f"body_rel={body_rel}, body_len={body_len}"
            )
        linked_abs: list[int] = []
        for l_rel in linked_body_rels:
            l_abs = body_abs + l_rel
            if l_rel < 0 or l_abs + 4 > obj_end:
                raise AssetFormatError(
                    f"{context_label} ({comp_class}.{fname}) 联动字段偏移越界: body_rel={l_rel}"
                )
            linked_abs.append(l_abs)

        sp = specs[fname]
        (val,) = struct.unpack_from(sp.fmt, data, abs_off)
        if sp.kind == "float" and not math.isfinite(float(val)):
            raise AssetFormatError(f"{context_label} ({comp_class}.{fname}) 读到非有限浮点值: {val!r}")
        fields[fname] = FieldLocation(
            name=fname,
            rel_offset=rel_off,
            abs_offset=abs_off,
            fmt=sp.fmt,
            kind=sp.kind,
            value=val,
            linked_abs_offsets=tuple(linked_abs),
        )

    if comp_class == "HP":
        if body_len != 100:
            raise AssetFormatError(f"{context_label} HP 组件长度异常: body_len={body_len} (期望 100)")
        (hp_type,) = struct.unpack_from("<i", data, body_abs + 0x0C)
        readonly_meta["hpType"] = hp_type
        readonly_meta["hpTypeName"] = HP_TYPE_NAMES.get(hp_type, f"未知类型 ({hp_type})")
        _add("maxHp", 0x10, linked_body_rels=(0x14,))
        _add("maxExtraHp", 0x18)
        _add("sidesArmore", 0x20)
        _add("frontArmore", 0x24)
        _add("rearArmore", 0x28)
        _add("fireResist", 0x2C)
        _add("gasResist", 0x30)
        _add("areaResist", 0x34)
    elif comp_class in ATTACK_COMPONENT_CLASSES:
        if body_len < 256:
            raise AssetFormatError(f"{context_label} {comp_class} 长度过短: body_len={body_len}")
        _add("MoveAttack", 0x30)
        _add("SpeedTower", 0x6C)
        _add("fogCheck", 0xB4)
        _add("minRange", 0xB8)
        _add("range", 0xBC)
        _add("addRange", 0xC0)
        _add("coolDownShot", 0xD4)
        _add("gun_range", 0xE4)
        _add("gun_cleanDamage", 0xE8)
        _add("gun_damageToVehicle", 0xEC)
        _add("gun_damageToInfantry", 0xF0)
        _add("gun_damageToBuild", 0xF4)
    elif comp_class in MOVE_COMPONENT_CLASSES:
        expected_len = {"TankPattern": 212, "CarPattern": 208, "SmoothPattern": 200}[comp_class]
        if body_len != expected_len:
            raise AssetFormatError(
                f"{context_label} {comp_class} 长度异常: body_len={body_len} (期望 {expected_len})"
            )
        _add("clearSpeed", 0x18)
        _add("angularSpeed", 0x20)
        _add("acceleration", 0x28)
    elif comp_class == "UnitComponent":
        if body_len < 4:
            raise AssetFormatError(f"{context_label} UnitComponent 长度过短: body_len={body_len}")
        _add("fowRadius", body_len - 4)
        fow_val = float(fields["fowRadius"].value)
        if fow_val < 1.0 or fow_val > 200.0:
            raise AssetFormatError(
                f"{context_label} UnitComponent.fowRadius 原值异常 ({fow_val})，预期在 [1.0, 200.0]"
            )
    elif comp_class == "FogOfWarUnit":
        if body_len != 8:
            raise AssetFormatError(f"{context_label} FogOfWarUnit 长度异常: body_len={body_len}")
        _add("radius", 0x04)
    elif comp_class == "Harvester":
        if body_len != 84:
            raise AssetFormatError(f"{context_label} Harvester 长度异常: body_len={body_len}")
        _add("onlyNormalMinerals", 0x30)
        _add("supplyMax", 0x34)
    elif comp_class == "OilPump":
        if body_len != 32:
            raise AssetFormatError(f"{context_label} OilPump 长度异常: body_len={body_len}")
        _add("cooldown", 0x18)
        _add("addRes", 0x1C)
    elif comp_class == "Mineral":
        if body_len < 100:
            return None  # 过滤 36B 的 MineralPrefabDeploy
        _add("minerals", 0x04)
    elif comp_class == "Bunker":
        if body_len < 80:
            raise AssetFormatError(f"{context_label} Bunker 长度过短: body_len={body_len}")
        _add("addVision", 0x34)
        _add("canShootback", 0x3C)
        _add("maxUnits", 0x4C)
    elif comp_class == "HealRange":
        if body_len != 116:
            raise AssetFormatError(f"{context_label} HealRange 长度异常: body_len={body_len}")
        _add("coolDownScan", 0x0C)
        _add("range", 0x2C)
        _add("heal", 0x58)
    elif comp_class == "Regeneration":
        if body_len != 44:
            raise AssetFormatError(f"{context_label} Regeneration 长度异常: body_len={body_len}")
        _add("RegenHP", 0x24)
        _add("timer", 0x28)
    elif comp_class == "BuildComponent":
        if body_len < 0x10:
            raise AssetFormatError(f"{context_label} BuildComponent 长度过短: body_len={body_len}")
        (n_cnt,) = struct.unpack_from("<i", data, body_abs + 0x0C)
        if n_cnt < 0 or n_cnt > 50:
            raise AssetFormatError(f"{context_label} BuildComponent contentMain.count={n_cnt} 异常")
        tail = 0x10 + n_cnt * 12
        _add("discount", tail + 0x08)
        _add("timeMultiplier", tail + 0x0C)
        _add("maxBuildings", tail + 0x10)
    else:
        raise AssetFormatError(f"未实现的组件解析类: {comp_class}")

    return fields, readonly_meta


def _format_world_display_name(comp_class: str, go_name: str, same_name_count: int, occ_idx: int) -> str:
    if comp_class == "Mineral":
        suffix = f" #{occ_idx + 1}" if same_name_count > 1 else ""
        return f"矿脉资源点 ({go_name}{suffix})"
    if go_name == "CaptureTerritory":
        return "占领产矿区 (CaptureTerritory)"
    if go_name == "SiloTower_midStrat":
        return "战略油井/矿塔 (SiloTower_midStrat)"
    return f"独立油井 ({go_name})"


def parse_sharedassets_configs(
    sharedassets_data: bytes | bytearray | memoryview,
    ggm_path: str | Path,
    resources_path: str | Path | None = None,
) -> ParsedAssetsBundle:
    """解析 sharedassets0.assets 中的配置、Prefab 挂载组件及独立地图资源对象。"""
    meta = parse_serialized_file_meta(sharedassets_data)
    ggm_file_id = find_ggm_file_id(meta.externals)
    all_pids = resolve_all_script_pids(ggm_path, ALL_TARGET_SCRIPTS)
    script_pids = {s: all_pids[s] for s in TARGET_SCRIPTS}
    component_script_pids = {s: all_pids[s] for s in COMPONENT_SCRIPTS}
    pid_to_config_script = {pid: name for name, pid in script_pids.items()}
    pid_to_comp_script = {pid: name for name, pid in component_script_pids.items()}

    loc_map, loc_warning = load_localization(resources_path)

    total_len = len(sharedassets_data)
    items: list[ConfigItem] = []
    by_key: dict[tuple[str, str], ConfigItem] = {}
    main_prefab_refs: dict[tuple[str, str], tuple[int, int]] = {}
    objs_by_pid: dict[int, SerializedObject] = {o.path_id: o for o in meta.objects}

    for obj in meta.objects:
        if obj.class_id != 114:
            continue
        obj_abs = meta.data_off + obj.byte_start
        obj_end = obj_abs + obj.byte_size
        if obj_end > total_len or obj.byte_size < 28:
            continue

        go_fid, go_pid = struct.unpack_from("<iq", sharedassets_data, obj_abs)
        if go_fid != 0 or go_pid != 0:
            continue

        sc_fid, sc_pid = struct.unpack_from("<iq", sharedassets_data, obj_abs + 16)
        if sc_fid != ggm_file_id or sc_pid not in pid_to_config_script:
            continue

        script = pid_to_config_script[sc_pid]
        asset_name, p = _read_aligned_string(sharedassets_data, obj_abs + 28, obj_end)
        if not asset_name:
            raise AssetFormatError(f"发现空 m_Name 的 {script} 对象 path_id={obj.path_id}")

        key = (script, asset_name)
        if key in by_key:
            raise AssetFormatError(
                f"发现重复的 ({script}, {asset_name}) 对象: path_id={obj.path_id}"
            )

        skip_icon = 40 if script in ("BuildConfig", "UnitConfig", "UpgradeConfig") else 16
        if p + skip_icon > obj_end:
            raise AssetFormatError(f"{script}/{asset_name} 图标引用区越界")
        p += skip_icon

        name_key, p = _read_aligned_string(sharedassets_data, p, obj_end)
        desc_key, p = _read_aligned_string(sharedassets_data, p, obj_end)

        price_abs = p
        if price_abs + 44 > obj_end:
            raise AssetFormatError(f"{script}/{asset_name} PriceResources 越界")

        (
            minerals,
            energy_price,
            limit_price,
            gears,
            time_creation,
            _only_global,
            energy_produce,
            limit_produce,
            silo_produce,
            _skip_blocked,
            req_count,
        ) = struct.unpack_from("<iiiifiiiiii", sharedassets_data, price_abs)

        if req_count < 0 or req_count > 100:
            raise AssetFormatError(
                f"{script}/{asset_name} requiredConfigs.count={req_count} 异常"
            )

        after_req = price_abs + 44 + req_count * 12
        if after_req > obj_end:
            raise AssetFormatError(
                f"{script}/{asset_name} requiredConfigs 数组越界"
            )

        fields: dict[str, FieldLocation] = {}

        def _add_field(fname: str, abs_off: int, val: int | float) -> None:
            spec = FIELD_META[fname]
            rel_off = abs_off - obj_abs
            if rel_off < 0 or rel_off + 4 > obj.byte_size:
                raise AssetFormatError(
                    f"{script}/{asset_name}.{fname} 字段偏移越界: "
                    f"rel={rel_off}, byte_size={obj.byte_size}"
                )
            fields[fname] = FieldLocation(
                name=fname,
                rel_offset=rel_off,
                abs_offset=abs_off,
                fmt=spec.fmt,
                kind=spec.kind,
                value=val,
            )

        _add_field("minerals", price_abs + 0x00, minerals)
        _add_field("energyPrice", price_abs + 0x04, energy_price)
        _add_field("limitPrice", price_abs + 0x08, limit_price)
        _add_field("gears", price_abs + 0x0C, gears)
        _add_field("timeCreation", price_abs + 0x10, time_creation)
        _add_field("energyProduce", price_abs + 0x18, energy_produce)
        _add_field("limitProduce", price_abs + 0x1C, limit_produce)
        _add_field("siloProduce", price_abs + 0x20, silo_produce)

        faction: int | None = None
        faction_name = "通用"
        mp_fid = 0
        mp_pid = 0

        if script in ("BuildConfig", "UnitConfig"):
            if after_req + 8 > obj_end:
                raise AssetFormatError(
                    f"{script}/{asset_name} RtsObjectConfig 尾部字段越界"
                )
            faction, max_count = struct.unpack_from("<ii", sharedassets_data, after_req)
            faction_name = FACTION_NAMES.get(faction, f"未知阵营({faction})")
            _add_field("maxCount", after_req + 0x04, max_count)

            # V2: 读取 RtsObjectConfig.upgrades 与 mainPrefab
            after_max = after_req + 8
            if after_max + 0x20 > obj_end:
                raise AssetFormatError(
                    f"{script}/{asset_name} RtsObjectConfig mainPrefab 头越界"
                )
            (u_cnt,) = struct.unpack_from("<i", sharedassets_data, after_max + 0x1C)
            if u_cnt < 0 or u_cnt > 50:
                raise AssetFormatError(
                    f"{script}/{asset_name} upgrades.count={u_cnt} 异常"
                )
            mp_off = after_max + 0x20 + u_cnt * 12
            if mp_off + 12 > obj_end:
                raise AssetFormatError(
                    f"{script}/{asset_name} mainPrefab PPtr 越界"
                )
            mp_fid, mp_pid = struct.unpack_from("<iq", sharedassets_data, mp_off)
            if (mp_fid, mp_pid) != (0, 0):
                main_prefab_refs[key] = (mp_fid, mp_pid)
        elif script == "TacticalAbilityConfig":
            if after_req + 12 > obj_end:
                raise AssetFormatError(
                    f"{script}/{asset_name} TacticalAbilityConfig 尾部字段越界"
                )
            cd_start, use_in_fog, cool_down = struct.unpack_from(
                "<iif", sharedassets_data, after_req
            )
            _add_field("coolDownInStart", after_req + 0x00, cd_start)
            _add_field("useInFog", after_req + 0x04, use_in_fog)
            _add_field("coolDown", after_req + 0x08, cool_down)

        expected = set(EDITABLE_FIELDS_BY_SCRIPT[script])
        if set(fields) != expected:
            raise AssetFormatError(
                f"{script}/{asset_name} 字段解析集合不完整: {set(fields)} != {expected}"
            )

        affiliation = resolve_affiliation(script, asset_name, faction)
        affiliation_name = AFFILIATION_LABELS[affiliation]
        raw_name = loc_map.get(name_key, "").strip() if name_key else ""
        display_name = raw_name if raw_name else f"[无译名] {asset_name}"
        display_desc = loc_map.get(desc_key, "").strip() if desc_key else ""

        item = ConfigItem(
            script=script,
            path_id=obj.path_id,
            byte_start=obj.byte_start,
            byte_size=obj.byte_size,
            asset_name=asset_name,
            name_key=name_key,
            desc_key=desc_key,
            display_name=display_name,
            display_desc=display_desc,
            faction=faction,
            faction_name=faction_name,
            fields=fields,
            affiliation=affiliation,
            affiliation_name=affiliation_name,
            main_prefab_pid=mp_pid if mp_fid == 0 else 0,
        )
        items.append(item)
        by_key[key] = item

    if not items:
        raise AssetFormatError("sharedassets0.assets 中未解析到任何目标配置对象")

    # --- V2 F6 Stage 1: 解析各 BuildConfig/UnitConfig 挂载的 Prefab 组件树 ---
    components: list[ComponentItem] = []
    components_by_key: dict[ComponentKey, ComponentItem] = {}
    linked_comp_pids: set[int] = set()

    for key, (mp_fid, mp_pid) in main_prefab_refs.items():
        if mp_fid != 0 or mp_pid not in objs_by_pid:
            raise AssetFormatError(
                f"{key[0]}/{key[1]} mainPrefab 引用无效: fileID={mp_fid}, pathID={mp_pid}"
            )
        item = by_key[key]
        mp_obj = objs_by_pid[mp_pid]
        if mp_obj.class_id == 1:
            root_go_pid = mp_pid
        elif mp_obj.class_id == 114:
            mp_abs = meta.data_off + mp_obj.byte_start
            if mp_obj.byte_size < 12 or mp_abs + 12 > total_len:
                raise AssetFormatError(f"{key[0]}/{key[1]} mainPrefab MonoBehaviour 头部越界")
            gf, gp = struct.unpack_from("<iq", sharedassets_data, mp_abs)
            if gf != 0 or gp not in objs_by_pid or objs_by_pid[gp].class_id != 1:
                raise AssetFormatError(
                    f"{key[0]}/{key[1]} mainPrefab MonoBehaviour 未指向有效 GameObject"
                )
            root_go_pid = gp
        else:
            raise AssetFormatError(
                f"{key[0]}/{key[1]} mainPrefab class_id={mp_obj.class_id} 非 GameObject/MonoBehaviour"
            )

        root_name, _ = _read_game_object(sharedassets_data, meta, objs_by_pid, root_go_pid)
        stack: list[tuple[int, str]] = [(root_go_pid, root_name)]
        visited_go: set[int] = set()
        occ_counter: Counter[tuple[str, str]] = Counter()

        while stack:
            go_pid, rel_path = stack.pop()
            if go_pid in visited_go:
                continue
            visited_go.add(go_pid)

            _, comp_pids = _read_game_object(sharedassets_data, meta, objs_by_pid, go_pid)
            tr_pids: list[int] = []
            for cpid in comp_pids:
                c_obj = objs_by_pid.get(cpid)
                if c_obj is None:
                    continue
                if c_obj.class_id in (4, 224):
                    tr_pids.append(cpid)
                    continue
                hdr = _read_component_header(
                    sharedassets_data, meta, c_obj, ggm_file_id, pid_to_comp_script
                )
                if hdr is None:
                    continue
                comp_class, _, _, _, c_abs, body_abs, c_end = hdr
                if comp_class == "Mineral":
                    continue
                occ_key = (comp_class, rel_path)
                occ_idx = occ_counter[occ_key]
                occ_counter[occ_key] += 1

                comp_key: ComponentKey = (item.script, item.asset_name, comp_class, rel_path, occ_idx)
                extracted = _extract_component_fields(
                    sharedassets_data,
                    comp_class,
                    c_obj,
                    c_abs,
                    body_abs,
                    c_end,
                    context_label=f"{item.script}/{item.asset_name}@{rel_path}",
                )
                if extracted is None:
                    continue
                comp_fields, readonly_meta = extracted
                comp_item = ComponentItem(
                    key=comp_key,
                    config_script=item.script,
                    config_asset_name=item.asset_name,
                    comp_class=comp_class,
                    go_rel_path=rel_path,
                    occ_index=occ_idx,
                    path_id=cpid,
                    byte_start=c_obj.byte_start,
                    byte_size=c_obj.byte_size,
                    body_abs=body_abs,
                    fields=comp_fields,
                    readonly_meta=readonly_meta,
                )
                item.components.append(comp_item)
                components.append(comp_item)
                components_by_key[comp_key] = comp_item
                linked_comp_pids.add(cpid)

            child_gos: list[tuple[int, str]] = []
            for tpid in tr_pids:
                for c_tr in _read_transform_children(sharedassets_data, meta, objs_by_pid, tpid):
                    c_tr_obj = objs_by_pid[c_tr]
                    tr_abs = meta.data_off + c_tr_obj.byte_start
                    cgf, cgp = struct.unpack_from("<iq", sharedassets_data, tr_abs)
                    if cgf == 0 and cgp in objs_by_pid and objs_by_pid[cgp].class_id == 1:
                        cname_go, _ = _read_game_object(
                            sharedassets_data, meta, objs_by_pid, cgp
                        )
                        child_gos.append((cgp, f"{rel_path}/{cname_go}"))
            for cg in reversed(child_gos):
                stack.append(cg)

    # --- V2 F6 Stage 2: 收集独立地图资源点（标准 Mineral + 未绑定 OilPump） ---
    raw_world_records: list[tuple[str, str, SerializedObject, int, int, int, dict[str, FieldLocation]]] = []
    for obj in meta.objects:
        if obj.class_id != 114:
            continue
        hdr = _read_component_header(
            sharedassets_data, meta, obj, ggm_file_id, pid_to_comp_script
        )
        if hdr is None:
            continue
        comp_class, go_fid, go_pid, m_name, o_abs, body_abs, o_end = hdr
        if comp_class not in ("Mineral", "OilPump"):
            continue
        if comp_class == "OilPump" and obj.path_id in linked_comp_pids:
            continue
        extracted = _extract_component_fields(
            sharedassets_data,
            comp_class,
            obj,
            o_abs,
            body_abs,
            o_end,
            context_label=f"world/{comp_class}(pid={obj.path_id})",
        )
        if extracted is None:
            continue
        comp_fields, _ = extracted
        go_name = m_name or comp_class
        if go_fid == 0 and go_pid in objs_by_pid and objs_by_pid[go_pid].class_id == 1:
            go_name, _ = _read_game_object(sharedassets_data, meta, objs_by_pid, go_pid)
        raw_world_records.append((comp_class, go_name, obj, o_abs, body_abs, o_end, comp_fields))

    world_name_totals = Counter((rec[0], rec[1]) for rec in raw_world_records)
    world_occ_counter: Counter[tuple[str, str]] = Counter()
    world_items: list[WorldItem] = []
    world_by_key: dict[WorldKey, WorldItem] = {}

    for comp_class, go_name, obj, _o_abs, body_abs, _o_end, comp_fields in raw_world_records:
        occ_idx = world_occ_counter[(comp_class, go_name)]
        world_occ_counter[(comp_class, go_name)] += 1
        wkey: WorldKey = ("world", comp_class, go_name, occ_idx)
        disp = _format_world_display_name(
            comp_class, go_name, world_name_totals[(comp_class, go_name)], occ_idx
        )
        witem = WorldItem(
            key=wkey,
            comp_class=comp_class,
            go_name=go_name,
            occ_index=occ_idx,
            display_name=disp,
            affiliation="neutral",
            affiliation_name=AFFILIATION_LABELS["neutral"],
            path_id=obj.path_id,
            byte_start=obj.byte_start,
            byte_size=obj.byte_size,
            body_abs=body_abs,
            fields=comp_fields,
        )
        world_items.append(witem)
        world_by_key[wkey] = witem

    return ParsedAssetsBundle(
        unity_version=meta.unity_version,
        file_size=meta.file_size,
        data_off=meta.data_off,
        object_count=len(meta.objects),
        ggm_file_id=ggm_file_id,
        script_pids=script_pids,
        items=items,
        by_key=by_key,
        localization_warning=loc_warning,
        components=components,
        components_by_key=components_by_key,
        world_items=world_items,
        world_by_key=world_by_key,
        component_script_pids=component_script_pids,
    )


def patch_sharedassets_bytes(
    base_data: bytes | bytearray,
    bundle: ParsedAssetsBundle,
    overrides: Mapping[tuple[str, str], Mapping[str, int | float]],
    component_overrides: Mapping[ComponentKey, Mapping[str, int | float]] | None = None,
    world_overrides: Mapping[WorldKey, Mapping[str, int | float]] | None = None,
) -> tuple[bytearray, int]:
    """基于干净基准字节数组，原地覆写三层改动字段并返回 (新字节数组, 写入逻辑字段数)。"""
    buf = bytearray(base_data)
    expected_len = len(buf)
    patched_fields = 0
    written_offsets: dict[int, tuple[bytes, str]] = {}

    def _pack_checked(abs_off: int, fmt: str, val: int | float, desc: str) -> None:
        if abs_off < bundle.data_off or abs_off + 4 > expected_len:
            raise AssetFormatError(f"写入越界拦截: {desc} abs_offset={abs_off}")
        raw_bytes = struct.pack(fmt, val)
        prev = written_offsets.get(abs_off)
        if prev is not None:
            prev_bytes, prev_desc = prev
            if prev_bytes != raw_bytes:
                raise ValidationError(
                    f"共享 Prefab/字段地址冲突: {desc} 与 {prev_desc} 指向同一偏移 0x{abs_off:X}，"
                    "但写入了不同数值，请统一或保留其中一方改动"
                )
            return
        written_offsets[abs_off] = (raw_bytes, desc)
        buf[abs_off : abs_off + 4] = raw_bytes

    # 1. Config 层（保持与 V1 100% 兼容）
    for (script, asset_name), field_changes in overrides.items():
        if not field_changes:
            continue
        item = bundle.by_key.get((script, asset_name))
        if item is None:
            raise ValidationError(f"资产中未找到目标对象: {script}/{asset_name}")

        for field_name, new_val in field_changes.items():
            if field_name not in item.fields:
                raise ValidationError(f"{script}/{asset_name} 不存在可调字段 {field_name}")
            floc = item.fields[field_name]
            checked = validate_field_value(
                script, field_name, new_val, vanilla_value=floc.value
            )
            _pack_checked(floc.abs_offset, floc.fmt, checked, f"{script}/{asset_name}.{field_name}")
            patched_fields += 1

    # 2. Prefab Component 层（含 HP.maxHp -> curHp 联动双写）
    if component_overrides:
        for ckey, field_changes in component_overrides.items():
            if not field_changes:
                continue
            comp = bundle.components_by_key.get(ckey)
            if comp is None:
                raise ValidationError(f"资产中未找到目标组件: {ckey}")
            for field_name, new_val in field_changes.items():
                if field_name not in comp.fields:
                    raise ValidationError(f"组件 {ckey} 不存在可调字段 {field_name}")
                floc = comp.fields[field_name]
                checked = validate_component_field_value(
                    comp.comp_class, field_name, new_val, vanilla_value=floc.value
                )
                _pack_checked(floc.abs_offset, floc.fmt, checked, f"{ckey}.{field_name}")
                for linked_abs in floc.linked_abs_offsets:
                    _pack_checked(linked_abs, floc.fmt, checked, f"{ckey}.{field_name}(linked)")
                patched_fields += 1

    # 3. World 资源点层
    if world_overrides:
        for wkey, field_changes in world_overrides.items():
            if not field_changes:
                continue
            witem = bundle.world_by_key.get(wkey)
            if witem is None:
                raise ValidationError(f"资产中未找到地图资源点: {wkey}")
            for field_name, new_val in field_changes.items():
                if field_name not in witem.fields:
                    raise ValidationError(f"地图资源点 {wkey} 不存在可调字段 {field_name}")
                floc = witem.fields[field_name]
                checked = validate_component_field_value(
                    witem.comp_class, field_name, new_val, vanilla_value=floc.value
                )
                _pack_checked(floc.abs_offset, floc.fmt, checked, f"{wkey}.{field_name}")
                patched_fields += 1

    if len(buf) != expected_len:
        raise AssertionError("原地补丁意外改变了文件长度")
    return buf, patched_fields


def reconstruct_vanilla_from_limited_mod(
    mod_data: bytes | bytearray,
    ggm_path: str | Path,
) -> bytearray:
    """将已知 10/22 有限修改 MOD 字节回填 10 个原版字段，校验精确还原出 D-35-1 原版基准。"""
    src_sha = compute_sha256_bytes(mod_data)
    if src_sha != KNOWN_LIMITED_MOD_1022_SHA256:
        raise AssetFormatError(
            f"输入文件 SHA-256 ({src_sha}) 不是已知 10/22 MOD ({KNOWN_LIMITED_MOD_1022_SHA256})"
        )

    bundle = parse_sharedassets_configs(mod_data, ggm_path, resources_path=None)
    buf = bytearray(mod_data)
    for (script, asset_name), revert_fields in LIMITED_MOD_1022_VANILLA_VALUES.items():
        item = bundle.by_key.get((script, asset_name))
        if item is None:
            raise AssetFormatError(f"反向重建原版时缺少对象: {script}/{asset_name}")
        for field_name, vanilla_val in revert_fields.items():
            floc = item.fields[field_name]
            struct.pack_into(floc.fmt, buf, floc.abs_offset, vanilla_val)

    rebuilt_sha = compute_sha256_bytes(buf)
    if rebuilt_sha != KNOWN_VANILLA_D351_SHA256:
        raise AssetFormatError(
            f"反向重建的原版基准校验失败: got={rebuilt_sha}, expected={KNOWN_VANILLA_D351_SHA256}"
        )
    return buf
