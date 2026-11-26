"""游戏目录诊断、安全原版备份、跨版本防覆写保护、进程检测与原子替换。"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .preset_manager import (
    ComponentOverridesMap,
    OverridesMap,
    WorldOverridesMap,
    compute_all_diffs_from_bundles,
)
from .unity_assets import (
    AssetFormatError,
    ComponentKey,
    KNOWN_LIMITED_MOD_1022_SHA256,
    KNOWN_VANILLA_D351_SHA256,
    ParsedAssetsBundle,
    WorldKey,
    compute_sha256_bytes,
    compute_sha256_file,
    parse_serialized_file_meta,
    parse_sharedassets_configs,
    patch_sharedassets_bytes,
    reconstruct_vanilla_from_limited_mod,
)

BACKUP_FILENAME = "sharedassets0.assets.vanilla_backup"
META_FILENAME = "vanilla_backup.meta.json"
GAME_PROCESS_NAMES: tuple[str, ...] = (
    "Dust Front RTS.exe",
    "Dust Front RTS 单机启动器.exe",
)
LAUNCHER_EXE_NAME = "Dust Front RTS 单机启动器.exe"


class ProcessRunningError(RuntimeError):
    """游戏或单机启动器正在运行，禁止修改游戏资产文件。"""


class ExternalUpdateDetectedError(RuntimeError):
    """检测到游戏文件被外部更新或替换，已拦截旧备份覆盖以防损坏新版游戏。"""


class BaselineConfirmationRequiredError(RuntimeError):
    """当前文件 SHA-256 未知且无备份，需用户明确确认后才可创建原版基准。"""


@dataclass(frozen=True)
class GameDataStatus:
    code: str
    label: str
    detail: str
    game_sha256: str | None
    backup_exists: bool
    backup_sha256: str | None
    meta: dict[str, Any] | None
    can_write_directly: bool


@dataclass(frozen=True)
class WorkspaceSnapshot:
    status: GameDataStatus
    vanilla_bundle: ParsedAssetsBundle
    current_bundle: ParsedAssetsBundle
    initial_overrides: OverridesMap
    reconstructed_in_memory: bool
    initial_component_overrides: ComponentOverridesMap = field(default_factory=dict)
    initial_world_overrides: WorldOverridesMap = field(default_factory=dict)


def detect_default_game_data_dir(workspace_dir: str | Path) -> Path:
    """默认定位 MOD 工作区上一级目录中的 Dust Front RTS_Data。"""
    ws = Path(workspace_dir).resolve()
    candidate = ws.parent / "Dust Front RTS_Data"
    return candidate


def validate_game_data_dir(data_dir: str | Path) -> tuple[bool, str]:
    """校验目录是否包含所需的 sharedassets0.assets 与 globalgamemanagers.assets。"""
    d = Path(data_dir)
    if not d.is_dir():
        return False, f"游戏数据目录不存在: {d}"
    shared = d / "sharedassets0.assets"
    ggm = d / "globalgamemanagers.assets"
    if not shared.is_file():
        return False, f"目录中缺少 sharedassets0.assets: {d}"
    if not ggm.is_file():
        return False, f"目录中缺少 globalgamemanagers.assets: {d}"
    return True, "目录有效"


def _read_meta(meta_path: Path) -> dict[str, Any] | None:
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_meta(meta_path: Path, meta: Mapping[str, Any]) -> None:
    meta_path.write_text(
        json.dumps(dict(meta), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _decode_tasklist_output(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("mbcs", "replace")


def find_running_game_processes(
    tasklist_runner: Callable[[], bytes | str] | None = None,
) -> list[str]:
    """检测 Dust Front RTS.exe 或 Dust Front RTS 单机启动器.exe 是否正在运行。"""
    if tasklist_runner is None:
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = _decode_tasklist_output(proc.stdout)
    else:
        text = _decode_tasklist_output(tasklist_runner())

    target_by_lower = {name.lower(): name for name in GAME_PROCESS_NAMES}
    found: list[str] = []
    seen: set[str] = set()
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row:
            continue
        img_lower = row[0].strip().lower()
        if img_lower in target_by_lower and img_lower not in seen:
            seen.add(img_lower)
            found.append(target_by_lower[img_lower])
    return found


def inspect_game_status(
    data_dir: str | Path,
    *,
    custom_diff_count: int = 0,
) -> GameDataStatus:
    """诊断游戏目录 sharedassets0.assets 与原版备份状态。"""
    d = Path(data_dir)
    ok, msg = validate_game_data_dir(d)
    if not ok:
        return GameDataStatus(
            code="invalid_dir",
            label="🔴 游戏目录无效",
            detail=msg,
            game_sha256=None,
            backup_exists=False,
            backup_sha256=None,
            meta=None,
            can_write_directly=False,
        )

    shared_path = d / "sharedassets0.assets"
    backup_path = d / BACKUP_FILENAME
    meta_path = d / META_FILENAME

    game_sha = compute_sha256_file(shared_path)
    backup_exists = backup_path.is_file()
    meta = _read_meta(meta_path)

    if backup_exists:
        backup_sha = compute_sha256_file(backup_path)
        meta_vanilla_sha = meta.get("vanilla_sha256") if meta else None
        if meta_vanilla_sha and meta_vanilla_sha != backup_sha:
            return GameDataStatus(
                code="external_update_conflict",
                label="🟡 原版备份元数据不一致（需重建基准）",
                detail=(
                    f"备份文件 SHA-256 ({backup_sha[:12]}...) 与元数据记录 "
                    f"({meta_vanilla_sha[:12]}...) 不符，请归档旧备份并重建基准。"
                ),
                game_sha256=game_sha,
                backup_exists=True,
                backup_sha256=backup_sha,
                meta=meta,
                can_write_directly=False,
            )

        last_applied = meta.get("last_applied_sha256") if meta else None
        known_consistent = {backup_sha}
        if backup_sha == KNOWN_VANILLA_D351_SHA256:
            known_consistent.add(KNOWN_LIMITED_MOD_1022_SHA256)
        if last_applied:
            known_consistent.add(last_applied)

        if game_sha not in known_consistent:
            return GameDataStatus(
                code="external_update_conflict",
                label="🟡 检测到游戏更新或外部修改（已拦截旧备份覆盖）",
                detail=(
                    f"当前 sharedassets0.assets ({game_sha[:12]}...) 与既有原版备份 "
                    f"({backup_sha[:12]}...) 及工具上次产物均不一致；可能游戏已更新。"
                    "请点击「归档旧备份并重建基准」后再修改。"
                ),
                game_sha256=game_sha,
                backup_exists=True,
                backup_sha256=backup_sha,
                meta=meta,
                can_write_directly=False,
            )

        if game_sha == KNOWN_LIMITED_MOD_1022_SHA256:
            return GameDataStatus(
                code="limited_mod_1022",
                label="🔵 已启用：有限修改MOD (10月22日原版)",
                detail=f"原版备份已就绪 ({backup_sha[:12]}...)，当前文件匹配 10/22 有限修改MOD",
                game_sha256=game_sha,
                backup_exists=True,
                backup_sha256=backup_sha,
                meta=meta,
                can_write_directly=True,
            )

        if game_sha == backup_sha:
            if game_sha == KNOWN_VANILLA_D351_SHA256:
                return GameDataStatus(
                    code="verified_vanilla_d351",
                    label="🟢 已验证原版 (D-35-1)",
                    detail=f"原版备份就绪，SHA-256 匹配 D-35-1 ({game_sha[:12]}...)",
                    game_sha256=game_sha,
                    backup_exists=True,
                    backup_sha256=backup_sha,
                    meta=meta,
                    can_write_directly=True,
                )
            return GameDataStatus(
                code="verified_custom_baseline",
                label="🟢 已还原为当前版本原版基准",
                detail=f"与既有基准备份一致 ({game_sha[:12]}...)",
                game_sha256=game_sha,
                backup_exists=True,
                backup_sha256=backup_sha,
                meta=meta,
                can_write_directly=True,
            )

        return GameDataStatus(
            code="custom_mod",
            label=f"🟣 已启用：自定义修改 (共 {custom_diff_count} 项改动)",
            detail=f"基于原版备份 ({backup_sha[:12]}...) 通过本工具应用",
            game_sha256=game_sha,
            backup_exists=True,
            backup_sha256=backup_sha,
            meta=meta,
            can_write_directly=True,
        )

    # 尚无 vanilla_backup
    if game_sha == KNOWN_VANILLA_D351_SHA256:
        return GameDataStatus(
            code="verified_vanilla_d351",
            label="🟢 已验证原版 (D-35-1)",
            detail="首次写入时将自动备份干净的 D-35-1 原版文件",
            game_sha256=game_sha,
            backup_exists=False,
            backup_sha256=None,
            meta=None,
            can_write_directly=True,
        )

    if game_sha == KNOWN_LIMITED_MOD_1022_SHA256:
        return GameDataStatus(
            code="limited_mod_1022",
            label="🔵 已启用：有限修改MOD (10月22日原版)",
            detail="首次写入或还原时将自动回填 10 项原版数值以重建 D-35-1 干净备份",
            game_sha256=game_sha,
            backup_exists=False,
            backup_sha256=None,
            meta=None,
            can_write_directly=True,
        )

    return GameDataStatus(
        code="unknown_baseline",
        label="🟡 未知版本/外部修改基准（需确认）",
        detail=(
            f"当前 sharedassets0.assets ({game_sha[:12]}...) 不在已登记指纹中，"
            "首次写入前需由您确认其为干净原版。"
        ),
        game_sha256=game_sha,
        backup_exists=False,
        backup_sha256=None,
        meta=None,
        can_write_directly=False,
    )


def load_workspace_snapshot(data_dir: str | Path) -> WorkspaceSnapshot:
    """以只读方式加载游戏资产与当前激活的改动（启动期零磁盘写入）。"""
    d = Path(data_dir)
    ok, msg = validate_game_data_dir(d)
    if not ok:
        raise FileNotFoundError(msg)

    status = inspect_game_status(d)
    shared_path = d / "sharedassets0.assets"
    ggm_path = d / "globalgamemanagers.assets"
    res_path = d / "resources.assets"
    backup_path = d / BACKUP_FILENAME

    current_bytes = shared_path.read_bytes()
    current_bundle = parse_sharedassets_configs(
        current_bytes,
        ggm_path,
        res_path if res_path.is_file() else None,
    )

    reconstructed_in_memory = False
    if backup_path.is_file() and status.code != "external_update_conflict":
        vanilla_bytes = backup_path.read_bytes()
        vanilla_bundle = parse_sharedassets_configs(
            vanilla_bytes,
            ggm_path,
            res_path if res_path.is_file() else None,
        )
        initial_overrides, initial_comp_overrides, initial_world_overrides = (
            compute_all_diffs_from_bundles(vanilla_bundle, current_bundle)
        )
    elif status.code == "limited_mod_1022":
        vanilla_bytes = bytes(reconstruct_vanilla_from_limited_mod(current_bytes, ggm_path))
        vanilla_bundle = parse_sharedassets_configs(
            vanilla_bytes,
            ggm_path,
            res_path if res_path.is_file() else None,
        )
        initial_overrides, initial_comp_overrides, initial_world_overrides = (
            compute_all_diffs_from_bundles(vanilla_bundle, current_bundle)
        )
        reconstructed_in_memory = True
    else:
        vanilla_bundle = current_bundle
        initial_overrides = {}
        initial_comp_overrides = {}
        initial_world_overrides = {}

    diff_count = (
        sum(len(fields) for fields in initial_overrides.values())
        + sum(len(fields) for fields in initial_comp_overrides.values())
        + sum(len(fields) for fields in initial_world_overrides.values())
    )
    final_status = inspect_game_status(d, custom_diff_count=diff_count)
    return WorkspaceSnapshot(
        status=final_status,
        vanilla_bundle=vanilla_bundle,
        current_bundle=current_bundle,
        initial_overrides=initial_overrides,
        reconstructed_in_memory=reconstructed_in_memory,
        initial_component_overrides=initial_comp_overrides,
        initial_world_overrides=initial_world_overrides,
    )


def atomic_write_bytes(
    target_path: Path,
    payload: bytes | bytearray,
    *,
    expected_size: int | None = None,
    validate_unity_v22: bool = True,
    replace_fn: Callable[[Path, Path], None] = os.replace,
) -> None:
    """将字节先写同目录 .tmp 文件校验无误后原子替换，失败时始终清理 .tmp。"""
    if expected_size is not None and len(payload) != expected_size:
        raise AssetFormatError(
            f"写入前长度校验失败: got={len(payload)}, expected={expected_size}"
        )
    if validate_unity_v22:
        parse_serialized_file_meta(payload)

    tmp_path = target_path.parent / f"{target_path.name}.{os.getpid()}.tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if expected_size is not None and tmp_path.stat().st_size != expected_size:
            raise OSError("临时文件写入后尺寸不匹配")
        replace_fn(tmp_path, target_path)
    except PermissionError as exc:
        raise PermissionError(
            f"无法覆盖 {target_path.name}（可能被游戏进程、只读属性或杀毒软件占用）: {exc}"
        ) from exc
    except OSError as exc:
        raise OSError(f"写入 {target_path.name} 失败: {exc}") from exc
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def ensure_vanilla_backup(
    data_dir: str | Path,
    *,
    allow_unknown_baseline: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """确保 Dust Front RTS_Data 存在与当前游戏版本匹配的干净原版备份。"""
    d = Path(data_dir)
    status = inspect_game_status(d)
    if status.code == "invalid_dir":
        raise FileNotFoundError(status.detail)
    if status.code == "external_update_conflict":
        raise ExternalUpdateDetectedError(status.detail)

    backup_path = d / BACKUP_FILENAME
    meta_path = d / META_FILENAME
    shared_path = d / "sharedassets0.assets"
    ggm_path = d / "globalgamemanagers.assets"

    if backup_path.is_file():
        backup_bytes = backup_path.read_bytes()
        bundle = parse_sharedassets_configs(backup_bytes, ggm_path, None)
        backup_sha = compute_sha256_bytes(backup_bytes)
        meta = status.meta or {
            "schema_version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "unity_version": bundle.unity_version,
            "file_size": bundle.file_size,
            "object_count": bundle.object_count,
            "vanilla_sha256": backup_sha,
            "last_applied_sha256": status.game_sha256,
        }
        if not meta_path.is_file():
            _write_meta(meta_path, meta)
        return backup_path, meta

    game_bytes = shared_path.read_bytes()
    game_sha = compute_sha256_bytes(game_bytes)

    if game_sha == KNOWN_VANILLA_D351_SHA256:
        vanilla_bytes = game_bytes
    elif game_sha == KNOWN_LIMITED_MOD_1022_SHA256:
        vanilla_bytes = bytes(reconstruct_vanilla_from_limited_mod(game_bytes, ggm_path))
    else:
        if not allow_unknown_baseline:
            raise BaselineConfirmationRequiredError(
                f"当前 sharedassets0.assets 指纹 ({game_sha[:12]}...) 不在已知 D-35-1 / 10-22 MOD 列表中，"
                "请先确认当前游戏文件确为干净原版再建立备份。"
            )
        vanilla_bytes = game_bytes

    bundle = parse_sharedassets_configs(vanilla_bytes, ggm_path, None)
    vanilla_sha = compute_sha256_bytes(vanilla_bytes)
    atomic_write_bytes(
        backup_path,
        vanilla_bytes,
        expected_size=len(vanilla_bytes),
        validate_unity_v22=True,
    )
    meta = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "unity_version": bundle.unity_version,
        "file_size": bundle.file_size,
        "object_count": bundle.object_count,
        "vanilla_sha256": vanilla_sha,
        "last_applied_sha256": game_sha,
    }
    _write_meta(meta_path, meta)
    return backup_path, meta


def _unique_archive_path(directory: Path, base_name: str, stamp: str) -> Path:
    candidate = directory / f"{base_name}.{stamp}.old"
    idx = 1
    while candidate.exists():
        candidate = directory / f"{base_name}.{stamp}_{idx}.old"
        idx += 1
    return candidate


def archive_old_backup_and_rebuild(
    data_dir: str | Path,
    *,
    allow_unknown_baseline: bool = True,
) -> tuple[list[Path], Path, dict[str, Any]]:
    """归档旧版 vanilla_backup 与元数据为 .old 文件，并基于当前新版重建基准。"""
    d = Path(data_dir)
    ok, msg = validate_game_data_dir(d)
    if not ok:
        raise FileNotFoundError(msg)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived: list[Path] = []
    backup_path = d / BACKUP_FILENAME
    meta_path = d / META_FILENAME

    if backup_path.is_file():
        dst_bak = _unique_archive_path(d, BACKUP_FILENAME, stamp)
        backup_path.rename(dst_bak)
        archived.append(dst_bak)

    if meta_path.is_file():
        dst_meta = _unique_archive_path(d, META_FILENAME, stamp)
        meta_path.rename(dst_meta)
        archived.append(dst_meta)

    new_backup, new_meta = ensure_vanilla_backup(
        d, allow_unknown_baseline=allow_unknown_baseline
    )
    return archived, new_backup, new_meta


def apply_overrides_to_game(
    data_dir: str | Path,
    overrides: Mapping[tuple[str, str], Mapping[str, int | float]],
    *,
    component_overrides: Mapping[ComponentKey, Mapping[str, int | float]] | None = None,
    world_overrides: Mapping[WorldKey, Mapping[str, int | float]] | None = None,
    allow_unknown_baseline: bool = False,
    tasklist_runner: Callable[[], bytes | str] | None = None,
    replace_fn: Callable[[Path, Path], None] = os.replace,
) -> tuple[str, int]:
    """检测进程与版本后，从干净原版备份原地打三层补丁并原子写回游戏目录。"""
    running = find_running_game_processes(tasklist_runner)
    if running:
        raise ProcessRunningError(
            f"检测到游戏相关进程正在运行: {', '.join(running)}。请先关闭游戏及启动器后再应用修改。"
        )

    d = Path(data_dir)
    backup_path, meta = ensure_vanilla_backup(
        d, allow_unknown_baseline=allow_unknown_baseline
    )
    ggm_path = d / "globalgamemanagers.assets"
    shared_path = d / "sharedassets0.assets"

    vanilla_bytes = backup_path.read_bytes()
    vanilla_bundle = parse_sharedassets_configs(vanilla_bytes, ggm_path, None)
    patched_bytes, patched_count = patch_sharedassets_bytes(
        vanilla_bytes,
        vanilla_bundle,
        overrides,
        component_overrides=component_overrides,
        world_overrides=world_overrides,
    )
    new_sha = compute_sha256_bytes(patched_bytes)

    atomic_write_bytes(
        shared_path,
        patched_bytes,
        expected_size=len(vanilla_bytes),
        validate_unity_v22=True,
        replace_fn=replace_fn,
    )
    meta = dict(meta)
    meta["last_applied_sha256"] = new_sha
    meta["last_applied_at"] = datetime.now().isoformat(timespec="seconds")
    _write_meta(d / META_FILENAME, meta)
    return new_sha, patched_count


def restore_vanilla_to_game(
    data_dir: str | Path,
    *,
    tasklist_runner: Callable[[], bytes | str] | None = None,
    replace_fn: Callable[[Path, Path], None] = os.replace,
) -> str:
    """校验安全后，将干净的 vanilla_backup 原子还原回 Dust Front RTS_Data\\sharedassets0.assets。"""
    running = find_running_game_processes(tasklist_runner)
    if running:
        raise ProcessRunningError(
            f"检测到游戏相关进程正在运行: {', '.join(running)}。请先关闭游戏及启动器后再还原。"
        )

    d = Path(data_dir)
    status = inspect_game_status(d)
    if status.code == "invalid_dir":
        raise FileNotFoundError(status.detail)
    if status.code == "external_update_conflict":
        raise ExternalUpdateDetectedError(status.detail)

    backup_path = d / BACKUP_FILENAME
    if not backup_path.is_file():
        if status.code in ("verified_vanilla_d351", "limited_mod_1022"):
            backup_path, meta = ensure_vanilla_backup(d)
        else:
            raise FileNotFoundError(
                f"未找到原版备份文件 {BACKUP_FILENAME}，无法盲目还原未知版本文件。"
            )
    else:
        meta = dict(status.meta or {})

    ggm_path = d / "globalgamemanagers.assets"
    shared_path = d / "sharedassets0.assets"
    vanilla_bytes = backup_path.read_bytes()
    vanilla_sha = compute_sha256_bytes(vanilla_bytes)
    if meta.get("vanilla_sha256") and meta["vanilla_sha256"] != vanilla_sha:
        raise ExternalUpdateDetectedError("备份文件 SHA-256 与元数据不符，已中止还原。")
    bundle = parse_sharedassets_configs(vanilla_bytes, ggm_path, None)

    atomic_write_bytes(
        shared_path,
        vanilla_bytes,
        expected_size=len(vanilla_bytes),
        validate_unity_v22=True,
        replace_fn=replace_fn,
    )
    meta.setdefault("schema_version", 1)
    meta["unity_version"] = bundle.unity_version
    meta["file_size"] = bundle.file_size
    meta["object_count"] = bundle.object_count
    meta["vanilla_sha256"] = vanilla_sha
    meta["last_applied_sha256"] = vanilla_sha
    meta["last_applied_at"] = datetime.now().isoformat(timespec="seconds")
    _write_meta(d / META_FILENAME, meta)
    return vanilla_sha


def launch_game_launcher(data_dir: str | Path) -> subprocess.Popen[Any]:
    """显式设置游戏根目录为 cwd 并拉起 Dust Front RTS 单机启动器.exe。"""
    game_root = Path(data_dir).resolve().parent
    launcher = game_root / LAUNCHER_EXE_NAME
    if not launcher.is_file():
        raise FileNotFoundError(f"未在游戏根目录找到启动器: {launcher}")
    return subprocess.Popen([str(launcher)], cwd=str(game_root))
