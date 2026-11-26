"""自动化验收测试（V1 7 项黄金回归 + V2 7 项分类与组件专项验收）。"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import tkinter as tk
import unittest
from collections import Counter
from pathlib import Path

from mod_configurator.backup_manager import (
    BACKUP_FILENAME,
    BaselineConfirmationRequiredError,
    ExternalUpdateDetectedError,
    META_FILENAME,
    ProcessRunningError,
    apply_overrides_to_game,
    archive_old_backup_and_rebuild,
    ensure_vanilla_backup,
    inspect_game_status,
    load_workspace_snapshot,
    restore_vanilla_to_game,
)
from mod_configurator.gui import ModConfiguratorApp, WORLD_TAB_KEY, _enable_dpi_awareness
from mod_configurator.preset_manager import (
    PresetError,
    apply_batch_all_minerals_value,
    apply_batch_hp_factor,
    apply_batch_int_cost_factor,
    apply_batch_move_speed_factor,
    apply_batch_population_factor,
    apply_batch_time_factor,
    apply_batch_unlock_max_count,
    apply_batch_weapon_damage_factor,
    count_targets_by_affiliation,
    load_preset_file,
    save_preset_file,
    sync_weapon_overrides_to_unit,
)
from mod_configurator.unity_assets import (
    ATTACK_COMPONENT_CLASSES,
    AssetFormatError,
    KNOWN_LIMITED_MOD_1022_SHA256,
    KNOWN_VANILLA_D351_SHA256,
    ValidationError,
    compute_sha256_bytes,
    compute_sha256_file,
    parse_serialized_file_meta,
    parse_sharedassets_configs,
    patch_sharedassets_bytes,
    reconstruct_vanilla_from_limited_mod,
    validate_component_field_value,
    validate_field_value,
)

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
GAME_DATA_DIR = WORKSPACE_DIR.parent / "Dust Front RTS_Data"
PRESET_1022_PATH = WORKSPACE_DIR / "presets" / "limited_mod_1022.json"
MOD_SHAREDASSETS_PATH = WORKSPACE_DIR / "sharedassets0.assets"


def _locate_clean_vanilla_bytes(ggm_path: Path) -> bytes:
    """只读定位干净 D-35-1 原版字节（不触碰也不依赖用户当前修改过的游戏文件）。"""
    direct = GAME_DATA_DIR / "sharedassets0.assets"
    if direct.is_file() and compute_sha256_file(direct) == KNOWN_VANILLA_D351_SHA256:
        return direct.read_bytes()
    bak = GAME_DATA_DIR / BACKUP_FILENAME
    if bak.is_file() and compute_sha256_file(bak) == KNOWN_VANILLA_D351_SHA256:
        return bak.read_bytes()
    if MOD_SHAREDASSETS_PATH.is_file():
        return bytes(
            reconstruct_vanilla_from_limited_mod(MOD_SHAREDASSETS_PATH.read_bytes(), ggm_path)
        )
    raise AssertionError("无法找到干净的 D-35-1 原版 sharedassets0.assets 字节")


class TestDustFrontPatcher(unittest.TestCase):
    """基于真实 D-35-1 只读资产与临时沙盒目录的 V1+V2 全量回归验收测试。"""

    @classmethod
    def setUpClass(cls) -> None:
        assert GAME_DATA_DIR.is_dir(), f"未找到游戏数据目录: {GAME_DATA_DIR}"
        cls.ggm_path = GAME_DATA_DIR / "globalgamemanagers.assets"
        cls.res_path = GAME_DATA_DIR / "resources.assets"
        cls.vanilla_bytes = _locate_clean_vanilla_bytes(cls.ggm_path)
        cls.vanilla_bundle = parse_sharedassets_configs(
            cls.vanilla_bytes, cls.ggm_path, cls.res_path
        )

    def _make_temp_game_dir(self, tmp_root: str, *, use_mod_as_current: bool = False) -> Path:
        data_dir = Path(tmp_root) / "Dust Front RTS_Data"
        data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.ggm_path, data_dir / "globalgamemanagers.assets")
        if self.res_path.is_file():
            shutil.copy2(self.res_path, data_dir / "resources.assets")
        dst_shared = data_dir / "sharedassets0.assets"
        if use_mod_as_current:
            shutil.copy2(MOD_SHAREDASSETS_PATH, dst_shared)
        else:
            dst_shared.write_bytes(self.vanilla_bytes)
        return data_dir

    # --- V1 验收指标 1：全量解析覆盖率、外部引用与汉化降级 ---
    def test_01_full_config_parsing_and_localization(self) -> None:
        self.assertEqual(self.vanilla_bundle.ggm_file_id, 1)
        counts: dict[str, int] = {}
        for item in self.vanilla_bundle.items:
            counts[item.script] = counts.get(item.script, 0) + 1
            for floc in item.fields.values():
                self.assertGreaterEqual(floc.rel_offset, 0)
                self.assertLessEqual(floc.rel_offset + 4, item.byte_size)

        self.assertEqual(counts["BuildConfig"], 63)
        self.assertEqual(counts["UnitConfig"], 66)
        self.assertEqual(counts["UpgradeConfig"], 40)
        self.assertEqual(counts["TacticalAbilityConfig"], 7)
        self.assertEqual(len(self.vanilla_bundle.items), 176)

        self.assertEqual(
            self.vanilla_bundle.by_key[("BuildConfig", "r_Barn_Build")].display_name, "仓库"
        )
        self.assertEqual(
            self.vanilla_bundle.by_key[("UnitConfig", "r_Dreadnought_Unit")].display_name, "无畏舰"
        )
        self.assertEqual(
            self.vanilla_bundle.by_key[("BuildConfig", "r_Crane_Build")].display_name,
            "工程起重机",
        )
        self.assertEqual(
            self.vanilla_bundle.by_key[("UnitConfig", "r_MCV_BuildMobile")].display_name,
            "机动建造车",
        )
        for script, name in (
            ("UnitConfig", "CargoTruckBus_Unit"),
            ("UnitConfig", "CargoTruckFuel_Unit"),
            ("UnitConfig", "CargoTruckRes_Unit"),
            ("BuildConfig", "Point"),
        ):
            self.assertEqual(
                self.vanilla_bundle.by_key[(script, name)].display_name,
                f"[无译名] {name}",
            )

        self.assertEqual(
            self.vanilla_bundle.by_key[("TacticalAbilityConfig", "r_yakDefence")]
            .fields["useInFog"]
            .value,
            1,
        )
        self.assertEqual(
            self.vanilla_bundle.by_key[("TacticalAbilityConfig", "r_heavyBombardment")]
            .fields["useInFog"]
            .value,
            0,
        )

        bad_endian = bytearray(self.vanilla_bytes)
        bad_endian[16] = 1
        with self.assertRaises(AssetFormatError):
            parse_serialized_file_meta(bad_endian)

        bad_ver = bytearray(self.vanilla_bytes)
        struct.pack_into(">I", bad_ver, 8, 21)
        with self.assertRaises(AssetFormatError):
            parse_serialized_file_meta(bad_ver)

    # --- V1 验收指标 2：正向逐字节黄金校验 ---
    def test_02_golden_forward_patch_exact_sha256(self) -> None:
        self.assertEqual(compute_sha256_bytes(self.vanilla_bytes), KNOWN_VANILLA_D351_SHA256)
        self.assertEqual(len(self.vanilla_bytes), 76_600_076)

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            preset_res = load_preset_file(PRESET_1022_PATH, self.vanilla_bundle)
            self.assertEqual(preset_res.warnings, [])
            self.assertEqual(sum(len(v) for v in preset_res.overrides.values()), 10)

            new_sha, patched_count = apply_overrides_to_game(
                data_dir,
                preset_res.overrides,
                tasklist_runner=lambda: b"",
            )
            self.assertEqual(patched_count, 10)
            self.assertEqual(new_sha, KNOWN_LIMITED_MOD_1022_SHA256)
            patched_file = data_dir / "sharedassets0.assets"
            self.assertEqual(patched_file.stat().st_size, 76_600_076)
            self.assertEqual(compute_sha256_file(patched_file), KNOWN_LIMITED_MOD_1022_SHA256)

            snap = load_workspace_snapshot(data_dir)
            self.assertEqual(snap.status.code, "limited_mod_1022")
            self.assertEqual(sum(len(v) for v in snap.initial_overrides.values()), 10)

    # --- V1 验收指标 3：反向重建黄金校验 ---
    def test_03_golden_reverse_reconstruction_from_mod(self) -> None:
        self.assertEqual(compute_sha256_file(MOD_SHAREDASSETS_PATH), KNOWN_LIMITED_MOD_1022_SHA256)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=True)

            snap = load_workspace_snapshot(data_dir)
            self.assertTrue(snap.reconstructed_in_memory)
            self.assertEqual(snap.status.code, "limited_mod_1022")
            self.assertFalse((data_dir / BACKUP_FILENAME).exists())

            backup_path, _ = ensure_vanilla_backup(data_dir)
            self.assertEqual(compute_sha256_file(backup_path), KNOWN_VANILLA_D351_SHA256)

            restored_sha = restore_vanilla_to_game(data_dir, tasklist_runner=lambda: b"")
            self.assertEqual(restored_sha, KNOWN_VANILLA_D351_SHA256)
            self.assertEqual(
                compute_sha256_file(data_dir / "sharedassets0.assets"),
                KNOWN_VANILLA_D351_SHA256,
            )

    # --- V1 验收指标 4：跨版本更新防覆写保护 ---
    def test_04_cross_version_update_protection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            overrides = {("BuildConfig", "r_Barn_Build"): {"limitProduce": 400}}
            apply_overrides_to_game(data_dir, overrides, tasklist_runner=lambda: b"")

            game_file = data_dir / "sharedassets0.assets"
            fake_new_bytes, _ = patch_sharedassets_bytes(
                game_file.read_bytes(),
                self.vanilla_bundle,
                {("BuildConfig", "r_Barn_Build"): {"minerals": 999}},
            )
            game_file.write_bytes(fake_new_bytes)
            fake_new_sha = compute_sha256_bytes(fake_new_bytes)

            status = inspect_game_status(data_dir)
            self.assertEqual(status.code, "external_update_conflict")
            self.assertFalse(status.can_write_directly)

            with self.assertRaises(ExternalUpdateDetectedError):
                apply_overrides_to_game(data_dir, overrides, tasklist_runner=lambda: b"")
            with self.assertRaises(ExternalUpdateDetectedError):
                restore_vanilla_to_game(data_dir, tasklist_runner=lambda: b"")
            self.assertEqual(compute_sha256_file(game_file), fake_new_sha)

            archived, new_backup, new_meta = archive_old_backup_and_rebuild(
                data_dir, allow_unknown_baseline=True
            )
            self.assertGreaterEqual(len(archived), 2)
            self.assertTrue(all(p.name.endswith(".old") and p.is_file() for p in archived))
            self.assertEqual(compute_sha256_file(new_backup), fake_new_sha)
            self.assertEqual(new_meta["vanilla_sha256"], fake_new_sha)

    # --- V1 验收指标 5：旧 .bak 文件彻底隔离 ---
    def test_05_old_bak_file_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            old_bak = data_dir / "sharedassets0.assets.bak"
            old_bak.write_bytes(b"OLD_1016_BACKUP_DO_NOT_TOUCH")
            os.utime(old_bak, (1_700_000_000, 1_700_000_000))
            orig_mtime = old_bak.stat().st_mtime_ns
            orig_sha = compute_sha256_file(old_bak)

            preset_res = load_preset_file(PRESET_1022_PATH, self.vanilla_bundle)
            apply_overrides_to_game(data_dir, preset_res.overrides, tasklist_runner=lambda: b"")
            restore_vanilla_to_game(data_dir, tasklist_runner=lambda: b"")
            archive_old_backup_and_rebuild(data_dir, allow_unknown_baseline=True)

            self.assertEqual(compute_sha256_file(old_bak), orig_sha)
            self.assertEqual(old_bak.stat().st_mtime_ns, orig_mtime)

    # --- V1 验收指标 6：输入校验、Schema、批量口径、进程锁、未知基准与原子清理 ---
    def test_06_validation_schema_batch_locks_and_atomic_cleanup(self) -> None:
        for bad_int in (-1, 1_000_000, 1.5, True, "abc", ""):
            with self.assertRaises(ValidationError):
                validate_field_value("BuildConfig", "minerals", bad_int, 100)

        for bad_float in (-0.1, float("nan"), float("inf"), float("-inf"), True, 100_000.0):
            with self.assertRaises(ValidationError):
                validate_field_value("BuildConfig", "timeCreation", bad_float, 40.0)

        with self.assertRaises(ValidationError):
            validate_field_value("BuildConfig", "timeCreation", 0.0, 40.0)
        with self.assertRaises(ValidationError):
            validate_field_value("BuildConfig", "timeCreation", 0.4, 40.0)
        self.assertEqual(validate_field_value("BuildConfig", "timeCreation", 0.5, 40.0), 0.5)
        self.assertEqual(validate_field_value("UnitConfig", "timeCreation", 0.0, 0.0), 0.0)

        for ro in ("faction", "onlyGlobalMinerals", "skipLoadIfBlocked"):
            with self.assertRaises(ValidationError):
                validate_field_value("BuildConfig", ro, 1, 0)

        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp)
            corrupt = pdir / "corrupt.json"
            corrupt.write_text("{bad json", encoding="utf-8")
            with self.assertRaises(PresetError):
                load_preset_file(corrupt, self.vanilla_bundle)

            readonly_preset = pdir / "ro.json"
            readonly_preset.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "bad",
                        "changes": [
                            {
                                "script": "BuildConfig",
                                "asset_name": "r_Barn_Build",
                                "field": "faction",
                                "value": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(PresetError):
                load_preset_file(readonly_preset, self.vanilla_bundle)

            missing_obj_preset = pdir / "future.json"
            missing_obj_preset.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "cross_ver",
                        "changes": [
                            {
                                "script": "BuildConfig",
                                "asset_name": "Future_Removed_Building",
                                "field": "minerals",
                                "value": 50,
                            },
                            {
                                "script": "BuildConfig",
                                "asset_name": "r_Barn_Build",
                                "field": "limitProduce",
                                "value": 300,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_preset_file(missing_obj_preset, self.vanilla_bundle)
            self.assertEqual(len(loaded.warnings), 1)
            self.assertEqual(loaded.overrides[("BuildConfig", "r_Barn_Build")]["limitProduce"], 300)

            saved = pdir / "saved.json"
            save_preset_file(saved, "导出测试", "desc", self.vanilla_bundle, loaded.overrides)
            reloaded = load_preset_file(saved, self.vanilla_bundle)
            self.assertEqual(reloaded.overrides, loaded.overrides)
            self.assertEqual(reloaded.preset.schema_version, 2)

        bld_keys = [
            (it.script, it.asset_name)
            for it in self.vanilla_bundle.items
            if it.script == "BuildConfig"
        ]
        unit_keys = [
            (it.script, it.asset_name)
            for it in self.vanilla_bundle.items
            if it.script == "UnitConfig"
        ]
        ov1, cnt1 = apply_batch_time_factor(self.vanilla_bundle, {}, bld_keys, 0.5)
        self.assertGreater(cnt1, 0)
        ov2, cnt2 = apply_batch_time_factor(self.vanilla_bundle, ov1, bld_keys, 0.5)
        self.assertEqual(cnt2, 0)
        self.assertEqual(ov1, ov2)
        self.assertEqual(ov1[("BuildConfig", "r_Crane_Build")]["timeCreation"], 20.0)

        ov_pop, _ = apply_batch_population_factor(self.vanilla_bundle, {}, bld_keys, 2.0)
        self.assertEqual(ov_pop[("BuildConfig", "r_Barn_Build")]["limitProduce"], 60)
        self.assertNotIn(("BuildConfig", "r_Crane_Build"), ov_pop)

        ov_gear, _ = apply_batch_int_cost_factor(self.vanilla_bundle, {}, bld_keys, "gears", 0.5)
        self.assertEqual(ov_gear[("BuildConfig", "r_BarnBig_Build")]["gears"], 20)

        ov_unlock, unlocked = apply_batch_unlock_max_count(self.vanilla_bundle, {}, unit_keys)
        self.assertEqual(unlocked, 2)
        self.assertEqual(ov_unlock[("UnitConfig", "y_WheeledDom_Unit")]["maxCount"], 0)
        self.assertEqual(ov_unlock[("UnitConfig", "merc_DreadMK0_Unit")]["maxCount"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)

            fake_csv_game = '"Dust Front RTS.exe","1234","Console","1","100,000 K"\n'.encode("utf-8")
            with self.assertRaises(ProcessRunningError):
                apply_overrides_to_game(data_dir, {}, tasklist_runner=lambda: fake_csv_game)

            fake_csv_launcher = '"Dust Front RTS 单机启动器.exe","5678","Console","1","50,000 K"\n'.encode("mbcs")
            with self.assertRaises(ProcessRunningError):
                restore_vanilla_to_game(data_dir, tasklist_runner=lambda: fake_csv_launcher)

            def _failing_replace(_src: Path, _dst: Path) -> None:
                raise PermissionError("simulated AV lock")

            with self.assertRaises(PermissionError):
                apply_overrides_to_game(
                    data_dir,
                    {("BuildConfig", "r_Barn_Build"): {"limitProduce": 250}},
                    tasklist_runner=lambda: b"",
                    replace_fn=_failing_replace,
                )
            self.assertEqual(list(data_dir.glob("*.tmp")), [])
            self.assertEqual(
                compute_sha256_file(data_dir / "sharedassets0.assets"),
                KNOWN_VANILLA_D351_SHA256,
            )

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            unknown_bytes, _ = patch_sharedassets_bytes(
                self.vanilla_bytes,
                self.vanilla_bundle,
                {("BuildConfig", "r_Barn_Build"): {"limitProduce": 123}},
            )
            (data_dir / "sharedassets0.assets").write_bytes(unknown_bytes)
            self.assertEqual(inspect_game_status(data_dir).code, "unknown_baseline")
            with self.assertRaises(BaselineConfirmationRequiredError):
                apply_overrides_to_game(
                    data_dir,
                    {("BuildConfig", "r_Barn_Build"): {"limitProduce": 456}},
                    allow_unknown_baseline=False,
                    tasklist_runner=lambda: b"",
                )
            new_sha, _ = apply_overrides_to_game(
                data_dir,
                {("BuildConfig", "r_Barn_Build"): {"limitProduce": 456}},
                allow_unknown_baseline=True,
                tasklist_runner=lambda: b"",
            )
            self.assertEqual(
                compute_sha256_file(data_dir / BACKUP_FILENAME),
                compute_sha256_bytes(unknown_bytes),
            )
            self.assertEqual(compute_sha256_file(data_dir / "sharedassets0.assets"), new_sha)
            meta = json.loads((data_dir / META_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(meta["last_applied_sha256"], new_sha)

    # --- V1 GUI 回归测试（适配 V2 默认归属后支持切换全部验证 V1 等价条目） ---
    def test_07_gui_v1_compat_regression(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            root = tk.Tk()
            root.withdraw()
            try:
                app = ModConfiguratorApp(
                    root,
                    workspace_dir=WORKSPACE_DIR,
                    initial_game_dir=data_dir,
                    confirm_fn=lambda _t, _m: True,
                    info_fn=lambda _t, _m: None,
                    warn_fn=lambda _t, _m: None,
                    error_fn=lambda _t, m: self.fail(f"GUI unexpected error: {m}"),
                )
                # V2 默认锁定 我方（帝国）
                self.assertEqual(len(app.filtered_keys), 23)
                # 切至 全部（含敌我） 应保持 V1 全量计数 63 / 66 / 40 / 7
                app.set_affiliation_filter_code("all")
                self.assertEqual(len(app.filtered_keys), 63)

                app.select_script_tab("UnitConfig")
                self.assertEqual(len(app.filtered_keys), 66)

                app.search_var.set("无畏")
                root.update_idletasks()
                self.assertIn(("UnitConfig", "r_Dreadnought_Unit"), app.filtered_keys)
                app.search_var.set("r_Dreadnought_Unit")
                root.update_idletasks()
                self.assertEqual(app.filtered_keys, [("UnitConfig", "r_Dreadnought_Unit")])
                app.search_var.set("")

                app.select_script_tab("UpgradeConfig")
                self.assertEqual(len(app.filtered_keys), 40)

                app.select_script_tab("TacticalAbilityConfig")
                self.assertEqual(len(app.filtered_keys), 7)

                app.select_script_tab("BuildConfig")
                app._on_load_selected_preset()
                self.assertEqual(len(app.overrides), 5)

                changed = app._run_batch_operation("time_half", skip_confirm=True)
                self.assertGreater(changed, 0)
                app._on_undo_batch()
                self.assertEqual(len(app.overrides), 5)
            finally:
                root.destroy()

    # --- V2 验收指标 1：实战归属分类准确性 ---
    def test_08_affiliation_classification_accuracy(self) -> None:
        aff_counts = Counter(it.affiliation for it in self.vanilla_bundle.items)
        self.assertEqual(aff_counts["player_empire"], 96)
        self.assertEqual(aff_counts["player_merc"], 6)
        self.assertEqual(aff_counts["enemy_mutants"], 27)
        self.assertEqual(aff_counts["enemy_rebels"], 18)
        self.assertEqual(aff_counts["enemy_robots"], 13)
        self.assertEqual(aff_counts["neutral"], 16)
        self.assertEqual(len(self.vanilla_bundle.world_items), 9)

        # 验证关键原版纠偏项
        self.assertEqual(
            self.vanilla_bundle.by_key[("BuildConfig", "r_Trench_Build")].affiliation,
            "player_empire",
        )
        self.assertEqual(
            self.vanilla_bundle.by_key[("BuildConfig", "y_Refinery_Build")].affiliation,
            "enemy_rebels",
        )
        for m in (
            "merc_DreadMK0_Unit",
            "merc_LaserTank_Unit",
            "merc_Marauder_Unit",
            "merc_Mechbot_Unit",
            "merc_Rafa_Unit",
            "merc_Scorpion_Unit",
        ):
            self.assertEqual(self.vanilla_bundle.by_key[("UnitConfig", m)].affiliation, "player_merc")

        tactical = {
            it.asset_name: it.affiliation
            for it in self.vanilla_bundle.items
            if it.script == "TacticalAbilityConfig"
        }
        self.assertEqual(sum(1 for v in tactical.values() if v == "player_empire"), 5)
        self.assertEqual(sum(1 for v in tactical.values() if v == "enemy_mutants"), 2)
        self.assertEqual(tactical["TacticalInfuse"], "enemy_mutants")
        self.assertEqual(tactical["mutantBirdBombardment"], "enemy_mutants")

    # --- V2 验收指标 2：10 类 Prefab 与地图组件全量解析无报错及精确数量 ---
    def test_09_prefab_and_world_component_parsing(self) -> None:
        bld_unit = [
            it for it in self.vanilla_bundle.items if it.script in ("BuildConfig", "UnitConfig")
        ]
        linked_cfgs = sum(1 for it in bld_unit if it.main_prefab_pid != 0)
        unlinked_cfgs = sum(1 for it in bld_unit if it.main_prefab_pid == 0)
        self.assertEqual(linked_cfgs, 109)
        self.assertEqual(unlinked_cfgs, 20)

        comp_counts = Counter(c.comp_class for c in self.vanilla_bundle.components)
        self.assertEqual(comp_counts["HP"], 110)
        atk_total = sum(comp_counts[c] for c in ATTACK_COMPONENT_CLASSES)
        self.assertEqual(atk_total, 106)
        self.assertEqual(
            comp_counts["TankPattern"] + comp_counts["CarPattern"] + comp_counts["SmoothPattern"],
            50,
        )
        self.assertEqual(comp_counts["UnitComponent"], 112)
        self.assertEqual(comp_counts["BuildComponent"], 17)
        self.assertEqual(comp_counts["HealRange"], 10)
        self.assertEqual(comp_counts["Bunker"], 6)
        self.assertEqual(comp_counts["Regeneration"], 5)
        self.assertEqual(comp_counts["Harvester"], 2)
        self.assertEqual(comp_counts["FogOfWarUnit"], 2)

        world_counts = Counter(w.comp_class for w in self.vanilla_bundle.world_items)
        self.assertEqual(world_counts["Mineral"], 7)
        self.assertEqual(world_counts["OilPump"], 2)
        self.assertEqual(comp_counts["OilPump"] + world_counts["OilPump"], 4)

    # --- V2 验收指标 3：HP 双写 curHp、有符号校验、零冷却特例与共享 Prefab 冲突保护 ---
    def test_10_hp_dual_write_and_component_validation(self) -> None:
        dread = self.vanilla_bundle.by_key[("UnitConfig", "r_Dreadnought_Unit")]
        hp_comp = next(c for c in dread.components if c.comp_class == "HP")
        patched, cnt = patch_sharedassets_bytes(
            self.vanilla_bytes,
            self.vanilla_bundle,
            {},
            component_overrides={hp_comp.key: {"maxHp": 4500}},
        )
        self.assertEqual(cnt, 1)
        (max_hp_written, cur_hp_written) = struct.unpack_from("<ii", patched, hp_comp.body_abs + 0x10)
        self.assertEqual(max_hp_written, 4500)
        self.assertEqual(cur_hp_written, 4500)

        # 允许负抗性与负 addRange
        self.assertAlmostEqual(validate_component_field_value("HP", "fireResist", -0.8), -0.8)
        self.assertAlmostEqual(
            validate_component_field_value("AutoAttack_MG", "addRange", -7.0), -7.0
        )
        with self.assertRaises(ValidationError):
            validate_component_field_value("HP", "fireResist", -2.1)
        with self.assertRaises(ValidationError):
            validate_component_field_value("AutoAttack_MG", "addRange", -10.0)
        with self.assertRaises(ValidationError):
            validate_component_field_value("HP", "hpType", 1)

        # 原版 coolDownShot==0.0 (如 BTR_flamer) 允许保持 0.0，原版 >0 则下限 0.05
        self.assertEqual(
            validate_component_field_value(
                "AutoAttack_Projectile", "coolDownShot", 0.0, vanilla_value=0.0
            ),
            0.0,
        )
        with self.assertRaises(ValidationError):
            validate_component_field_value(
                "AutoAttack_Projectile", "coolDownShot", 0.0, vanilla_value=1.0
            )

        # 共享 Prefab 冲突拦截：HeavyWall_Build 与 LargePipe_Build 共享 HP
        hw_hp = next(
            c
            for c in self.vanilla_bundle.by_key[("BuildConfig", "HeavyWall_Build")].components
            if c.comp_class == "HP"
        )
        lp_hp = next(
            c
            for c in self.vanilla_bundle.by_key[("BuildConfig", "LargePipe_Build")].components
            if c.comp_class == "HP"
        )
        # 相同值幂等放行
        patch_sharedassets_bytes(
            self.vanilla_bytes,
            self.vanilla_bundle,
            {},
            component_overrides={hw_hp.key: {"maxHp": 1200}, lp_hp.key: {"maxHp": 1200}},
        )
        # 不同值拒绝
        with self.assertRaises(ValidationError):
            patch_sharedassets_bytes(
                self.vanilla_bytes,
                self.vanilla_bundle,
                {},
                component_overrides={hw_hp.key: {"maxHp": 1200}, lp_hp.key: {"maxHp": 1500}},
            )

    # --- V2 验收指标 4：同名子组件 occ_index 独立修改互不串位 ---
    def test_11_duplicate_child_occ_index_independence(self) -> None:
        avan = self.vanilla_bundle.by_key[("BuildConfig", "r_Avanpost_Build")]
        turret_mgs = [
            c
            for c in avan.components
            if c.comp_class == "AutoAttack_MG" and c.go_rel_path == "Avanpost/turL/turretMg"
        ]
        self.assertEqual(len(turret_mgs), 2)
        self.assertEqual([t.occ_index for t in turret_mgs], [0, 1])

        mcv = self.vanilla_bundle.by_key[("UnitConfig", "r_MCV_BuildMobile")]
        mcv_atks = [c for c in mcv.components if c.comp_class in ATTACK_COMPONENT_CLASSES]
        self.assertEqual(len(mcv_atks), 4)

        patched, cnt = patch_sharedassets_bytes(
            self.vanilla_bytes,
            self.vanilla_bundle,
            {},
            component_overrides={
                turret_mgs[0].key: {"gun_damageToInfantry": 111},
                turret_mgs[1].key: {"gun_damageToInfantry": 222},
            },
        )
        self.assertEqual(cnt, 2)
        parsed_after = parse_sharedassets_configs(patched, self.ggm_path, None)
        self.assertEqual(
            parsed_after.components_by_key[turret_mgs[0].key].fields["gun_damageToInfantry"].value,
            111,
        )
        self.assertEqual(
            parsed_after.components_by_key[turret_mgs[1].key].fields["gun_damageToInfantry"].value,
            222,
        )

    # --- V2 验收指标 5：Schema v1 向下兼容 & Schema v2 保存/加载/补丁/快照识别/一键还原闭环 ---
    def test_12_schema_v1_compat_and_v2_roundtrip(self) -> None:
        dread = self.vanilla_bundle.by_key[("UnitConfig", "r_Dreadnought_Unit")]
        hp_comp = next(c for c in dread.components if c.comp_class == "HP")
        atk_comp = next(c for c in dread.components if c.comp_class in ATTACK_COMPONENT_CLASSES)
        first_mineral = next(w for w in self.vanilla_bundle.world_items if w.comp_class == "Mineral")

        cfg_ov = {("UnitConfig", "r_Dreadnought_Unit"): {"timeCreation": 45.0}}
        comp_ov = {
            hp_comp.key: {"maxHp": 4200},
            atk_comp.key: {"gun_damageToVehicle": 800},
        }
        world_ov = {first_mineral.key: {"minerals": 9500}}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            preset_v2_path = tmp_path / "v2_test.json"
            save_preset_file(
                preset_v2_path,
                "V2 往返测试",
                "三层全覆写",
                self.vanilla_bundle,
                cfg_ov,
                component_overrides=comp_ov,
                world_overrides=world_ov,
            )
            raw_json = json.loads(preset_v2_path.read_text(encoding="utf-8"))
            self.assertEqual(raw_json["schema_version"], 2)

            # 加入一个未知版本组件，校验温和跳过并保留其余修改
            raw_json["component_changes"].append(
                {
                    "config_script": "UnitConfig",
                    "config_asset_name": "Future_Removed_Unit",
                    "comp_class": "HP",
                    "go_rel_path": "Future",
                    "occ_index": 0,
                    "field": "maxHp",
                    "value": 9999,
                }
            )
            preset_v2_warn_path = tmp_path / "v2_warn.json"
            preset_v2_warn_path.write_text(
                json.dumps(raw_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            loaded = load_preset_file(preset_v2_warn_path, self.vanilla_bundle)
            self.assertEqual(len(loaded.warnings), 1)
            self.assertEqual(loaded.overrides, cfg_ov)
            self.assertEqual(loaded.component_overrides, comp_ov)
            self.assertEqual(loaded.world_overrides, world_ov)

            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            new_sha, cnt = apply_overrides_to_game(
                data_dir,
                loaded.overrides,
                component_overrides=loaded.component_overrides,
                world_overrides=loaded.world_overrides,
                tasklist_runner=lambda: b"",
            )
            self.assertEqual(cnt, 4)

            snap = load_workspace_snapshot(data_dir)
            self.assertEqual(snap.status.code, "custom_mod")
            self.assertEqual(snap.initial_overrides, cfg_ov)
            self.assertEqual(snap.initial_component_overrides, comp_ov)
            self.assertEqual(snap.initial_world_overrides, world_ov)
            self.assertIn("4 项改动", snap.status.label)
            self.assertEqual(compute_sha256_file(data_dir / "sharedassets0.assets"), new_sha)

            restored_sha = restore_vanilla_to_game(data_dir, tasklist_runner=lambda: b"")
            self.assertEqual(restored_sha, KNOWN_VANILLA_D351_SHA256)

    # --- V2 验收指标 6：默认归属 我方（帝国） 批量修改对敌方/雇佣兵/中立影响为 0 ---
    def test_13_default_empire_filter_zero_enemy_impact(self) -> None:
        empire_keys = [
            (it.script, it.asset_name)
            for it in self.vanilla_bundle.items
            if it.affiliation == "player_empire"
        ]
        self.assertEqual(len(empire_keys), 96)
        stats = count_targets_by_affiliation(self.vanilla_bundle, empire_keys)
        self.assertEqual(stats["player_empire"], 96)
        self.assertEqual(stats["enemy"], 0)
        self.assertEqual(stats["neutral"], 0)
        self.assertEqual(stats["player_merc"], 0)

        cfg_ov, _ = apply_batch_time_factor(self.vanilla_bundle, {}, empire_keys, 0.5)
        cfg_ov, _ = apply_batch_int_cost_factor(self.vanilla_bundle, cfg_ov, empire_keys, "minerals", 0.5)
        cfg_ov, _ = apply_batch_population_factor(self.vanilla_bundle, cfg_ov, empire_keys, 2.0)

        comp_ov, _ = apply_batch_hp_factor(self.vanilla_bundle, {}, empire_keys, 2.0)
        comp_ov, _ = apply_batch_weapon_damage_factor(self.vanilla_bundle, comp_ov, empire_keys, 2.0)
        comp_ov, _ = apply_batch_move_speed_factor(self.vanilla_bundle, comp_ov, empire_keys, 1.5)

        self.assertGreater(len(cfg_ov), 0)
        self.assertGreater(len(comp_ov), 0)

        for key in cfg_ov:
            self.assertEqual(self.vanilla_bundle.by_key[key].affiliation, "player_empire")
        for ckey in comp_ov:
            owner = self.vanilla_bundle.by_key[(ckey[0], ckey[1])]
            self.assertEqual(owner.affiliation, "player_empire")

        # 一键修改全部 7 个标准矿脉
        world_ov, wcnt = apply_batch_all_minerals_value(self.vanilla_bundle, {}, 8888)
        self.assertEqual(wcnt, 7)
        self.assertEqual(len(world_ov), 7)

        # 多武器单位一键同步
        bron = self.vanilla_bundle.by_key[("UnitConfig", "r_Bronenosets_Unit")]
        bron_wpns = [c for c in bron.components if c.comp_class in ATTACK_COMPONENT_CLASSES]
        self.assertEqual(len(bron_wpns), 5)
        synced_comp, synced_cnt = sync_weapon_overrides_to_unit(
            self.vanilla_bundle,
            {bron_wpns[0].key: {"gun_damageToVehicle": 777}},
            bron_wpns[0].key,
        )
        self.assertEqual(synced_cnt, 4)
        for w in bron_wpns:
            self.assertEqual(synced_comp[w.key]["gun_damageToVehicle"], 777)

    # --- V2 验收指标 7：V2 GUI 无头冒烟测试与启动脚本 --check ---
    def test_14_v2_gui_smoke_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            root = tk.Tk()
            root.withdraw()
            try:
                app = ModConfiguratorApp(
                    root,
                    workspace_dir=WORKSPACE_DIR,
                    initial_game_dir=data_dir,
                    confirm_fn=lambda _t, _m: True,
                    info_fn=lambda _t, _m: None,
                    warn_fn=lambda _t, _m: None,
                    error_fn=lambda _t, m: self.fail(f"GUI unexpected error: {m}"),
                )
                # 默认选中 我方（帝国），包含 23 个帝国建筑，无敌方警告
                self.assertEqual(app.affiliation_filter_var.get(), "我方（帝国）")
                self.assertEqual(len(app.filtered_keys), 23)
                self.assertFalse(app.enemy_warning_visible)

                # 战术支援页签默认只看我方 5 项；切至 敌方·变种人 亮起敌方警告
                app.select_script_tab("TacticalAbilityConfig")
                self.assertEqual(len(app.filtered_keys), 5)
                self.assertFalse(app.enemy_warning_visible)
                app.set_affiliation_filter_code("enemy_mutants")
                self.assertEqual(len(app.filtered_keys), 2)
                self.assertTrue(app.enemy_warning_visible)

                # 切换地图资源点锁定 中立/地图物件 (9 项)，切回 UnitConfig 时恢复先前筛选
                app.select_script_tab(WORLD_TAB_KEY)
                self.assertEqual(len(app.filtered_keys), 9)
                self.assertFalse(app.enemy_warning_visible)
                changed_w = app.apply_batch_all_minerals(12000)
                self.assertEqual(changed_w, 7)

                app.select_script_tab("UnitConfig")
                app.set_affiliation_filter_code("player_empire")
                self.assertEqual(len(app.filtered_keys), 28)

                # 选中 r_Bronenosets_Unit 验证右侧 4 子页签与多武器切换
                iid_bron = app._encode_iid(("UnitConfig", "r_Bronenosets_Unit"))
                app.tree.selection_set(iid_bron)
                app.tree.focus(iid_bron)
                app._on_tree_select(None)
                self.assertEqual(app.selected_key, ("UnitConfig", "r_Bronenosets_Unit"))
                app._on_switch_weapon(("UnitConfig", "r_Bronenosets_Unit"), 2)

                # 批量血量 ×2 对 28 个帝国单位生效且不触及敌方
                hp_changed = app._run_batch_operation("hp_x2", skip_confirm=True)
                self.assertEqual(hp_changed, 28)
                for ckey in app.component_overrides:
                    self.assertEqual(
                        self.vanilla_bundle.by_key[(ckey[0], ckey[1])].affiliation,
                        "player_empire",
                    )

                # 切至 机器人 占位无 Prefab 对象不崩溃
                app.set_affiliation_filter_code("enemy_robots")
                self.assertEqual(len(app.filtered_keys), 7)
                self.assertTrue(app.enemy_warning_visible)
            finally:
                root.destroy()

        bat_proc = subprocess.run(
            ["cmd", "/c", "启动MOD配置器.bat", "--check"],
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(
            bat_proc.returncode, 0, msg=f"BAT failed: {bat_proc.stdout}\n{bat_proc.stderr}"
        )
        self.assertIn("v2.0.0", bat_proc.stdout)
        self.assertIn("自检通过", bat_proc.stdout)

    # --- V2 验收指标 8：窗口化高 DPI 防遮挡与自适应布局检查 ---
    def test_15_gui_layout_no_clipping(self) -> None:
        _enable_dpi_awareness()
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = self._make_temp_game_dir(tmp, use_mod_as_current=False)
            root = tk.Tk()
            try:
                root.geometry("1080x700+20+20")
                root.minsize(1000, 640)
                app = ModConfiguratorApp(
                    root,
                    workspace_dir=WORKSPACE_DIR,
                    initial_game_dir=data_dir,
                    confirm_fn=lambda _t, _m: True,
                    info_fn=lambda _t, _m: None,
                    warn_fn=lambda _t, _m: None,
                    error_fn=lambda _t, m: self.fail(f"GUI unexpected error: {m}"),
                )
                root.update_idletasks()
                root.update()

                # 1. 顶部与整体请求宽度不得溢出紧凑窗口 (1080x700)
                self.assertLessEqual(app.tools_frame.winfo_reqwidth(), 1060)
                self.assertLessEqual(app.outer.winfo_reqwidth(), 1060)
                self.assertLessEqual(app.outer.winfo_reqheight(), 680)

                def _assert_footer_buttons_visible() -> None:
                    root_bottom = root.winfo_rooty() + root.winfo_height()
                    root_right = root.winfo_rootx() + root.winfo_width()
                    for btn in (app.restore_btn, app.apply_btn, app.apply_launch_btn):
                        self.assertGreaterEqual(btn.winfo_height(), btn.winfo_reqheight())
                        self.assertLessEqual(btn.winfo_rooty() + btn.winfo_height(), root_bottom + 1)
                        self.assertLessEqual(btn.winfo_rootx() + btn.winfo_width(), root_right + 1)

                _assert_footer_buttons_visible()

                # 2. 触发敌方警示横幅时，底部按钮仍必须完整可见
                app.set_affiliation_filter_code("enemy_all")
                root.update_idletasks()
                root.update()
                self.assertTrue(app.enemy_warning_visible)
                _assert_footer_buttons_visible()

                # 3. 切回我方，分别在 BuildConfig(r_AtTurret_Build) 与 UnitConfig(r_Bronenosets_Unit)
                #    逐一检查右侧 4 个子页签是否存在向右溢出（保证“还原”按钮完整可见）
                app.set_affiliation_filter_code("player_empire")
                for tab_name, item_key in (
                    ("BuildConfig", ("BuildConfig", "r_AtTurret_Build")),
                    ("UnitConfig", ("UnitConfig", "r_Bronenosets_Unit")),
                ):
                    app.select_script_tab(tab_name)
                    iid = app._encode_iid(item_key)
                    app.tree.selection_set(iid)
                    app.tree.focus(iid)
                    app._on_tree_select(None)
                    for sub_idx in range(4):
                        app.inspector_notebook.select(sub_idx)
                        root.update_idletasks()
                        root.update()
                        canvas, inner, _wid = app._subtab_scroll_frames[sub_idx]
                        self.assertLessEqual(
                            inner.winfo_reqwidth(),
                            canvas.winfo_width() + 2,
                            msg=(
                                f"Subtab {sub_idx} overflow for {item_key}: "
                                f"inner={inner.winfo_reqwidth()} > canvas={canvas.winfo_width()}"
                            ),
                        )
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
