"""预设读写校验（Schema v1 兼容 + v2 扩展）、原版对比 Diff 计算与批量倍率工具（V2）。"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .unity_assets import (
    ATTACK_COMPONENT_CLASSES,
    ATTACK_DAMAGE_FIELDS,
    COMPONENT_FIELD_SPECS,
    ComponentKey,
    ConfigKey,
    EDITABLE_FIELDS_BY_SCRIPT,
    ENEMY_AFFILIATIONS,
    FIELD_META,
    MAX_FLOAT_VALUE,
    MAX_INT_VALUE,
    MIN_NONZERO_BUILD_TIME,
    MOVE_COMPONENT_CLASSES,
    PLAYER_AFFILIATIONS,
    ParsedAssetsBundle,
    READONLY_COMPONENT_FIELDS,
    READONLY_FIELDS,
    ValidationError,
    WorldKey,
    component_values_equal,
    get_component_field_spec,
    validate_component_field_value,
    validate_field_value,
    values_equal,
)

PRESET_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, 2)

OverridesMap = dict[ConfigKey, dict[str, int | float]]
ComponentOverridesMap = dict[ComponentKey, dict[str, int | float]]
WorldOverridesMap = dict[WorldKey, dict[str, int | float]]


class PresetError(ValueError):
    """预设文件格式错误或字段校验未通过。"""


@dataclass(frozen=True)
class PresetData:
    schema_version: int
    name: str
    description: str
    target_game_version: str
    changes: list[dict[str, Any]]
    component_changes: list[dict[str, Any]] = field(default_factory=list)
    world_changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PresetLoadResult:
    preset: PresetData
    overrides: OverridesMap
    warnings: list[str]
    component_overrides: ComponentOverridesMap = field(default_factory=dict)
    world_overrides: WorldOverridesMap = field(default_factory=dict)


def _normalize_by_kind(kind: str, value: int | float) -> int | float:
    if kind in ("int", "bool"):
        return int(value)
    val_f = float(value)
    rounded = round(val_f, 4)
    if struct.pack("<f", rounded) == struct.pack("<f", val_f):
        return rounded
    return val_f


def normalize_json_value(field_name: str, value: int | float) -> int | float:
    """将配置字段值规范化为适合 JSON 存储与直观展示的值。"""
    return _normalize_by_kind(FIELD_META[field_name].kind, value)


def normalize_component_json_value(
    comp_class: str, field_name: str, value: int | float
) -> int | float:
    """将组件/地图资源字段值规范化为适合 JSON 存储与直观展示的值。"""
    spec = get_component_field_spec(comp_class, field_name)
    return _normalize_by_kind(spec.kind, value)


def clone_overrides(
    overrides: Mapping[ConfigKey, Mapping[str, int | float]],
) -> OverridesMap:
    """深拷贝配置层 overrides 字典。"""
    cloned: OverridesMap = {}
    for key, fields in overrides.items():
        if fields:
            cloned[key] = dict(fields)
    return cloned


def clone_component_overrides(
    component_overrides: Mapping[ComponentKey, Mapping[str, int | float]],
) -> ComponentOverridesMap:
    """深拷贝 Prefab 组件层 overrides 字典。"""
    cloned: ComponentOverridesMap = {}
    for key, fields in component_overrides.items():
        if fields:
            cloned[key] = dict(fields)
    return cloned


def clone_world_overrides(
    world_overrides: Mapping[WorldKey, Mapping[str, int | float]],
) -> WorldOverridesMap:
    """深拷贝地图资源点层 overrides 字典。"""
    cloned: WorldOverridesMap = {}
    for key, fields in world_overrides.items():
        if fields:
            cloned[key] = dict(fields)
    return cloned


def compute_diff_from_bundles(
    vanilla_bundle: ParsedAssetsBundle,
    current_bundle: ParsedAssetsBundle,
) -> OverridesMap:
    """比对当前游戏配置层与原版基准（V1 兼容接口）。"""
    diffs: OverridesMap = {}
    for key, v_item in vanilla_bundle.by_key.items():
        c_item = current_bundle.by_key.get(key)
        if c_item is None:
            continue
        item_diffs: dict[str, int | float] = {}
        for fname, v_loc in v_item.fields.items():
            c_loc = c_item.fields.get(fname)
            if c_loc is None:
                continue
            if not values_equal(fname, c_loc.value, v_loc.value):
                item_diffs[fname] = normalize_json_value(fname, c_loc.value)
        if item_diffs:
            diffs[key] = item_diffs
    return diffs


def compute_all_diffs_from_bundles(
    vanilla_bundle: ParsedAssetsBundle,
    current_bundle: ParsedAssetsBundle,
) -> tuple[OverridesMap, ComponentOverridesMap, WorldOverridesMap]:
    """比对当前游戏三层资产与原版基准，提取配置/挂载组件/地图资源点全部差异。"""
    config_diffs = compute_diff_from_bundles(vanilla_bundle, current_bundle)

    comp_diffs: ComponentOverridesMap = {}
    for ckey, v_comp in vanilla_bundle.components_by_key.items():
        c_comp = current_bundle.components_by_key.get(ckey)
        if c_comp is None:
            continue
        c_fields: dict[str, int | float] = {}
        for fname, v_loc in v_comp.fields.items():
            c_loc = c_comp.fields.get(fname)
            if c_loc is None:
                continue
            if not component_values_equal(v_comp.comp_class, fname, c_loc.value, v_loc.value):
                c_fields[fname] = normalize_component_json_value(
                    v_comp.comp_class, fname, c_loc.value
                )
        if c_fields:
            comp_diffs[ckey] = c_fields

    world_diffs: WorldOverridesMap = {}
    for wkey, v_w in vanilla_bundle.world_by_key.items():
        c_w = current_bundle.world_by_key.get(wkey)
        if c_w is None:
            continue
        w_fields: dict[str, int | float] = {}
        for fname, v_loc in v_w.fields.items():
            c_loc = c_w.fields.get(fname)
            if c_loc is None:
                continue
            if not component_values_equal(v_w.comp_class, fname, c_loc.value, v_loc.value):
                w_fields[fname] = normalize_component_json_value(
                    v_w.comp_class, fname, c_loc.value
                )
        if w_fields:
            world_diffs[wkey] = w_fields

    return config_diffs, comp_diffs, world_diffs


def list_preset_files(presets_dir: str | Path) -> list[Path]:
    """列出 presets 目录下的全部 JSON 预设文件。"""
    pdir = Path(presets_dir)
    if not pdir.is_dir():
        return []
    return sorted((p for p in pdir.glob("*.json") if p.is_file()), key=lambda p: p.name.lower())


def load_preset_file(
    preset_path: str | Path,
    vanilla_bundle: ParsedAssetsBundle,
) -> PresetLoadResult:
    """加载并严格校验 Schema v1 / v2 预设 JSON，对未知对象/组件给出警告并跳过。"""
    path = Path(preset_path)
    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PresetError(f"无法读取预设文件 {path.name}: {exc}") from exc

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise PresetError(f"预设 JSON 语法损坏 ({path.name}): {exc}") from exc

    if not isinstance(raw, dict):
        raise PresetError(f"预设顶层必须为 JSON 对象 ({path.name})")

    schema_ver = raw.get("schema_version")
    if isinstance(schema_ver, bool) or schema_ver not in SUPPORTED_SCHEMA_VERSIONS:
        raise PresetError(
            f"不支持的预设 schema_version={schema_ver!r}（仅支持 {SUPPORTED_SCHEMA_VERSIONS}）"
        )

    name = str(raw.get("name") or path.stem)
    description = str(raw.get("description") or "")
    target_ver = str(raw.get("target_game_version") or "")
    changes = raw.get("changes", [])
    if not isinstance(changes, list):
        raise PresetError(f"预设缺少或格式错误的 changes 数组 ({path.name})")

    overrides: OverridesMap = {}
    component_overrides: ComponentOverridesMap = {}
    world_overrides: WorldOverridesMap = {}
    warnings: list[str] = []

    # 1. Config 层 changes
    for idx, entry in enumerate(changes):
        if not isinstance(entry, dict):
            raise PresetError(f"changes[{idx}] 必须为 JSON 对象")
        script = entry.get("script")
        asset_name = entry.get("asset_name")
        field_name = entry.get("field")
        if (
            not isinstance(script, str)
            or not isinstance(asset_name, str)
            or not isinstance(field_name, str)
        ):
            raise PresetError(f"changes[{idx}] 的 script / asset_name / field 必须为字符串")
        if "value" not in entry:
            raise PresetError(f"changes[{idx}] 缺少 value 字段")
        raw_value = entry["value"]

        if field_name in READONLY_FIELDS:
            raise PresetError(f"changes[{idx}] 尝试修改只读字段 '{field_name}'，已拒绝")
        if script not in EDITABLE_FIELDS_BY_SCRIPT or field_name not in EDITABLE_FIELDS_BY_SCRIPT[script]:
            raise PresetError(f"changes[{idx}] 包含未开放或未知字段: {script}.{field_name}")

        item = vanilla_bundle.by_key.get((script, asset_name))
        if item is None:
            try:
                validate_field_value(script, field_name, raw_value, vanilla_value=None)
            except ValidationError as exc:
                raise PresetError(f"changes[{idx}] 数值非法: {exc}") from exc
            warnings.append(f"已跳过当前游戏版本中不存在的对象: {script}/{asset_name}.{field_name}")
            continue

        vanilla_val = item.fields[field_name].value
        try:
            checked = validate_field_value(script, field_name, raw_value, vanilla_value=vanilla_val)
        except ValidationError as exc:
            raise PresetError(f"changes[{idx}] ({script}/{asset_name}.{field_name}) {exc}") from exc

        if not values_equal(field_name, checked, vanilla_val):
            overrides.setdefault((script, asset_name), {})[field_name] = normalize_json_value(
                field_name, checked
            )
        else:
            existing = overrides.get((script, asset_name))
            if existing and field_name in existing:
                del existing[field_name]
                if not existing:
                    del overrides[(script, asset_name)]

    component_changes: list[dict[str, Any]] = []
    world_changes: list[dict[str, Any]] = []

    if schema_ver == 2:
        raw_comp = raw.get("component_changes", [])
        if not isinstance(raw_comp, list):
            raise PresetError(f"预设格式错误的 component_changes 数组 ({path.name})")
        component_changes = list(raw_comp)

        for idx, entry in enumerate(component_changes):
            if not isinstance(entry, dict):
                raise PresetError(f"component_changes[{idx}] 必须为 JSON 对象")
            c_script = entry.get("config_script")
            c_asset = entry.get("config_asset_name")
            comp_class = entry.get("comp_class")
            go_rel_path = entry.get("go_rel_path")
            occ_index = entry.get("occ_index", 0)
            field_name = entry.get("field")
            if (
                not isinstance(c_script, str)
                or not isinstance(c_asset, str)
                or not isinstance(comp_class, str)
                or not isinstance(go_rel_path, str)
                or isinstance(occ_index, bool)
                or not isinstance(occ_index, int)
                or occ_index < 0
                or not isinstance(field_name, str)
            ):
                raise PresetError(f"component_changes[{idx}] 键字段类型非法")
            if "value" not in entry:
                raise PresetError(f"component_changes[{idx}] 缺少 value 字段")
            raw_value = entry["value"]

            if field_name in READONLY_COMPONENT_FIELDS:
                raise PresetError(f"component_changes[{idx}] 尝试修改只读字段 '{field_name}'，已拒绝")
            if comp_class not in COMPONENT_FIELD_SPECS or field_name not in COMPONENT_FIELD_SPECS[comp_class]:
                raise PresetError(
                    f"component_changes[{idx}] 包含未开放或未知字段: {comp_class}.{field_name}"
                )

            ckey: ComponentKey = (c_script, c_asset, comp_class, go_rel_path, occ_index)
            comp = vanilla_bundle.components_by_key.get(ckey)
            if comp is None:
                try:
                    validate_component_field_value(
                        comp_class, field_name, raw_value, vanilla_value=None
                    )
                except ValidationError as exc:
                    raise PresetError(f"component_changes[{idx}] 数值非法: {exc}") from exc
                warnings.append(
                    f"已跳过当前版本不存在的组件: {c_script}/{c_asset} [{comp_class}] {go_rel_path}#{occ_index}.{field_name}"
                )
                continue

            vanilla_val = comp.fields[field_name].value
            try:
                checked = validate_component_field_value(
                    comp_class, field_name, raw_value, vanilla_value=vanilla_val
                )
            except ValidationError as exc:
                raise PresetError(f"component_changes[{idx}] {exc}") from exc

            if not component_values_equal(comp_class, field_name, checked, vanilla_val):
                component_overrides.setdefault(ckey, {})[field_name] = (
                    normalize_component_json_value(comp_class, field_name, checked)
                )
            else:
                existing = component_overrides.get(ckey)
                if existing and field_name in existing:
                    del existing[field_name]
                    if not existing:
                        del component_overrides[ckey]

        raw_world = raw.get("world_changes", [])
        if not isinstance(raw_world, list):
            raise PresetError(f"预设格式错误的 world_changes 数组 ({path.name})")
        world_changes = list(raw_world)

        for idx, entry in enumerate(world_changes):
            if not isinstance(entry, dict):
                raise PresetError(f"world_changes[{idx}] 必须为 JSON 对象")
            comp_class = entry.get("comp_class")
            go_name = entry.get("go_name")
            occ_index = entry.get("occ_index", 0)
            field_name = entry.get("field")
            if (
                not isinstance(comp_class, str)
                or not isinstance(go_name, str)
                or isinstance(occ_index, bool)
                or not isinstance(occ_index, int)
                or occ_index < 0
                or not isinstance(field_name, str)
            ):
                raise PresetError(f"world_changes[{idx}] 键字段类型非法")
            if "value" not in entry:
                raise PresetError(f"world_changes[{idx}] 缺少 value 字段")
            raw_value = entry["value"]

            if comp_class not in ("Mineral", "OilPump") or field_name not in COMPONENT_FIELD_SPECS[comp_class]:
                raise PresetError(
                    f"world_changes[{idx}] 包含不支持的地图资源字段: {comp_class}.{field_name}"
                )

            wkey: WorldKey = ("world", comp_class, go_name, occ_index)
            witem = vanilla_bundle.world_by_key.get(wkey)
            if witem is None:
                try:
                    validate_component_field_value(
                        comp_class, field_name, raw_value, vanilla_value=None
                    )
                except ValidationError as exc:
                    raise PresetError(f"world_changes[{idx}] 数值非法: {exc}") from exc
                warnings.append(
                    f"已跳过当前版本不存在的地图资源: {comp_class}/{go_name}#{occ_index}.{field_name}"
                )
                continue

            vanilla_val = witem.fields[field_name].value
            try:
                checked = validate_component_field_value(
                    comp_class, field_name, raw_value, vanilla_value=vanilla_val
                )
            except ValidationError as exc:
                raise PresetError(f"world_changes[{idx}] {exc}") from exc

            if not component_values_equal(comp_class, field_name, checked, vanilla_val):
                world_overrides.setdefault(wkey, {})[field_name] = (
                    normalize_component_json_value(comp_class, field_name, checked)
                )
            else:
                existing = world_overrides.get(wkey)
                if existing and field_name in existing:
                    del existing[field_name]
                    if not existing:
                        del world_overrides[wkey]

    preset = PresetData(
        schema_version=schema_ver,
        name=name,
        description=description,
        target_game_version=target_ver,
        changes=list(changes),
        component_changes=component_changes,
        world_changes=world_changes,
    )
    return PresetLoadResult(
        preset=preset,
        overrides=overrides,
        warnings=warnings,
        component_overrides=component_overrides,
        world_overrides=world_overrides,
    )


def save_preset_file(
    preset_path: str | Path,
    name: str,
    description: str,
    vanilla_bundle: ParsedAssetsBundle,
    overrides: Mapping[ConfigKey, Mapping[str, int | float]],
    *,
    component_overrides: Mapping[ComponentKey, Mapping[str, int | float]] | None = None,
    world_overrides: Mapping[WorldKey, Mapping[str, int | float]] | None = None,
    target_game_version: str = "D-35-1",
) -> Path:
    """将当前相对于原版的三层修改导出为 Schema v2 预设 JSON。"""
    path = Path(preset_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    changes: list[dict[str, Any]] = []

    for key in sorted(overrides.keys()):
        script, asset_name = key
        item = vanilla_bundle.by_key.get(key)
        field_map = overrides[key]
        for field_name in sorted(field_map.keys()):
            val = field_map[field_name]
            vanilla_val = item.fields[field_name].value if item else None
            checked = validate_field_value(script, field_name, val, vanilla_value=vanilla_val)
            if vanilla_val is not None and values_equal(field_name, checked, vanilla_val):
                continue
            changes.append(
                {
                    "script": script,
                    "asset_name": asset_name,
                    "field": field_name,
                    "value": normalize_json_value(field_name, checked),
                }
            )

    component_changes: list[dict[str, Any]] = []
    if component_overrides:
        for ckey in sorted(component_overrides.keys()):
            c_script, c_asset, comp_class, go_rel_path, occ_index = ckey
            comp = vanilla_bundle.components_by_key.get(ckey)
            field_map = component_overrides[ckey]
            for field_name in sorted(field_map.keys()):
                val = field_map[field_name]
                vanilla_val = comp.fields[field_name].value if comp else None
                checked = validate_component_field_value(
                    comp_class, field_name, val, vanilla_value=vanilla_val
                )
                if vanilla_val is not None and component_values_equal(
                    comp_class, field_name, checked, vanilla_val
                ):
                    continue
                component_changes.append(
                    {
                        "config_script": c_script,
                        "config_asset_name": c_asset,
                        "comp_class": comp_class,
                        "go_rel_path": go_rel_path,
                        "occ_index": occ_index,
                        "field": field_name,
                        "value": normalize_component_json_value(comp_class, field_name, checked),
                    }
                )

    world_changes: list[dict[str, Any]] = []
    if world_overrides:
        for wkey in sorted(world_overrides.keys()):
            _, comp_class, go_name, occ_index = wkey
            witem = vanilla_bundle.world_by_key.get(wkey)
            field_map = world_overrides[wkey]
            for field_name in sorted(field_map.keys()):
                val = field_map[field_name]
                vanilla_val = witem.fields[field_name].value if witem else None
                checked = validate_component_field_value(
                    comp_class, field_name, val, vanilla_value=vanilla_val
                )
                if vanilla_val is not None and component_values_equal(
                    comp_class, field_name, checked, vanilla_val
                ):
                    continue
                world_changes.append(
                    {
                        "comp_class": comp_class,
                        "go_name": go_name,
                        "occ_index": occ_index,
                        "field": field_name,
                        "value": normalize_component_json_value(comp_class, field_name, checked),
                    }
                )

    payload = {
        "schema_version": PRESET_SCHEMA_VERSION,
        "name": name,
        "description": description,
        "target_game_version": target_game_version,
        "changes": changes,
        "component_changes": component_changes,
        "world_changes": world_changes,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def count_targets_by_affiliation(
    vanilla_bundle: ParsedAssetsBundle,
    target_keys: Iterable[ConfigKey],
) -> dict[str, int]:
    """统计指定目标键集合中 我方 / 敌方 / 中立 及细分子分类的数量，用于批量防误触明细。"""
    counts: dict[str, int] = {
        "total": 0,
        "player": 0,
        "enemy": 0,
        "neutral": 0,
        "player_empire": 0,
        "player_merc": 0,
        "enemy_mutants": 0,
        "enemy_rebels": 0,
        "enemy_robots": 0,
    }
    for key in target_keys:
        item = vanilla_bundle.by_key.get(key)
        if item is None:
            continue
        counts["total"] += 1
        aff = item.affiliation
        if aff in counts:
            counts[aff] += 1
        if aff in PLAYER_AFFILIATIONS:
            counts["player"] += 1
        elif aff in ENEMY_AFFILIATIONS:
            counts["enemy"] += 1
        else:
            counts["neutral"] += 1
    return counts


def _set_override_value(
    overrides: OverridesMap,
    vanilla_bundle: ParsedAssetsBundle,
    key: ConfigKey,
    field_name: str,
    new_val: int | float,
) -> bool:
    """设置单条配置修改（若与原版相同则移除），返回有效值是否相比修改前发生变化。"""
    item = vanilla_bundle.by_key[key]
    vanilla_val = item.fields[field_name].value
    old_effective = overrides.get(key, {}).get(field_name, vanilla_val)
    changed = not values_equal(field_name, new_val, old_effective)

    if values_equal(field_name, new_val, vanilla_val):
        if key in overrides and field_name in overrides[key]:
            del overrides[key][field_name]
            if not overrides[key]:
                del overrides[key]
    else:
        overrides.setdefault(key, {})[field_name] = normalize_json_value(field_name, new_val)
    return changed


def _set_component_override_value(
    comp_overrides: ComponentOverridesMap,
    vanilla_bundle: ParsedAssetsBundle,
    ckey: ComponentKey,
    field_name: str,
    new_val: int | float,
) -> bool:
    """设置单条组件修改（若与原版相同则移除），返回有效值是否相比修改前发生变化。"""
    comp = vanilla_bundle.components_by_key[ckey]
    vanilla_val = comp.fields[field_name].value
    old_effective = comp_overrides.get(ckey, {}).get(field_name, vanilla_val)
    changed = not component_values_equal(comp.comp_class, field_name, new_val, old_effective)

    if component_values_equal(comp.comp_class, field_name, new_val, vanilla_val):
        if ckey in comp_overrides and field_name in comp_overrides[ckey]:
            del comp_overrides[ckey][field_name]
            if not comp_overrides[ckey]:
                del comp_overrides[ckey]
    else:
        comp_overrides.setdefault(ckey, {})[field_name] = normalize_component_json_value(
            comp.comp_class, field_name, new_val
        )
    return changed


def _set_world_override_value(
    world_overrides: WorldOverridesMap,
    vanilla_bundle: ParsedAssetsBundle,
    wkey: WorldKey,
    field_name: str,
    new_val: int | float,
) -> bool:
    """设置单条地图资源点修改（若与原版相同则移除），返回有效值是否发生变化。"""
    witem = vanilla_bundle.world_by_key[wkey]
    vanilla_val = witem.fields[field_name].value
    old_effective = world_overrides.get(wkey, {}).get(field_name, vanilla_val)
    changed = not component_values_equal(witem.comp_class, field_name, new_val, old_effective)

    if component_values_equal(witem.comp_class, field_name, new_val, vanilla_val):
        if wkey in world_overrides and field_name in world_overrides[wkey]:
            del world_overrides[wkey][field_name]
            if not world_overrides[wkey]:
                del world_overrides[wkey]
    else:
        world_overrides.setdefault(wkey, {})[field_name] = normalize_component_json_value(
            witem.comp_class, field_name, new_val
        )
    return changed


def apply_batch_time_factor(
    vanilla_bundle: ParsedAssetsBundle,
    current_overrides: Mapping[ConfigKey, Mapping[str, int | float]],
    target_keys: Iterable[ConfigKey],
    factor: float = 0.5,
) -> tuple[OverridesMap, int]:
    """基于原版时间字段应用双向倍率（建造/研发 timeCreation 或战术支援 coolDown）。"""
    new_overrides = clone_overrides(current_overrides)
    changed_count = 0
    for key in target_keys:
        item = vanilla_bundle.by_key.get(key)
        if item is None:
            continue
        fname = "coolDown" if item.script == "TacticalAbilityConfig" else "timeCreation"
        base = float(item.fields[fname].value)
        if base <= 0.0:
            continue
        min_v = MIN_NONZERO_BUILD_TIME if fname == "timeCreation" else 0.1
        target_val = min(MAX_FLOAT_VALUE, max(min_v, round(base * factor, 1)))
        if _set_override_value(new_overrides, vanilla_bundle, key, fname, target_val):
            changed_count += 1
    return new_overrides, changed_count


def apply_batch_int_cost_factor(
    vanilla_bundle: ParsedAssetsBundle,
    current_overrides: Mapping[ConfigKey, Mapping[str, int | float]],
    target_keys: Iterable[ConfigKey],
    field_name: str,
    factor: float = 0.5,
) -> tuple[OverridesMap, int]:
    """基于原版整数消耗字段（minerals / gears）应用倍率，最低保留 1。"""
    if field_name not in ("minerals", "gears"):
        raise ValueError(f"不支持批量整数消耗倍率字段: {field_name}")
    new_overrides = clone_overrides(current_overrides)
    changed_count = 0
    for key in target_keys:
        item = vanilla_bundle.by_key.get(key)
        if item is None or field_name not in item.fields:
            continue
        base = int(item.fields[field_name].value)
        if base <= 0:
            continue
        target_val = min(MAX_INT_VALUE, max(1, round(base * factor)))
        if _set_override_value(new_overrides, vanilla_bundle, key, field_name, target_val):
            changed_count += 1
    return new_overrides, changed_count


def apply_batch_population_factor(
    vanilla_bundle: ParsedAssetsBundle,
    current_overrides: Mapping[ConfigKey, Mapping[str, int | float]],
    target_keys: Iterable[ConfigKey],
    factor: float,
) -> tuple[OverridesMap, int]:
    """基于原版 limitProduce > 0 的条目应用人口上限倍率。"""
    new_overrides = clone_overrides(current_overrides)
    changed_count = 0
    for key in target_keys:
        item = vanilla_bundle.by_key.get(key)
        if item is None or "limitProduce" not in item.fields:
            continue
        base = int(item.fields["limitProduce"].value)
        if base <= 0:
            continue
        target_val = min(MAX_INT_VALUE, max(1, round(base * factor)))
        if _set_override_value(new_overrides, vanilla_bundle, key, "limitProduce", target_val):
            changed_count += 1
    return new_overrides, changed_count


def apply_batch_unlock_max_count(
    vanilla_bundle: ParsedAssetsBundle,
    current_overrides: Mapping[ConfigKey, Mapping[str, int | float]],
    target_keys: Iterable[ConfigKey],
) -> tuple[OverridesMap, int]:
    """将筛选范围内有数量限制（maxCount > 0）的对象改为 0（不限）。"""
    new_overrides = clone_overrides(current_overrides)
    changed_count = 0
    for key in target_keys:
        item = vanilla_bundle.by_key.get(key)
        if item is None or "maxCount" not in item.fields:
            continue
        base = int(item.fields["maxCount"].value)
        cur = int(new_overrides.get(key, {}).get("maxCount", base))
        if base == 0 and cur == 0:
            continue
        if _set_override_value(new_overrides, vanilla_bundle, key, "maxCount", 0):
            changed_count += 1
    return new_overrides, changed_count


def apply_batch_hp_factor(
    vanilla_bundle: ParsedAssetsBundle,
    current_component_overrides: Mapping[ComponentKey, Mapping[str, int | float]],
    target_config_keys: Iterable[ConfigKey],
    factor: float,
) -> tuple[ComponentOverridesMap, int]:
    """基于原版 HP.maxHp > 0 应用双向血量倍率（补丁时自动联动 curHp）。"""
    target_set = set(target_config_keys)
    new_comp = clone_component_overrides(current_component_overrides)
    changed_count = 0
    for ckey, comp in vanilla_bundle.components_by_key.items():
        if comp.comp_class != "HP":
            continue
        if (comp.config_script, comp.config_asset_name) not in target_set:
            continue
        base = int(comp.fields["maxHp"].value)
        if base <= 0:
            continue
        target_val = min(MAX_INT_VALUE, max(1, round(base * factor)))
        if _set_component_override_value(new_comp, vanilla_bundle, ckey, "maxHp", target_val):
            changed_count += 1
    return new_comp, changed_count


def apply_batch_weapon_damage_factor(
    vanilla_bundle: ParsedAssetsBundle,
    current_component_overrides: Mapping[ComponentKey, Mapping[str, int | float]],
    target_config_keys: Iterable[ConfigKey],
    factor: float,
) -> tuple[ComponentOverridesMap, int]:
    """基于原版全部 AttackComponent 4 项伤害 (>0) 应用双向倍率。"""
    target_set = set(target_config_keys)
    new_comp = clone_component_overrides(current_component_overrides)
    changed_count = 0
    for ckey, comp in vanilla_bundle.components_by_key.items():
        if comp.comp_class not in ATTACK_COMPONENT_CLASSES:
            continue
        if (comp.config_script, comp.config_asset_name) not in target_set:
            continue
        comp_changed = False
        for dmg_field in ATTACK_DAMAGE_FIELDS:
            base = int(comp.fields[dmg_field].value)
            if base <= 0:
                continue
            target_val = min(MAX_INT_VALUE, max(1, round(base * factor)))
            if _set_component_override_value(new_comp, vanilla_bundle, ckey, dmg_field, target_val):
                comp_changed = True
        if comp_changed:
            changed_count += 1
    return new_comp, changed_count


def apply_batch_weapon_cooldown_factor(
    vanilla_bundle: ParsedAssetsBundle,
    current_component_overrides: Mapping[ComponentKey, Mapping[str, int | float]],
    target_config_keys: Iterable[ConfigKey],
    factor: float,
) -> tuple[ComponentOverridesMap, int]:
    """基于原版 AttackComponent.coolDownShot > 0 应用倍率（下限 0.05s，上限 60s）。"""
    target_set = set(target_config_keys)
    new_comp = clone_component_overrides(current_component_overrides)
    changed_count = 0
    for ckey, comp in vanilla_bundle.components_by_key.items():
        if comp.comp_class not in ATTACK_COMPONENT_CLASSES:
            continue
        if (comp.config_script, comp.config_asset_name) not in target_set:
            continue
        base = float(comp.fields["coolDownShot"].value)
        if base <= 0.0:
            continue
        target_val = min(60.0, max(0.05, round(base * factor, 3)))
        if _set_component_override_value(new_comp, vanilla_bundle, ckey, "coolDownShot", target_val):
            changed_count += 1
    return new_comp, changed_count


def apply_batch_move_speed_factor(
    vanilla_bundle: ParsedAssetsBundle,
    current_component_overrides: Mapping[ComponentKey, Mapping[str, int | float]],
    target_config_keys: Iterable[ConfigKey],
    factor: float,
) -> tuple[ComponentOverridesMap, int]:
    """基于原版 MovePattern.clearSpeed 应用双向移速倍率（限制在 [0.1, 100.0]）。"""
    target_set = set(target_config_keys)
    new_comp = clone_component_overrides(current_component_overrides)
    changed_count = 0
    for ckey, comp in vanilla_bundle.components_by_key.items():
        if comp.comp_class not in MOVE_COMPONENT_CLASSES:
            continue
        if (comp.config_script, comp.config_asset_name) not in target_set:
            continue
        base = float(comp.fields["clearSpeed"].value)
        if base <= 0.0:
            continue
        target_val = min(100.0, max(0.1, round(base * factor, 2)))
        if _set_component_override_value(new_comp, vanilla_bundle, ckey, "clearSpeed", target_val):
            changed_count += 1
    return new_comp, changed_count


def sync_weapon_overrides_to_unit(
    vanilla_bundle: ParsedAssetsBundle,
    current_component_overrides: Mapping[ComponentKey, Mapping[str, int | float]],
    source_comp_key: ComponentKey,
) -> tuple[ComponentOverridesMap, int]:
    """将源武器当前已调整的参数值同步到同一单位下其余全部 AutoAttack_* 武器。"""
    src_comp = vanilla_bundle.components_by_key.get(source_comp_key)
    if src_comp is None or src_comp.comp_class not in ATTACK_COMPONENT_CLASSES:
        return clone_component_overrides(current_component_overrides), 0

    new_comp = clone_component_overrides(current_component_overrides)
    src_ov = new_comp.get(source_comp_key, {})
    sibling_keys = [
        c.key
        for c in vanilla_bundle.by_key[(src_comp.config_script, src_comp.config_asset_name)].components
        if c.comp_class in ATTACK_COMPONENT_CLASSES and c.key != source_comp_key
    ]
    changed_weapons = 0
    for sib_key in sibling_keys:
        sib_comp = vanilla_bundle.components_by_key[sib_key]
        sib_changed = False
        for fname, floc in sib_comp.fields.items():
            # 取源武器的有效值，然后结合目标武器的原版值做合法性校验（防止 coolDownShot=0 等边界错误）
            src_effective = src_ov.get(fname, src_comp.fields[fname].value)
            try:
                checked = validate_component_field_value(
                    sib_comp.comp_class, fname, src_effective, vanilla_value=floc.value
                )
            except ValidationError:
                continue
            if _set_component_override_value(new_comp, vanilla_bundle, sib_key, fname, checked):
                sib_changed = True
        if sib_changed:
            changed_weapons += 1
    return new_comp, changed_weapons


def apply_batch_all_minerals_value(
    vanilla_bundle: ParsedAssetsBundle,
    current_world_overrides: Mapping[WorldKey, Mapping[str, int | float]],
    new_minerals_value: int,
) -> tuple[WorldOverridesMap, int]:
    """一键将全部 7 个标准 Mineral 矿脉储量设为指定整数。"""
    checked = int(validate_component_field_value("Mineral", "minerals", new_minerals_value))
    new_world = clone_world_overrides(current_world_overrides)
    changed = 0
    for wkey, witem in vanilla_bundle.world_by_key.items():
        if witem.comp_class != "Mineral":
            continue
        if _set_world_override_value(new_world, vanilla_bundle, wkey, "minerals", checked):
            changed += 1
    return new_world, changed


def reset_keys_to_vanilla(
    current_overrides: Mapping[ConfigKey, Mapping[str, int | float]],
    target_keys: Iterable[ConfigKey],
) -> tuple[OverridesMap, int]:
    """将指定配置对象的配置层修改重置回原版值（V1 兼容接口）。"""
    new_overrides = clone_overrides(current_overrides)
    reset_count = 0
    for key in target_keys:
        if key in new_overrides:
            del new_overrides[key]
            reset_count += 1
    return new_overrides, reset_count


def reset_config_and_component_keys_to_vanilla(
    current_overrides: Mapping[ConfigKey, Mapping[str, int | float]],
    current_comp_overrides: Mapping[ComponentKey, Mapping[str, int | float]],
    target_keys: Iterable[ConfigKey],
) -> tuple[OverridesMap, ComponentOverridesMap, int]:
    """将指定配置对象及其全部挂载组件修改同步重置回原版值。"""
    target_set = set(target_keys)
    new_ov = clone_overrides(current_overrides)
    new_comp = clone_component_overrides(current_comp_overrides)
    touched_configs: set[ConfigKey] = set()

    for key in target_set:
        if key in new_ov:
            del new_ov[key]
            touched_configs.add(key)

    for ckey in list(new_comp.keys()):
        cfg_key = (ckey[0], ckey[1])
        if cfg_key in target_set:
            del new_comp[ckey]
            touched_configs.add(cfg_key)

    return new_ov, new_comp, len(touched_configs)


def reset_world_keys_to_vanilla(
    current_world_overrides: Mapping[WorldKey, Mapping[str, int | float]],
    target_world_keys: Iterable[WorldKey],
) -> tuple[WorldOverridesMap, int]:
    """将指定地图资源点的修改重置回原版值。"""
    new_world = clone_world_overrides(current_world_overrides)
    reset_count = 0
    for wkey in target_world_keys:
        if wkey in new_world:
            del new_world[wkey]
            reset_count += 1
    return new_world, reset_count
