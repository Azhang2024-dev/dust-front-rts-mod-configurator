"""《灰烬战争》外部可视化 MOD 配置器桌面 GUI（V2：敌我防误触 + 第二梯队组件 + 纯标准库 tkinter/ttk）。"""

from __future__ import annotations

import ctypes
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk
from typing import Any, Callable

from .backup_manager import (
    BaselineConfirmationRequiredError,
    ExternalUpdateDetectedError,
    LAUNCHER_EXE_NAME,
    ProcessRunningError,
    WorkspaceSnapshot,
    apply_overrides_to_game,
    archive_old_backup_and_rebuild,
    detect_default_game_data_dir,
    launch_game_launcher,
    load_workspace_snapshot,
    restore_vanilla_to_game,
)
from .preset_manager import (
    ComponentOverridesMap,
    OverridesMap,
    PresetError,
    WorldOverridesMap,
    apply_batch_all_minerals_value,
    apply_batch_hp_factor,
    apply_batch_int_cost_factor,
    apply_batch_move_speed_factor,
    apply_batch_population_factor,
    apply_batch_time_factor,
    apply_batch_unlock_max_count,
    apply_batch_weapon_cooldown_factor,
    apply_batch_weapon_damage_factor,
    clone_component_overrides,
    clone_overrides,
    clone_world_overrides,
    count_targets_by_affiliation,
    list_preset_files,
    load_preset_file,
    reset_config_and_component_keys_to_vanilla,
    reset_world_keys_to_vanilla,
    save_preset_file,
    sync_weapon_overrides_to_unit,
)
from .unity_assets import (
    ADVANCED_FIELDS_BY_SCRIPT,
    AFFILIATION_FILTER_OPTIONS,
    ALL_COMPONENT_FIELDS_FLAT,
    ATTACK_COMPONENT_CLASSES,
    ATTACK_DAMAGE_FIELDS,
    ComponentItem,
    ComponentKey,
    ConfigKey,
    DEFAULT_AFFILIATION_FILTER,
    FIELD_META,
    FieldSpec,
    MOVE_COMPONENT_CLASSES,
    PRIMARY_FIELDS_BY_SCRIPT,
    SCRIPT_TAB_LABELS,
    TARGET_SCRIPTS,
    ValidationError,
    WorldKey,
    get_component_field_spec,
    is_enemy_affiliation,
    matches_affiliation_filter,
    validate_component_field_value,
    validate_field_value,
    values_equal,
    component_values_equal,
)

BUILTIN_VANILLA_LABEL = "原版默认数值 (Vanilla - 清空全部改动)"
WORLD_TAB_KEY = "WorldResources"
WORLD_TAB_LABEL = "地图资源点"

ALL_TOP_TABS: tuple[str, ...] = (*TARGET_SCRIPTS, WORLD_TAB_KEY)
TOP_TAB_LABELS: dict[str, str] = {
    **SCRIPT_TAB_LABELS,
    WORLD_TAB_KEY: WORLD_TAB_LABEL,
}
COMPACT_TAB_LABELS: dict[str, str] = {
    "BuildConfig": "建筑",
    "UnitConfig": "单位",
    "UpgradeConfig": "科技升级",
    "TacticalAbilityConfig": "战术支援",
    WORLD_TAB_KEY: "地图资源",
}

AFFILIATION_LABEL_TO_CODE: dict[str, str] = {
    label: code for code, label in AFFILIATION_FILTER_OPTIONS
}
AFFILIATION_CODE_TO_LABEL: dict[str, str] = {
    code: label for code, label in AFFILIATION_FILTER_OPTIONS
}

WEAPON_ATTR_FIELDS: tuple[str, ...] = (
    "minRange",
    "range",
    "addRange",
    "coolDownShot",
    "SpeedTower",
    "MoveAttack",
    "fogCheck",
)


def _enable_dpi_awareness() -> None:
    """在 Windows 下启用高分屏 DPI 缩放，忽略非 Windows 或权限异常。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def format_display_value_by_spec(spec: FieldSpec, value: int | float) -> str:
    """按 FieldSpec 将字段值格式化为便于对比阅读的字符串。"""
    if spec.kind == "bool":
        return "是 (1)" if int(value) == 1 else "否 (0)"
    if spec.kind == "int":
        return str(int(value))
    text = f"{round(float(value), 4):g}"
    if "." not in text and "e" not in text.lower():
        text += ".0"
    return text


def format_entry_text_by_spec(spec: FieldSpec, value: int | float) -> str:
    """按 FieldSpec 将字段值格式化为输入框初始文本。"""
    if spec.kind == "int":
        return str(int(value))
    val_f = round(float(value), 4)
    text = f"{val_f:g}"
    if "." not in text and "e" not in text.lower():
        text += ".0"
    return text


def format_display_value(field_name: str, value: int | float) -> str:
    """将配置层字段值格式化为便于对比阅读的字符串（V1 兼容接口）。"""
    spec = FIELD_META.get(field_name) or ALL_COMPONENT_FIELDS_FLAT[field_name]
    return format_display_value_by_spec(spec, value)


def format_entry_text(field_name: str, value: int | float) -> str:
    """将配置层字段值格式化为输入框初始文本（V1 兼容接口）。"""
    spec = FIELD_META.get(field_name) or ALL_COMPONENT_FIELDS_FLAT[field_name]
    return format_entry_text_by_spec(spec, value)


class ModConfiguratorApp:
    """V2 主配置器界面控制器。"""

    def __init__(
        self,
        root: tk.Misc,
        *,
        workspace_dir: Path,
        initial_game_dir: Path | None = None,
        confirm_fn: Callable[[str, str], bool] | None = None,
        info_fn: Callable[[str, str], Any] | None = None,
        warn_fn: Callable[[str, str], Any] | None = None,
        error_fn: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.root = root
        self.workspace_dir = Path(workspace_dir).resolve()
        self.presets_dir = self.workspace_dir / "presets"
        self.data_dir = (
            Path(initial_game_dir).resolve()
            if initial_game_dir
            else detect_default_game_data_dir(self.workspace_dir)
        )

        self._confirm = confirm_fn or messagebox.askyesno
        self._info = info_fn or messagebox.showinfo
        self._warn = warn_fn or messagebox.showwarning
        self._error = error_fn or messagebox.showerror

        self.snapshot: WorkspaceSnapshot | None = None
        self.overrides: OverridesMap = {}
        self.component_overrides: ComponentOverridesMap = {}
        self.world_overrides: WorldOverridesMap = {}
        self.batch_undo_stack: list[
            tuple[OverridesMap, ComponentOverridesMap, WorldOverridesMap]
        ] = []

        self.current_tab_script: str = "BuildConfig"
        self.selected_key: ConfigKey | WorldKey | None = None
        self.filtered_keys: list[ConfigKey | WorldKey] = []
        self._saved_config_affiliation: str = AFFILIATION_CODE_TO_LABEL[DEFAULT_AFFILIATION_FILTER]
        self._preset_choices: dict[str, Path | None] = {}

        # V2 右侧多子页签、多 HP / 多武器状态与统一编辑器映射
        self._field_editors: dict[tuple[str, Any, str], dict[str, Any]] = {}
        self._subtab_scroll_frames: dict[int, tuple[tk.Canvas, ttk.Frame, int]] = {}
        self._selected_hp_idx_by_config: dict[ConfigKey, int] = {}
        self._selected_weapon_idx_by_config: dict[ConfigKey, int] = {}
        self._suppress_tree_select = False
        self._suppress_entry_trace = False
        self.enemy_warning_visible: bool = False

        # Tk Variables
        self.game_dir_var = tk.StringVar(master=self.root, value=str(self.data_dir))
        self.status_badge_var = tk.StringVar(master=self.root, value="正在扫描游戏目录...")
        self.status_detail_var = tk.StringVar(master=self.root, value="")
        self.loc_warn_var = tk.StringVar(master=self.root, value="")

        self.preset_var = tk.StringVar(master=self.root)
        self.affiliation_filter_var = tk.StringVar(
            master=self.root, value=AFFILIATION_CODE_TO_LABEL[DEFAULT_AFFILIATION_FILTER]
        )
        # 向下兼容属性名别名
        self.faction_filter_var = self.affiliation_filter_var
        self.search_var = tk.StringVar(master=self.root, value="")
        self.only_modified_var = tk.BooleanVar(master=self.root, value=False)
        self.advanced_expanded_var = tk.BooleanVar(master=self.root, value=False)

        self.batch_scope_var = tk.StringVar(master=self.root, value="")
        self.enemy_warning_var = tk.StringVar(master=self.root, value="")
        self.item_title_var = tk.StringVar(master=self.root, value="未选择对象")
        self.item_meta_var = tk.StringVar(master=self.root, value="")
        self.item_desc_var = tk.StringVar(master=self.root, value="")
        self.validation_var = tk.StringVar(master=self.root, value="")
        self.footer_summary_var = tk.StringVar(master=self.root, value="待应用修改: 0 项")

        self._configure_style()
        self._build_ui()
        self.refresh_preset_dropdown()
        self.refresh_workspace()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        for preferred in ("vista", "winnative", "clam"):
            if preferred in available:
                style.theme_use(preferred)
                break
        default_font = ("Microsoft YaHei UI", 9)
        self.root.option_add("*Font", default_font)
        try:
            ui_font = tkfont.Font(master=self.root, family="Microsoft YaHei UI", size=9)
            row_h = max(22, ui_font.metrics("linespace") + 6)
        except Exception:
            row_h = 26
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Scope.TLabel", foreground="#004a99", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Warn.TLabel", foreground="#b26b00")
        style.configure("Error.TLabel", foreground="#c42b1c")
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Treeview", rowheight=row_h)

    def _build_ui(self) -> None:
        self.outer = ttk.Frame(self.root, padding=6)
        self.outer.pack(fill=tk.BOTH, expand=True)

        # --- F1 顶部游戏目录与状态诊断栏 ---
        self.diag_frame = ttk.LabelFrame(self.outer, text="游戏目录与状态诊断", padding=(6, 4))
        self.diag_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        dir_row = ttk.Frame(self.diag_frame)
        dir_row.pack(fill=tk.X)
        ttk.Label(dir_row, text="Dust Front RTS_Data 路径:").pack(side=tk.LEFT)
        dir_entry = ttk.Entry(dir_row, textvariable=self.game_dir_var)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        dir_entry.bind("<Return>", lambda _e: self._on_manual_dir_apply())
        ttk.Button(dir_row, text="浏览...", command=self._on_browse_dir).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(dir_row, text="重新扫描", command=self._on_manual_dir_apply).pack(side=tk.LEFT)

        status_row = ttk.Frame(self.diag_frame)
        status_row.pack(fill=tk.X, pady=(3, 0))
        self.archive_rebuild_btn = ttk.Button(
            status_row,
            text="归档旧备份并重建新基准",
            command=self._on_archive_and_rebuild,
        )
        self.status_badge_lbl = ttk.Label(
            status_row, textvariable=self.status_badge_var, style="Status.TLabel"
        )
        self.status_badge_lbl.pack(side=tk.LEFT)
        self.status_detail_lbl = ttk.Label(
            status_row, textvariable=self.status_detail_var, wraplength=540, justify=tk.LEFT
        )
        self.status_detail_lbl.pack(side=tk.LEFT, padx=(10, 6), fill=tk.X, expand=True)
        status_row.bind(
            "<Configure>",
            lambda e, lbl=self.status_detail_lbl, b=self.status_badge_lbl: lbl.configure(
                wraplength=max(200, e.width - b.winfo_reqwidth() - 36)
            ),
        )
        self.archive_rebuild_btn.pack(side=tk.RIGHT)
        self.archive_rebuild_btn.pack_forget()

        self.loc_warn_lbl = ttk.Label(
            self.diag_frame, textvariable=self.loc_warn_var, style="Warn.TLabel", wraplength=760
        )
        self.loc_warn_lbl.pack(anchor=tk.W, pady=(2, 0))
        self.loc_warn_lbl.pack_forget()

        # --- F3 + F5 预设管理与防误触批量快捷工具栏 ---
        self.tools_frame = ttk.LabelFrame(
            self.outer, text="预设管理与批量快捷工具", padding=(6, 4)
        )
        self.tools_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        # 第 1 行：预设操作（Combobox 弹性伸展，右侧按钮永不被挤出）
        preset_row = ttk.Frame(self.tools_frame)
        preset_row.pack(fill=tk.X)
        ttk.Label(preset_row, text="预设方案:").pack(side=tk.LEFT)
        export_btn = ttk.Button(preset_row, text="导出...", command=self._on_export_preset)
        export_btn.pack(side=tk.RIGHT)
        import_btn = ttk.Button(preset_row, text="导入...", command=self._on_import_preset)
        import_btn.pack(side=tk.RIGHT, padx=(0, 4))
        save_btn = ttk.Button(preset_row, text="保存预设...", command=self._on_save_preset)
        save_btn.pack(side=tk.RIGHT, padx=(0, 4))
        load_btn = ttk.Button(preset_row, text="加载预设", command=self._on_load_selected_preset)
        load_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self.preset_combo = ttk.Combobox(
            preset_row,
            textvariable=self.preset_var,
            state="readonly",
            width=22,
        )
        self.preset_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))

        # 第 2 行：高频正向批量按钮 + 撤销 + 更多批量下拉菜单（反向/低频收拢）
        batch_row = ttk.Frame(self.tools_frame)
        batch_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(batch_row, text="常用批量:").pack(side=tk.LEFT, padx=(0, 3))
        for text, op in (
            ("时间×0.5", "time_half"),
            ("矿物×0.5", "minerals_half"),
            ("零件×0.5", "gears_half"),
            ("人口×2", "pop_x2"),
            ("血量×2", "hp_x2"),
            ("伤害×2", "dmg_x2"),
            ("移速×1.5", "speed_x1_5"),
        ):
            ttk.Button(
                batch_row,
                text=text,
                width=8,
                command=lambda o=op: self._run_batch_operation(o),
            ).pack(side=tk.LEFT, padx=(0, 2))

        self.undo_batch_btn = ttk.Button(
            batch_row,
            text="撤销",
            width=6,
            command=self._on_undo_batch,
            state=tk.DISABLED,
        )
        self.undo_batch_btn.pack(side=tk.RIGHT, padx=(3, 0))

        more_btn = ttk.Menubutton(batch_row, text="更多批量", width=8)
        more_menu = tk.Menu(more_btn, tearoff=False)
        more_menu.add_command(
            label="建造/研发/冷却时间 ×2（加长）",
            command=lambda: self._run_batch_operation("time_x2"),
        )
        more_menu.add_command(
            label="矿物消耗 ×2（增耗）",
            command=lambda: self._run_batch_operation("minerals_x2"),
        )
        more_menu.add_command(
            label="人口提供上限 ×5",
            command=lambda: self._run_batch_operation("pop_x5"),
        )
        more_menu.add_separator()
        more_menu.add_command(
            label="最大血量 ×0.5（削弱敌方常用）",
            command=lambda: self._run_batch_operation("hp_half"),
        )
        more_menu.add_command(
            label="武器伤害 ×0.5（削弱敌方常用）",
            command=lambda: self._run_batch_operation("dmg_half"),
        )
        more_menu.add_command(
            label="移动速度 ×0.5（降速）",
            command=lambda: self._run_batch_operation("speed_half"),
        )
        more_menu.add_command(
            label="武器攻击冷却 ×0.5（攻速翻倍）",
            command=lambda: self._run_batch_operation("weapon_cd_half"),
        )
        more_menu.add_separator()
        more_menu.add_command(
            label="解除建造数量限制 (maxCount → 0)",
            command=lambda: self._run_batch_operation("unlock_max_count"),
        )
        more_menu.add_command(
            label="一键修改全部 7 个标准矿脉储量...",
            command=self._on_batch_all_minerals_dialog,
        )
        more_menu.add_separator()
        more_menu.add_command(
            label="重置当前筛选条目为原版（含战斗组件）",
            command=lambda: self._run_batch_operation("reset_filtered"),
        )
        more_btn["menu"] = more_menu
        more_btn.pack(side=tk.RIGHT)

        # 第 3 行：独立的作用域提示行（永不截断）
        scope_row = ttk.Frame(self.tools_frame)
        scope_row.pack(fill=tk.X, pady=(3, 0))
        self.scope_lbl = ttk.Label(
            scope_row,
            textvariable=self.batch_scope_var,
            style="Scope.TLabel",
            wraplength=540,
            justify=tk.LEFT,
        )
        self.scope_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scope_row.bind(
            "<Configure>",
            lambda e, lbl=self.scope_lbl: self._safe_set_wrap(lbl, max(260, e.width - 16)),
        )

        # 第 4 行（按需弹出）：F5 敌方操作醒目警示横幅
        self.enemy_warn_frame = tk.Frame(
            self.tools_frame,
            bg="#fff1e6",
            highlightbackground="#e05300",
            highlightthickness=1,
            padx=6,
            pady=3,
        )
        self.enemy_back_btn = ttk.Button(
            self.enemy_warn_frame,
            text="切回我方（帝国）",
            command=self._reset_filter_to_player_empire,
        )
        self.enemy_back_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.enemy_warn_label = tk.Label(
            self.enemy_warn_frame,
            textvariable=self.enemy_warning_var,
            bg="#fff1e6",
            fg="#b83200",
            font=("Microsoft YaHei UI", 9, "bold"),
            anchor="w",
            justify=tk.LEFT,
            wraplength=540,
        )
        self.enemy_warn_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.enemy_warn_frame.bind(
            "<Configure>",
            lambda e, lbl=self.enemy_warn_label, b=self.enemy_back_btn: self._safe_set_wrap(
                lbl, max(200, e.width - b.winfo_reqwidth() - 28)
            ),
        )
        self.enemy_warn_frame.pack_forget()

        # --- F4 先于主工作区打包底部按钮栏，根治任何窗口高度下的底部按钮截断 ---
        self.footer = ttk.Frame(self.outer, padding=(2, 3))
        self.footer.pack(side=tk.BOTTOM, fill=tk.X)

        btn_box = ttk.Frame(self.footer)
        btn_box.pack(side=tk.RIGHT)
        self.restore_btn = ttk.Button(
            btn_box, text="一键还原原版", command=self._on_restore_vanilla
        )
        self.restore_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.apply_btn = ttk.Button(
            btn_box,
            text="应用修改到游戏",
            style="Primary.TButton",
            command=lambda: self._on_apply_to_game(launch=False),
        )
        self.apply_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.apply_launch_btn = ttk.Button(
            btn_box,
            text="应用并启动游戏",
            style="Primary.TButton",
            command=lambda: self._on_apply_to_game(launch=True),
        )
        self.apply_launch_btn.pack(side=tk.LEFT)

        self.footer_summary_lbl = ttk.Label(
            self.footer,
            textvariable=self.footer_summary_var,
            style="Status.TLabel",
            wraplength=540,
            justify=tk.LEFT,
        )
        self.footer_summary_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.footer.bind(
            "<Configure>",
            lambda e, lbl=self.footer_summary_lbl, b=btn_box: lbl.configure(
                wraplength=max(180, e.width - b.winfo_reqwidth() - 20)
            ),
        )

        # --- F2 + F6 主工作区（最后 pack，弹性吸收全部剩余高宽） ---
        self.paned = ttk.PanedWindow(self.outer, orient=tk.HORIZONTAL)
        self.paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 4))

        left_pane = ttk.Frame(self.paned, padding=(0, 0, 4, 0))
        right_pane = ttk.Frame(self.paned, padding=(4, 0, 0, 0))
        self.paned.add(left_pane, weight=1)
        self.paned.add(right_pane, weight=1)

        # 顶层 5 大分类页签按钮栏（紧凑内边距，适应窗口化）
        tab_bar = ttk.Frame(left_pane)
        tab_bar.pack(fill=tk.X, pady=(0, 4))
        self.tab_buttons: dict[str, tk.Button] = {}
        for script in ALL_TOP_TABS:
            btn = tk.Button(
                tab_bar,
                text=COMPACT_TAB_LABELS[script],
                relief=tk.RAISED,
                bd=1,
                padx=5,
                pady=3,
                command=lambda s=script: self.select_script_tab(s),
            )
            btn.pack(side=tk.LEFT, padx=(0, 3))
            self.tab_buttons[script] = btn

        # F5 全配置页签可用归属筛选条
        filter_bar = ttk.Frame(left_pane)
        filter_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(filter_bar, text="归属:").pack(side=tk.LEFT)
        self.affiliation_choices = [label for _code, label in AFFILIATION_FILTER_OPTIONS]
        self.affiliation_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.affiliation_filter_var,
            values=self.affiliation_choices,
            state="readonly",
            width=13,
        )
        self.affiliation_combo.pack(side=tk.LEFT, padx=(3, 6))
        self.affiliation_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_affiliation_selected())

        ttk.Label(filter_bar, text="搜索:").pack(side=tk.LEFT)
        ttk.Checkbutton(
            filter_bar,
            text="仅已修改",
            variable=self.only_modified_var,
            command=self.refresh_item_list,
        ).pack(side=tk.RIGHT)
        ttk.Button(filter_bar, text="清除", width=4, command=self._on_clear_search).pack(
            side=tk.RIGHT, padx=(2, 6)
        )
        search_entry = ttk.Entry(filter_bar, textvariable=self.search_var, width=10)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 2))
        self.search_var.trace_add("write", lambda *_a: self.refresh_item_list())

        # 左侧列表 Treeview（消歧展示 + 敌方区分着色）
        tree_wrap = ttk.Frame(left_pane)
        tree_wrap.pack(fill=tk.BOTH, expand=True)
        columns = ("display_name", "affiliation", "asset_name", "diff_summary")
        self.tree = ttk.Treeview(
            tree_wrap,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("display_name", text="中文名称")
        self.tree.heading("affiliation", text="实战归属")
        self.tree.heading("asset_name", text="内部资产名 (m_Name)")
        self.tree.heading("diff_summary", text="改动摘要")
        self.tree.column("display_name", width=125, minwidth=70)
        self.tree.column("affiliation", width=80, minwidth=64, anchor=tk.CENTER)
        self.tree.column("asset_name", width=135, minwidth=80)
        self.tree.column("diff_summary", width=165, minwidth=90)

        self.tree.tag_configure("modified", background="#eef5ff", foreground="#004a99")
        self.tree.tag_configure("enemy_unmod", background="#fff7f5", foreground="#7a261d")
        self.tree.tag_configure("enemy_mod", background="#ffe4de", foreground="#b81d00")

        vsb = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # 右侧对象详情卡（随面板宽度自动换行）
        info_box = ttk.LabelFrame(right_pane, text="对象信息", padding=6)
        info_box.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.item_title_lbl = ttk.Label(
            info_box, textvariable=self.item_title_var, style="Title.TLabel", wraplength=420
        )
        self.item_title_lbl.pack(anchor=tk.W, fill=tk.X)
        self.item_meta_lbl = ttk.Label(
            info_box,
            textvariable=self.item_meta_var,
            wraplength=420,
            justify=tk.LEFT,
        )
        self.item_meta_lbl.pack(anchor=tk.W, fill=tk.X, pady=(2, 2))
        self.item_desc_lbl = ttk.Label(
            info_box,
            textvariable=self.item_desc_var,
            wraplength=420,
            justify=tk.LEFT,
            foreground="#444444",
        )
        self.item_desc_lbl.pack(anchor=tk.W, fill=tk.X)
        info_box.bind(
            "<Configure>",
            lambda e: self._update_info_box_wrap(max(220, e.width - 24)),
        )

        # 右侧 4 子页签对比编辑器 (F6)：先 pack 底部单条重置条，再 pack Notebook
        editor_box = ttk.LabelFrame(right_pane, text="参数对比与修改", padding=5)
        editor_box.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        editor_footer = ttk.Frame(editor_box)
        editor_footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        self.reset_item_btn = ttk.Button(
            editor_footer,
            text="单条重置为原版",
            command=self._on_reset_selected_item,
            state=tk.DISABLED,
        )
        self.reset_item_btn.pack(side=tk.RIGHT)
        self.validation_lbl = ttk.Label(
            editor_footer,
            textvariable=self.validation_var,
            style="Error.TLabel",
            wraplength=280,
            justify=tk.LEFT,
        )
        self.validation_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        editor_footer.bind(
            "<Configure>",
            lambda e, lbl=self.validation_lbl, b=self.reset_item_btn: lbl.configure(
                wraplength=max(140, e.width - b.winfo_reqwidth() - 16)
            ),
        )

        self.inspector_notebook = ttk.Notebook(editor_box)
        self.inspector_notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.subtab_base_titles = (
            "经济与建造",
            "生命与护甲",
            "武器火力",
            "机动/视野/后勤",
        )
        for idx, title in enumerate(self.subtab_base_titles):
            tab_container = ttk.Frame(self.inspector_notebook)
            tab_container.rowconfigure(0, weight=1)
            tab_container.columnconfigure(0, weight=1)
            self.inspector_notebook.add(tab_container, text=title)

            canvas = tk.Canvas(
                tab_container,
                highlightthickness=0,
                borderwidth=0,
                width=360,
                height=140,
            )
            sub_vsb = ttk.Scrollbar(tab_container, orient=tk.VERTICAL, command=canvas.yview)
            sub_hsb = ttk.Scrollbar(tab_container, orient=tk.HORIZONTAL, command=canvas.xview)
            inner = ttk.Frame(canvas, padding=(4, 4))
            win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
            canvas.configure(yscrollcommand=sub_vsb.set, xscrollcommand=sub_hsb.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            sub_vsb.grid(row=0, column=1, sticky="ns")
            sub_hsb.grid(row=1, column=0, sticky="ew")

            inner.bind(
                "<Configure>",
                lambda _e, c=canvas, inn=inner, wid=win_id: self._sync_subtab_scrollregion(
                    c, inn, wid
                ),
            )
            canvas.bind(
                "<Configure>",
                lambda e, c=canvas, inn=inner, wid=win_id: self._on_subtab_canvas_configure(
                    c, inn, wid, e.width
                ),
            )
            self._subtab_scroll_frames[idx] = (canvas, inner, win_id)

        # 全局滚轮事件路由到悬停所在的子页签 Canvas
        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
        self._update_tab_button_styles()

    def _update_info_box_wrap(self, wrap_w: int) -> None:
        self.item_title_lbl.configure(wraplength=wrap_w)
        self.item_meta_lbl.configure(wraplength=wrap_w)
        self.item_desc_lbl.configure(wraplength=wrap_w)

    def _safe_set_wrap(self, lbl: tk.Misc, width: int) -> None:
        if lbl.winfo_exists():
            lbl.configure(wraplength=width)

    def _bind_dynamic_wrap(self, container: tk.Misc, lbl: tk.Misc, reserve: int = 24, min_w: int = 200) -> None:
        container.bind(
            "<Configure>",
            lambda e, l=lbl, r=reserve, m=min_w: self._safe_set_wrap(l, max(m, e.width - r)),
            add="+",
        )

    def _sync_subtab_scrollregion(
        self, canvas: tk.Canvas, inner: ttk.Frame, win_id: int
    ) -> None:
        if not canvas.winfo_exists() or not inner.winfo_exists():
            return
        cw = canvas.winfo_width()
        req_w = inner.winfo_reqwidth()
        if cw > 10:
            canvas.itemconfigure(win_id, width=max(cw, req_w))
        canvas.configure(scrollregion=canvas.bbox("all"))
        self._refresh_subtab_wrap_widths(inner, max(200, cw - 24 if cw > 24 else 320))

    def _on_subtab_canvas_configure(
        self, canvas: tk.Canvas, inner: ttk.Frame, win_id: int, width: int
    ) -> None:
        if not canvas.winfo_exists() or not inner.winfo_exists():
            return
        req_w = inner.winfo_reqwidth()
        canvas.itemconfigure(win_id, width=max(width, req_w))
        canvas.configure(scrollregion=canvas.bbox("all"))
        self._refresh_subtab_wrap_widths(inner, max(200, width - 24))

    def _refresh_subtab_wrap_widths(self, inner: ttk.Frame, wrap_w: int) -> None:
        for lbl in getattr(inner, "_wrap_labels", ()):
            if lbl.winfo_exists():
                lbl.configure(wraplength=wrap_w)

    def _on_global_mousewheel(self, event: tk.Event[Any]) -> None:
        widget = event.widget
        if widget is None:
            return
        # 避免拦截 Combobox 下拉弹出列表或 Treeview 的滚轮
        if isinstance(widget, ttk.Treeview) or str(widget.winfo_class()) in ("TCombobox", "Listbox"):
            return
        canvas_by_widget = {c: c for c, _i, _w in self._subtab_scroll_frames.values()}
        cur: Any = widget
        while cur is not None:
            if cur in canvas_by_widget:
                c = canvas_by_widget[cur]
                if c.winfo_viewable():
                    bbox = c.bbox("all")
                    if bbox and (bbox[3] - bbox[1]) > c.winfo_height():
                        c.yview_scroll(int(-1 * (event.delta / 120)), "units")
                return
            parent_name = cur.winfo_parent()
            if not parent_name:
                break
            try:
                cur = cur.nametowidget(parent_name)
            except KeyError:
                break

    def _get_current_affiliation_code(self) -> str:
        return AFFILIATION_LABEL_TO_CODE.get(
            self.affiliation_filter_var.get(), DEFAULT_AFFILIATION_FILTER
        )

    def set_affiliation_filter_code(self, filter_code: str) -> None:
        """以编程方式切换顶部实战归属筛选编码并刷新列表。"""
        label = AFFILIATION_CODE_TO_LABEL[filter_code]
        if self.current_tab_script == WORLD_TAB_KEY:
            self._saved_config_affiliation = label
            return
        self._saved_config_affiliation = label
        self.affiliation_filter_var.set(label)
        self.refresh_item_list()

    def _reset_filter_to_player_empire(self) -> None:
        self.set_affiliation_filter_code(DEFAULT_AFFILIATION_FILTER)

    def _on_affiliation_selected(self) -> None:
        if self.current_tab_script != WORLD_TAB_KEY:
            self._saved_config_affiliation = self.affiliation_filter_var.get()
        self.refresh_item_list()

    def _update_tab_button_styles(self) -> None:
        counts = {s: 0 for s in ALL_TOP_TABS}
        if self.snapshot is not None:
            for item in self.snapshot.vanilla_bundle.items:
                counts[item.script] = counts.get(item.script, 0) + 1
            counts[WORLD_TAB_KEY] = len(self.snapshot.vanilla_bundle.world_items)

        for script, btn in self.tab_buttons.items():
            label = f"{COMPACT_TAB_LABELS[script]} ({counts[script]})"
            if script == self.current_tab_script:
                btn.configure(
                    text=label,
                    relief=tk.SUNKEN,
                    bg="#dcebff",
                    fg="#003e80",
                    font=("Microsoft YaHei UI", 9, "bold"),
                )
            else:
                btn.configure(
                    text=label,
                    relief=tk.RAISED,
                    bg="#f0f0f0",
                    fg="#222222",
                    font=("Microsoft YaHei UI", 9),
                )

    def refresh_preset_dropdown(self) -> None:
        """扫描 presets/*.json 并更新下拉列表。"""
        self._preset_choices.clear()
        labels: list[str] = []
        default_label: str | None = None

        for p in list_preset_files(self.presets_dir):
            if p.name == "limited_mod_1022.json":
                label = "有限修改MOD (10月22日原版预设) [limited_mod_1022.json]"
                default_label = label
            else:
                label = f"{p.stem} [{p.name}]"
            self._preset_choices[label] = p
            labels.append(label)

        self._preset_choices[BUILTIN_VANILLA_LABEL] = None
        labels.append(BUILTIN_VANILLA_LABEL)
        self.preset_combo.configure(values=labels)
        if default_label:
            self.preset_var.set(default_label)
        elif labels:
            self.preset_var.set(labels[0])

    def refresh_workspace(self) -> None:
        """只读扫描当前游戏目录，更新三层基准、当前修改和状态诊断。"""
        self.data_dir = Path(self.game_dir_var.get().strip() or self.data_dir)
        self.batch_undo_stack.clear()
        self.undo_batch_btn.configure(state=tk.DISABLED)
        self.validation_var.set("")

        try:
            snapshot = load_workspace_snapshot(self.data_dir)
        except Exception as exc:
            self.snapshot = None
            self.overrides = {}
            self.component_overrides = {}
            self.world_overrides = {}
            self.selected_key = None
            self.status_badge_var.set("🔴 无法加载游戏目录")
            self.status_badge_lbl.configure(foreground="#c42b1c")
            self.status_detail_var.set(str(exc))
            self.archive_rebuild_btn.pack_forget()
            self.loc_warn_lbl.pack_forget()
            self._update_tab_button_styles()
            self.refresh_item_list()
            self._update_footer_summary()
            return

        self.snapshot = snapshot
        self.overrides = clone_overrides(snapshot.initial_overrides)
        self.component_overrides = clone_component_overrides(snapshot.initial_component_overrides)
        self.world_overrides = clone_world_overrides(snapshot.initial_world_overrides)
        self._apply_status_banner(snapshot.status)

        warn = snapshot.vanilla_bundle.localization_warning
        if warn:
            self.loc_warn_var.set(f"提示：{warn}")
            self.loc_warn_lbl.pack(anchor=tk.W, pady=(2, 0))
        else:
            self.loc_warn_var.set("")
            self.loc_warn_lbl.pack_forget()

        self._update_tab_button_styles()
        self.select_script_tab(self.current_tab_script)
        self._update_footer_summary()

    def _apply_status_banner(self, status: Any) -> None:
        self.status_badge_var.set(status.label)
        self.status_detail_var.set(status.detail)
        color_map = {
            "verified_vanilla_d351": "#0f7b0f",
            "verified_custom_baseline": "#0f7b0f",
            "limited_mod_1022": "#005fb8",
            "custom_mod": "#6b21a8",
            "unknown_baseline": "#b26b00",
            "external_update_conflict": "#b26b00",
            "invalid_dir": "#c42b1c",
        }
        self.status_badge_lbl.configure(foreground=color_map.get(status.code, "#222222"))
        if status.code == "external_update_conflict":
            self.archive_rebuild_btn.pack(side=tk.RIGHT)
        else:
            self.archive_rebuild_btn.pack_forget()

    def select_script_tab(self, script: str) -> None:
        """切换顶层 5 大分类页签，并在 4 配置页签保持归属筛选，地图资源页签锁定中立。"""
        self.commit_current_field_edits()
        prev_tab = self.current_tab_script
        self.current_tab_script = script
        self._update_tab_button_styles()

        if script == WORLD_TAB_KEY:
            if prev_tab != WORLD_TAB_KEY:
                self._saved_config_affiliation = self.affiliation_filter_var.get()
            self.affiliation_filter_var.set(AFFILIATION_CODE_TO_LABEL["neutral"])
            self.affiliation_combo.configure(state=tk.DISABLED)
        else:
            if prev_tab == WORLD_TAB_KEY:
                self.affiliation_filter_var.set(self._saved_config_affiliation)
            self.affiliation_combo.configure(state="readonly")
        self.refresh_item_list()

    def _get_config_component_override_count(self, key: ConfigKey) -> int:
        if self.snapshot is None:
            return 0
        item = self.snapshot.vanilla_bundle.by_key.get(key)
        if item is None:
            return 0
        cnt = 0
        for comp in item.components:
            cnt += len(self.component_overrides.get(comp.key, {}))
        return cnt

    def _is_config_modified(self, key: ConfigKey) -> bool:
        return bool(self.overrides.get(key)) or self._get_config_component_override_count(key) > 0

    def _encode_iid(self, key: ConfigKey | WorldKey) -> str:
        if len(key) == 2:
            return f"cfg::{key[0]}::{key[1]}"
        return f"world::{key[1]}::{key[2]}::{key[3]}"

    def _decode_iid(self, iid: str) -> ConfigKey | WorldKey:
        parts = iid.split("::")
        if parts[0] == "cfg":
            return (parts[1], parts[2])
        return ("world", parts[1], parts[2], int(parts[3]))

    def refresh_item_list(self) -> None:
        """根据页签、实战归属、搜索词与「仅显示已修改项」刷新左侧列表与作用域警示。"""
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        self.filtered_keys.clear()

        if self.snapshot is None:
            self._update_scope_and_enemy_warning(0)
            self._render_inspector(None)
            return

        aff_code = self._get_current_affiliation_code()
        query = self.search_var.get().strip().lower()
        only_mod = self.only_modified_var.get()
        enemy_in_list = 0

        if self.current_tab_script == WORLD_TAB_KEY:
            for witem in self.snapshot.vanilla_bundle.world_items:
                wkey = witem.key
                w_ov = self.world_overrides.get(wkey, {})
                if only_mod and not w_ov:
                    continue
                if query:
                    haystack = f"{witem.display_name} {witem.go_name} {witem.comp_class}".lower()
                    if query not in haystack:
                        continue
                self.filtered_keys.append(wkey)
                summary = self._build_world_diff_summary(witem, w_ov)
                iid = self._encode_iid(wkey)
                tags = ("modified",) if w_ov else ()
                self.tree.insert(
                    "",
                    tk.END,
                    iid=iid,
                    values=(witem.display_name, witem.affiliation_name, witem.go_name, summary),
                    tags=tags,
                )
        else:
            candidates = [
                item
                for item in self.snapshot.vanilla_bundle.items
                if item.script == self.current_tab_script
            ]
            candidates.sort(
                key=lambda it: (
                    1 if it.display_name.startswith("[无译名]") else 0,
                    it.display_name,
                    it.asset_name,
                )
            )
            for item in candidates:
                if not matches_affiliation_filter(item.affiliation, aff_code):
                    continue
                key = (item.script, item.asset_name)
                is_mod = self._is_config_modified(key)
                if only_mod and not is_mod:
                    continue
                if query:
                    haystack = f"{item.display_name} {item.asset_name} {item.name_key}".lower()
                    if query not in haystack:
                        continue

                self.filtered_keys.append(key)
                is_enemy = is_enemy_affiliation(item.affiliation)
                if is_enemy:
                    enemy_in_list += 1
                summary = self._build_config_diff_summary(item)
                iid = self._encode_iid(key)
                if is_enemy:
                    tags: tuple[str, ...] = ("enemy_mod",) if is_mod else ("enemy_unmod",)
                else:
                    tags = ("modified",) if is_mod else ()
                self.tree.insert(
                    "",
                    tk.END,
                    iid=iid,
                    values=(item.display_name, item.affiliation_name, item.asset_name, summary),
                    tags=tags,
                )

        self._update_scope_and_enemy_warning(enemy_in_list)

        target_key = (
            self.selected_key
            if self.selected_key in self.filtered_keys
            else (self.filtered_keys[0] if self.filtered_keys else None)
        )
        self._suppress_tree_select = True
        try:
            if target_key is not None:
                iid = self._encode_iid(target_key)
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self.tree.see(iid)
        finally:
            self._suppress_tree_select = False

        self.selected_key = target_key
        self._render_inspector(target_key)
        self._update_footer_summary()

    def _update_scope_and_enemy_warning(self, enemy_count: int) -> None:
        tab_label = TOP_TAB_LABELS[self.current_tab_script]
        aff_label = self.affiliation_filter_var.get()
        self.batch_scope_var.set(
            f"当前批量作用范围：【{aff_label} · {tab_label}】共 {len(self.filtered_keys)} 项"
        )
        if enemy_count > 0:
            self.enemy_warning_var.set(
                f"⚠️ 当前范围包含敌方对象 ({enemy_count} 项)，执行批量修改将同时影响敌方！"
            )
            if not self.enemy_warning_visible:
                self.enemy_warn_frame.pack(fill=tk.X, pady=(5, 0))
                self.enemy_warning_visible = True
        else:
            self.enemy_warning_var.set("")
            if self.enemy_warning_visible:
                self.enemy_warn_frame.pack_forget()
                self.enemy_warning_visible = False

    def _build_config_diff_summary(self, item: Any) -> str:
        key = (item.script, item.asset_name)
        item_ov = self.overrides.get(key, {})
        parts: list[str] = []
        for fname in sorted(item_ov.keys()):
            spec = FIELD_META[fname]
            old_s = format_display_value_by_spec(spec, item.fields[fname].value)
            new_s = format_display_value_by_spec(spec, item_ov[fname])
            parts.append(f"{spec.label} {old_s}→{new_s}")

        comp_cnt = 0
        comp_labels: list[str] = []
        for comp in item.components:
            cov = self.component_overrides.get(comp.key, {})
            if not cov:
                continue
            comp_cnt += len(cov)
            if comp.comp_class == "HP" and "maxHp" in cov:
                old_hp = int(comp.fields["maxHp"].value)
                new_hp = int(cov["maxHp"])
                comp_labels.append(f"血量 {old_hp}→{new_hp}")
            elif comp.comp_class in ATTACK_COMPONENT_CLASSES:
                comp_labels.append(f"武器({comp.comp_class.removeprefix('AutoAttack_')}) {len(cov)}项")
            elif comp.comp_class in MOVE_COMPONENT_CLASSES and "clearSpeed" in cov:
                comp_labels.append(f"移速 {comp.fields['clearSpeed'].value:g}→{cov['clearSpeed']:g}")
            else:
                comp_labels.append(f"{comp.comp_class} {len(cov)}项")

        if comp_labels:
            if len(comp_labels) <= 2:
                parts.extend(comp_labels)
            else:
                parts.append(f"战斗/组件共 {comp_cnt} 项改动")
        return "; ".join(parts) if parts else "原版未改"

    def _build_world_diff_summary(self, witem: Any, w_ov: dict[str, int | float]) -> str:
        if not w_ov:
            return "原版未改"
        parts: list[str] = []
        for fname in sorted(w_ov.keys()):
            spec = get_component_field_spec(witem.comp_class, fname)
            old_s = format_display_value_by_spec(spec, witem.fields[fname].value)
            new_s = format_display_value_by_spec(spec, w_ov[fname])
            parts.append(f"{spec.label} {old_s}→{new_s}")
        return "; ".join(parts)

    def _on_tree_select(self, _event: Any) -> None:
        if self._suppress_tree_select:
            return
        sel = self.tree.selection()
        if not sel:
            return
        next_key = self._decode_iid(sel[0])
        if next_key == self.selected_key:
            return
        self.commit_current_field_edits()
        self.selected_key = next_key
        self._render_inspector(next_key)

    def _clear_all_subtabs(self) -> None:
        self._field_editors.clear()
        for idx, (_canvas, inner, _wid) in self._subtab_scroll_frames.items():
            setattr(inner, "_wrap_labels", [])
            for child in inner.winfo_children():
                child.destroy()
            self.inspector_notebook.tab(idx, text=self.subtab_base_titles[idx])

    def _update_subtab_tab_badges(self, key: ConfigKey | WorldKey | None) -> None:
        if key is None or self.snapshot is None:
            for idx, title in enumerate(self.subtab_base_titles):
                self.inspector_notebook.tab(idx, text=title)
            return

        if len(key) == 4:
            w_mod = bool(self.world_overrides.get(key))
            self.inspector_notebook.tab(0, text=("★ 经济与建造" if w_mod else "经济与建造"))
            for idx in (1, 2, 3):
                self.inspector_notebook.tab(idx, text=self.subtab_base_titles[idx])
            return

        item = self.snapshot.vanilla_bundle.by_key.get(key)
        if item is None:
            return
        econ_mod = bool(self.overrides.get(key))
        hp_mod = any(
            bool(self.component_overrides.get(c.key))
            for c in item.components
            if c.comp_class in ("HP", "Regeneration")
        )
        wpn_mod = any(
            bool(self.component_overrides.get(c.key))
            for c in item.components
            if c.comp_class in ATTACK_COMPONENT_CLASSES
        )
        other_mod = any(
            bool(self.component_overrides.get(c.key))
            for c in item.components
            if c.comp_class not in ("HP", "Regeneration", *ATTACK_COMPONENT_CLASSES)
        )
        flags = (econ_mod, hp_mod, wpn_mod, other_mod)
        for idx, (title, is_mod) in enumerate(zip(self.subtab_base_titles, flags)):
            self.inspector_notebook.tab(idx, text=(f"★ {title}" if is_mod else title))

    def _render_inspector(self, key: ConfigKey | WorldKey | None) -> None:
        self._clear_all_subtabs()
        self.validation_var.set("")

        if key is None or self.snapshot is None:
            self.item_title_var.set("未选择对象")
            self.item_meta_var.set("请从左侧列表选择任意建筑、单位、科技、战术或地图资源点")
            self.item_desc_var.set("")
            self.reset_item_btn.configure(state=tk.DISABLED)
            return

        # 分支 A：地图资源点 (WorldItem)
        if len(key) == 4:
            witem = self.snapshot.vanilla_bundle.world_by_key.get(key)
            if witem is None:
                self.reset_item_btn.configure(state=tk.DISABLED)
                return
            w_ov = self.world_overrides.get(key, {})
            mod_mark = "  [已修改]" if w_ov else ""
            self.item_title_var.set(f"{witem.display_name}{mod_mark}")
            self.item_meta_var.set(
                f"组件类: {witem.comp_class}  |  归属: {witem.affiliation_name}  |  "
                f"GameObject: {witem.go_name}  |  出现序号: #{witem.occ_index + 1}"
            )
            self.item_desc_var.set(
                "说明: 地图场景中放置的公共矿脉或独立占领油井资源点（7 个标准 Mineral + 2 个独立 OilPump）。"
            )
            self.reset_item_btn.configure(state=tk.NORMAL if w_ov else tk.DISABLED)

            econ_parent = self._subtab_scroll_frames[0][1]
            box = ttk.LabelFrame(econ_parent, text=f"{witem.comp_class} 资源参数", padding=6)
            box.pack(fill=tk.X, pady=(0, 6))
            self._configure_param_grid(box)
            for r_idx, fname in enumerate(witem.fields.keys(), start=1):
                self._build_field_row(
                    parent=box,
                    row_idx=r_idx,
                    layer="world",
                    target_key=key,
                    comp_class=witem.comp_class,
                    fname=fname,
                    vanilla_val=witem.fields[fname].value,
                )
            if witem.comp_class == "Mineral":
                quick_bar = ttk.Frame(econ_parent)
                quick_bar.pack(fill=tk.X, pady=(4, 0))
                ttk.Button(
                    quick_bar,
                    text="一键修改全部 7 个标准矿脉储量...",
                    command=self._on_batch_all_minerals_dialog,
                ).pack(side=tk.LEFT)

            for idx, msg in (
                (1, "地图资源点不包含生命/护甲组件，请查看「经济与建造」页签。"),
                (2, "地图资源点不包含武器组件，请查看「经济与建造」页签。"),
                (3, "地图资源点参数位于「经济与建造」页签。"),
            ):
                p_sub = self._subtab_scroll_frames[idx][1]
                lbl = ttk.Label(
                    p_sub, text=msg, foreground="#666666", wraplength=320, justify=tk.LEFT
                )
                lbl.pack(anchor=tk.W, fill=tk.X, pady=12, padx=6)
                self._register_subtab_wrap_label(p_sub, lbl)

            self._update_subtab_tab_badges(key)
            return

        # 分支 B：配置对象 (ConfigItem + Prefab 组件)
        item = self.snapshot.vanilla_bundle.by_key.get(key)
        if item is None:
            self.reset_item_btn.configure(state=tk.DISABLED)
            return

        is_mod = self._is_config_modified(key)
        mod_mark = "  [已修改]" if is_mod else ""
        self.item_title_var.set(f"{item.display_name}{mod_mark}")
        prefab_txt = (
            f"已关联 {len(item.components)} 个组件"
            if item.main_prefab_pid != 0
            else "无战斗 Prefab (mainPrefab=0)"
        )
        self.item_meta_var.set(
            f"脚本: {item.script}  |  实战归属: {item.affiliation_name} (原版faction={item.faction_name})  |  "
            f"m_Name: {item.asset_name}  |  {prefab_txt}"
        )
        self.item_desc_var.set(
            f"说明: {item.display_desc}" if item.display_desc else "说明: （无描述文本）"
        )
        self.reset_item_btn.configure(state=tk.NORMAL if is_mod else tk.DISABLED)

        self._render_config_economy_subtab(self._subtab_scroll_frames[0][1], item)
        self._render_hp_subtab(self._subtab_scroll_frames[1][1], item)
        self._render_weapon_subtab(self._subtab_scroll_frames[2][1], item)
        self._render_mobility_logistics_subtab(self._subtab_scroll_frames[3][1], item)
        self._update_subtab_tab_badges(key)

    def _configure_param_grid(self, frame: ttk.Frame) -> None:
        """统一配置参数分组内部 4 列网格并渲染对齐列头（第 1 行起写数据行）。"""
        frame.columnconfigure(0, weight=1, minsize=120)
        frame.columnconfigure(1, weight=0, minsize=62)
        frame.columnconfigure(2, weight=0, minsize=92)
        frame.columnconfigure(3, weight=0, minsize=50)

        hdr_font = ("Microsoft YaHei UI", 9, "bold")
        ttk.Label(frame, text="参数名称", font=hdr_font).grid(
            row=0, column=0, sticky=tk.W, pady=(0, 3)
        )
        ttk.Label(frame, text="原版值", width=7, font=hdr_font).grid(
            row=0, column=1, sticky=tk.W, padx=(4, 4), pady=(0, 3)
        )
        ttk.Label(frame, text="当前修改值", width=11, font=hdr_font).grid(
            row=0, column=2, sticky=tk.W, padx=(4, 4), pady=(0, 3)
        )
        ttk.Label(frame, text="操作", width=5, font=hdr_font).grid(
            row=0, column=3, sticky=tk.E, pady=(0, 3)
        )

    def _compact_weapon_label(self, idx: int, comp: ComponentItem) -> str:
        short_cls = comp.comp_class.removeprefix("AutoAttack_")
        tail = comp.go_rel_path.split("/")[-1] if "/" in comp.go_rel_path else comp.go_rel_path
        suffix = f" #{comp.occ_index + 1}" if comp.occ_index > 0 else ""
        return f"#{idx + 1} [{short_cls}] {tail}{suffix}"

    def _render_config_economy_subtab(self, parent: ttk.Frame, item: Any) -> None:
        key = (item.script, item.asset_name)
        primary_frame = ttk.LabelFrame(parent, text="主要经济/建造参数", padding=6)
        primary_frame.pack(fill=tk.X, pady=(0, 6))
        self._configure_param_grid(primary_frame)
        for row_idx, fname in enumerate(PRIMARY_FIELDS_BY_SCRIPT[item.script], start=1):
            self._build_field_row(
                parent=primary_frame,
                row_idx=row_idx,
                layer="config",
                target_key=key,
                comp_class=None,
                fname=fname,
                vanilla_val=item.fields[fname].value,
            )

        adv_fields = ADVANCED_FIELDS_BY_SCRIPT[item.script]
        if adv_fields:
            arrow = "▼" if self.advanced_expanded_var.get() else "▶"
            toggle_btn = ttk.Button(
                parent,
                text=f"{arrow} 展开 PriceResources 附带字段（原版为 0）",
                command=self._toggle_advanced_fields,
            )
            toggle_btn.pack(fill=tk.X, pady=(2, 4))
            if self.advanced_expanded_var.get():
                adv_frame = ttk.LabelFrame(
                    parent, text="高级 / 全部 PriceResources 字段", padding=6
                )
                adv_frame.pack(fill=tk.X)
                self._configure_param_grid(adv_frame)
                for row_idx, fname in enumerate(adv_fields, start=1):
                    self._build_field_row(
                        parent=adv_frame,
                        row_idx=row_idx,
                        layer="config",
                        target_key=key,
                        comp_class=None,
                        fname=fname,
                        vanilla_val=item.fields[fname].value,
                    )

    def _register_subtab_wrap_label(self, inner: ttk.Frame, lbl: ttk.Label) -> None:
        lst = getattr(inner, "_wrap_labels", None)
        if lst is None:
            lst = []
            setattr(inner, "_wrap_labels", lst)
        lst.append(lbl)

    def _render_no_prefab_notice(self, parent: ttk.Frame, item: Any, module_desc: str) -> None:
        if item.script not in ("BuildConfig", "UnitConfig"):
            msg = f"当前对象属于「{TOP_TAB_LABELS[item.script]}」，不包含 {module_desc} 组件。"
        elif item.main_prefab_pid == 0:
            msg = f"该对象未关联战斗 Prefab (mainPrefab=0)，无 {module_desc} 参数。"
        else:
            msg = f"该对象在 Prefab 组件树中未挂载 {module_desc} 组件。"
        lbl = ttk.Label(parent, text=msg, foreground="#666666", wraplength=320, justify=tk.LEFT)
        lbl.pack(anchor=tk.W, fill=tk.X, pady=12, padx=6)
        self._register_subtab_wrap_label(parent, lbl)

    def _render_hp_subtab(self, parent: ttk.Frame, item: Any) -> None:
        key: ConfigKey = (item.script, item.asset_name)
        hp_comps = [c for c in item.components if c.comp_class == "HP"]
        regen_comps = [c for c in item.components if c.comp_class == "Regeneration"]
        if not hp_comps and not regen_comps:
            self._render_no_prefab_notice(parent, item, "生命与护甲 (HP / Regeneration)")
            return

        if hp_comps:
            idx = self._selected_hp_idx_by_config.get(key, 0)
            if idx >= len(hp_comps):
                idx = 0
                self._selected_hp_idx_by_config[key] = 0
            hp_comp = hp_comps[idx]

            if len(hp_comps) > 1:
                sel_row = ttk.Frame(parent)
                sel_row.pack(fill=tk.X, pady=(0, 4))
                ttk.Label(sel_row, text=f"HP 子体 ({len(hp_comps)}):").pack(side=tk.LEFT)
                labels = [
                    f"#{i + 1} {c.go_rel_path.split('/')[-1]} ({c.go_rel_path})"
                    for i, c in enumerate(hp_comps)
                ]
                hp_var = tk.StringVar(master=self.root, value=labels[idx])
                combo = ttk.Combobox(
                    sel_row, textvariable=hp_var, values=labels, state="readonly", width=20
                )
                combo.pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)
                combo.bind(
                    "<<ComboboxSelected>>",
                    lambda _e, k=key, cbox=combo: self._on_switch_hp_subcomponent(k, cbox.current()),
                )

            hp_type_name = hp_comp.readonly_meta.get("hpTypeName", "未知")
            hp_hint_lbl = ttk.Label(
                parent,
                text=(
                    f"只读护甲类型: {hp_type_name}  |  路径: {hp_comp.go_rel_path}\n"
                    "提示：修改「最大血量」将自动双写联动 curHp；抗性支持原版负数弱点 ([-2.0, 1.0])。"
                ),
                foreground="#444444",
                wraplength=340,
                justify=tk.LEFT,
            )
            hp_hint_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
            self._register_subtab_wrap_label(parent, hp_hint_lbl)

            hp_frame = ttk.LabelFrame(parent, text="HP 生命与抗性参数", padding=6)
            hp_frame.pack(fill=tk.X, pady=(0, 6))
            self._configure_param_grid(hp_frame)
            for r_idx, fname in enumerate(hp_comp.fields.keys(), start=1):
                self._build_field_row(
                    parent=hp_frame,
                    row_idx=r_idx,
                    layer="component",
                    target_key=hp_comp.key,
                    comp_class=hp_comp.comp_class,
                    fname=fname,
                    vanilla_val=hp_comp.fields[fname].value,
                )

        for r_comp in regen_comps:
            regen_frame = ttk.LabelFrame(
                parent, text=f"被动回血 ({r_comp.go_rel_path.split('/')[-1]})", padding=6
            )
            regen_frame.pack(fill=tk.X, pady=(0, 6))
            self._configure_param_grid(regen_frame)
            for r_idx, fname in enumerate(r_comp.fields.keys(), start=1):
                self._build_field_row(
                    parent=regen_frame,
                    row_idx=r_idx,
                    layer="component",
                    target_key=r_comp.key,
                    comp_class=r_comp.comp_class,
                    fname=fname,
                    vanilla_val=r_comp.fields[fname].value,
                )

    def _on_switch_hp_subcomponent(self, key: ConfigKey, new_idx: int) -> None:
        if new_idx < 0:
            return
        self.commit_current_field_edits()
        self._selected_hp_idx_by_config[key] = new_idx
        self._render_inspector(key)

    def _format_weapon_range_text(self, wpn: ComponentItem) -> str:
        w_ov = self.component_overrides.get(wpn.key, {})
        cur_r = float(w_ov.get("range", wpn.fields["range"].value))
        cur_a = float(w_ov.get("addRange", wpn.fields["addRange"].value))
        return (
            f"有效总射程 ≈ 基础 ({cur_r:g}) + 增量 ({cur_a:+g}) = {cur_r + cur_a:g}\n"
            f"挂载路径: {wpn.go_rel_path}  (类: {wpn.comp_class})"
        )

    def _render_weapon_subtab(self, parent: ttk.Frame, item: Any) -> None:
        key: ConfigKey = (item.script, item.asset_name)
        weapons = [c for c in item.components if c.comp_class in ATTACK_COMPONENT_CLASSES]
        if not weapons:
            self._render_no_prefab_notice(parent, item, "武器火力 (AttackComponent)")
            return

        w_idx = self._selected_weapon_idx_by_config.get(key, 0)
        if w_idx >= len(weapons):
            w_idx = 0
            self._selected_weapon_idx_by_config[key] = 0
        wpn = weapons[w_idx]

        # 第 1 行：紧凑武器选择器
        sel_row = ttk.Frame(parent)
        sel_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(sel_row, text=f"武器 ({len(weapons)} 门):").pack(side=tk.LEFT)
        w_labels = [self._compact_weapon_label(i, w) for i, w in enumerate(weapons)]
        w_var = tk.StringVar(master=self.root, value=w_labels[w_idx])
        combo = ttk.Combobox(
            sel_row, textvariable=w_var, values=w_labels, state="readonly", width=20
        )
        combo.pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _e, k=key, cbox=combo: self._on_switch_weapon(k, cbox.current()),
        )

        # 第 2 行：快捷倍率（拆行放置，彻底避免撑宽）
        quick_row = ttk.Frame(parent)
        quick_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(quick_row, text="全武器:").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            quick_row,
            text="伤害 ×2",
            command=lambda k=key: self._run_unit_weapon_quick(k, "dmg_x2"),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            quick_row,
            text="伤害 ×0.5",
            command=lambda k=key: self._run_unit_weapon_quick(k, "dmg_half"),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            quick_row,
            text="冷却 ×0.5",
            command=lambda k=key: self._run_unit_weapon_quick(k, "cd_half"),
        ).pack(side=tk.LEFT)

        if len(weapons) > 1:
            sync_row = ttk.Frame(parent)
            sync_row.pack(fill=tk.X, pady=(0, 4))
            ttk.Button(
                sync_row,
                text="将当前武器改动同步至本单位全部武器",
                command=lambda ck=wpn.key: self._on_sync_weapon_to_unit(ck),
            ).pack(side=tk.LEFT)

        # 有效射程实时提示（双行 + 动态换行）
        self.weapon_range_info_var = tk.StringVar(
            master=self.root, value=self._format_weapon_range_text(wpn)
        )
        range_lbl = ttk.Label(
            parent,
            textvariable=self.weapon_range_info_var,
            foreground="#004a99",
            wraplength=340,
            justify=tk.LEFT,
        )
        range_lbl.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
        self._register_subtab_wrap_label(parent, range_lbl)

        dmg_frame = ttk.LabelFrame(parent, text="伤害与溅射 (Weapon / gun)", padding=6)
        dmg_frame.pack(fill=tk.X, pady=(0, 6))
        self._configure_param_grid(dmg_frame)
        for r_idx, fname in enumerate((*ATTACK_DAMAGE_FIELDS, "gun_range"), start=1):
            self._build_field_row(
                parent=dmg_frame,
                row_idx=r_idx,
                layer="component",
                target_key=wpn.key,
                comp_class=wpn.comp_class,
                fname=fname,
                vanilla_val=wpn.fields[fname].value,
            )

        attr_frame = ttk.LabelFrame(parent, text="射程、射速与开火特性", padding=6)
        attr_frame.pack(fill=tk.X, pady=(0, 4))
        self._configure_param_grid(attr_frame)
        for r_idx, fname in enumerate(WEAPON_ATTR_FIELDS, start=1):
            self._build_field_row(
                parent=attr_frame,
                row_idx=r_idx,
                layer="component",
                target_key=wpn.key,
                comp_class=wpn.comp_class,
                fname=fname,
                vanilla_val=wpn.fields[fname].value,
            )

    def _on_switch_weapon(self, key: ConfigKey, new_idx: int) -> None:
        if new_idx < 0:
            return
        self.commit_current_field_edits()
        self._selected_weapon_idx_by_config[key] = new_idx
        self._render_inspector(key)

    def _run_unit_weapon_quick(self, key: ConfigKey, mode: str) -> None:
        if self.snapshot is None:
            return
        self.commit_current_field_edits()
        prev = (
            clone_overrides(self.overrides),
            clone_component_overrides(self.component_overrides),
            clone_world_overrides(self.world_overrides),
        )
        vb = self.snapshot.vanilla_bundle
        if mode == "dmg_x2":
            new_comp, changed = apply_batch_weapon_damage_factor(vb, self.component_overrides, [key], 2.0)
        elif mode == "dmg_half":
            new_comp, changed = apply_batch_weapon_damage_factor(vb, self.component_overrides, [key], 0.5)
        else:
            new_comp, changed = apply_batch_weapon_cooldown_factor(vb, self.component_overrides, [key], 0.5)

        if changed > 0:
            self.batch_undo_stack.append(prev)
            self.undo_batch_btn.configure(state=tk.NORMAL)
            self.component_overrides = new_comp
            self.refresh_item_list()

    def _on_sync_weapon_to_unit(self, source_comp_key: ComponentKey) -> None:
        if self.snapshot is None:
            return
        self.commit_current_field_edits()
        prev = (
            clone_overrides(self.overrides),
            clone_component_overrides(self.component_overrides),
            clone_world_overrides(self.world_overrides),
        )
        new_comp, changed = sync_weapon_overrides_to_unit(
            self.snapshot.vanilla_bundle, self.component_overrides, source_comp_key
        )
        self.batch_undo_stack.append(prev)
        self.undo_batch_btn.configure(state=tk.NORMAL)
        self.component_overrides = new_comp
        self.refresh_item_list()
        self._info("已同步同单位武器", f"已将当前武器数值同步至同单位其余 {changed} 门改动不同的武器。")

    def _render_mobility_logistics_subtab(self, parent: ttk.Frame, item: Any) -> None:
        other_comps = [
            c
            for c in item.components
            if c.comp_class not in ("HP", "Regeneration", *ATTACK_COMPONENT_CLASSES)
        ]
        if not other_comps:
            self._render_no_prefab_notice(parent, item, "机动 / 视野 / 采集 / 运输 / 医疗 / 生产队列")
            return

        section_titles = {
            "TankPattern": "机动性 (履带 TankPattern)",
            "CarPattern": "机动性 (轮式 CarPattern)",
            "SmoothPattern": "机动性 (飞行/步兵 SmoothPattern)",
            "UnitComponent": "基础视野 (UnitComponent)",
            "FogOfWarUnit": "大视野组件 (FogOfWarUnit)",
            "Harvester": "采矿车 (Harvester)",
            "OilPump": "自动产矿油井 (OilPump)",
            "Bunker": "运兵舱 / 碉堡 (Bunker)",
            "HealRange": "医疗 / 维修光环 (HealRange)",
            "BuildComponent": "生产队列加速与折扣 (BuildComponent)",
        }
        for comp in other_comps:
            title = section_titles.get(comp.comp_class, comp.comp_class)
            tail = comp.go_rel_path.split("/")[-1] if "/" in comp.go_rel_path else comp.go_rel_path
            box = ttk.LabelFrame(parent, text=f"{title} · {tail}", padding=6)
            box.pack(fill=tk.X, pady=(0, 6))
            self._configure_param_grid(box)
            for r_idx, fname in enumerate(comp.fields.keys(), start=1):
                self._build_field_row(
                    parent=box,
                    row_idx=r_idx,
                    layer="component",
                    target_key=comp.key,
                    comp_class=comp.comp_class,
                    fname=fname,
                    vanilla_val=comp.fields[fname].value,
                )

    def _toggle_advanced_fields(self) -> None:
        self.commit_current_field_edits()
        self.advanced_expanded_var.set(not self.advanced_expanded_var.get())
        self._render_inspector(self.selected_key)

    def _get_spec_and_override_dict(
        self, layer: str, target_key: Any, comp_class: str | None, fname: str
    ) -> tuple[FieldSpec, dict[Any, dict[str, int | float]]]:
        if layer == "config":
            return FIELD_META[fname], self.overrides
        assert comp_class is not None
        spec = get_component_field_spec(comp_class, fname)
        if layer == "component":
            return spec, self.component_overrides
        return spec, self.world_overrides

    def _build_field_row(
        self,
        *,
        parent: ttk.Frame,
        row_idx: int,
        layer: str,
        target_key: Any,
        comp_class: str | None,
        fname: str,
        vanilla_val: int | float,
    ) -> None:
        spec, ov_store = self._get_spec_and_override_dict(layer, target_key, comp_class, fname)
        cur_val = ov_store.get(target_key, {}).get(fname, vanilla_val)
        is_mod = not (
            values_equal(fname, cur_val, vanilla_val)
            if layer == "config"
            else component_values_equal(comp_class or "", fname, cur_val, vanilla_val)
        )

        label_text = f"{spec.label}" + (f" ({spec.unit})" if spec.unit else "")
        lbl = ttk.Label(
            parent,
            text=label_text,
            foreground="#005fb8" if is_mod else "#222222",
            anchor=tk.W,
        )
        lbl.grid(row=row_idx, column=0, sticky=tk.EW, padx=(0, 4), pady=2)

        van_lbl = ttk.Label(
            parent,
            text=format_display_value_by_spec(spec, vanilla_val),
            width=7,
            foreground="#666666",
            anchor=tk.W,
        )
        van_lbl.grid(row=row_idx, column=1, sticky=tk.W, padx=(4, 4), pady=2)

        ed_key = (layer, target_key, fname)
        reset_btn = ttk.Button(
            parent,
            text="还原",
            width=5,
            state=tk.NORMAL if is_mod else tk.DISABLED,
            command=lambda ek=ed_key: self._on_reset_single_field(ek),
        )
        reset_btn.grid(row=row_idx, column=3, sticky=tk.E, padx=(4, 0), pady=2)

        if spec.kind == "bool":
            var = tk.IntVar(master=self.root, value=1 if int(cur_val) == 1 else 0)
            chk = ttk.Checkbutton(
                parent,
                text="启用" if var.get() == 1 else "关闭",
                variable=var,
                command=lambda ek=ed_key: self._on_bool_toggled(ek),
            )
            chk.grid(row=row_idx, column=2, sticky=tk.W, padx=(4, 4), pady=2)
            self._field_editors[ed_key] = {
                "layer": layer,
                "target_key": target_key,
                "comp_class": comp_class,
                "fname": fname,
                "spec": spec,
                "vanilla_val": vanilla_val,
                "kind": "bool",
                "var": var,
                "widget": chk,
                "label": lbl,
                "reset_btn": reset_btn,
            }
        else:
            var_s = tk.StringVar(
                master=self.root, value=format_entry_text_by_spec(spec, cur_val)
            )
            entry = ttk.Entry(parent, textvariable=var_s, width=10)
            entry.grid(row=row_idx, column=2, sticky=tk.EW, padx=(4, 4), pady=2)
            var_s.trace_add("write", lambda *_a, ek=ed_key: self._on_entry_live_edit(ek))
            entry.bind("<FocusOut>", lambda _e, ek=ed_key: self._commit_single_field(ek, show_error=True))
            entry.bind("<Return>", lambda _e, ek=ed_key: self._commit_single_field(ek, show_error=True))
            self._field_editors[ed_key] = {
                "layer": layer,
                "target_key": target_key,
                "comp_class": comp_class,
                "fname": fname,
                "spec": spec,
                "vanilla_val": vanilla_val,
                "kind": spec.kind,
                "var": var_s,
                "widget": entry,
                "label": lbl,
                "reset_btn": reset_btn,
            }

    def _on_bool_toggled(self, ed_key: tuple[str, Any, str]) -> None:
        if self.snapshot is None:
            return
        info = self._field_editors.get(ed_key)
        if not info:
            return
        val = int(info["var"].get())
        info["widget"].configure(text="启用" if val == 1 else "关闭")
        self._apply_single_field_override(ed_key, val)

    def _on_entry_live_edit(self, ed_key: tuple[str, Any, str]) -> None:
        if self._suppress_entry_trace:
            return
        self._commit_single_field(ed_key, show_error=False)

    def _commit_single_field(self, ed_key: tuple[str, Any, str], *, show_error: bool) -> bool:
        if self.snapshot is None:
            return True
        info = self._field_editors.get(ed_key)
        if not info or info["kind"] == "bool":
            return True

        layer = info["layer"]
        target_key = info["target_key"]
        comp_class = info["comp_class"]
        fname = info["fname"]
        spec: FieldSpec = info["spec"]
        vanilla_val = info["vanilla_val"]
        raw_text = info["var"].get()

        try:
            if layer == "config":
                checked = validate_field_value(
                    target_key[0], fname, raw_text, vanilla_value=vanilla_val
                )
            else:
                checked = validate_component_field_value(
                    comp_class, fname, raw_text, vanilla_value=vanilla_val
                )
        except ValidationError as exc:
            self.validation_var.set(f"输入校验提示: {exc}")
            if show_error:
                _, ov_store = self._get_spec_and_override_dict(layer, target_key, comp_class, fname)
                cur_val = ov_store.get(target_key, {}).get(fname, vanilla_val)
                self._suppress_entry_trace = True
                try:
                    info["var"].set(format_entry_text_by_spec(spec, cur_val))
                finally:
                    self._suppress_entry_trace = False
            return False

        self.validation_var.set("")
        self._apply_single_field_override(ed_key, checked)
        return True

    def commit_current_field_edits(self) -> bool:
        """提交右侧编辑区全部子页签的有效输入。"""
        all_ok = True
        for ed_key in list(self._field_editors.keys()):
            if not self._commit_single_field(ed_key, show_error=True):
                all_ok = False
        return all_ok

    def _apply_single_field_override(
        self, ed_key: tuple[str, Any, str], new_val: int | float
    ) -> None:
        if self.snapshot is None or self.selected_key is None:
            return
        info = self._field_editors.get(ed_key)
        if not info:
            return
        layer = info["layer"]
        target_key = info["target_key"]
        comp_class = info["comp_class"]
        fname = info["fname"]
        vanilla_val = info["vanilla_val"]

        _, ov_store = self._get_spec_and_override_dict(layer, target_key, comp_class, fname)
        is_mod = not (
            values_equal(fname, new_val, vanilla_val)
            if layer == "config"
            else component_values_equal(comp_class, fname, new_val, vanilla_val)
        )

        if is_mod:
            ov_store.setdefault(target_key, {})[fname] = new_val
        else:
            if target_key in ov_store and fname in ov_store[target_key]:
                del ov_store[target_key][fname]
                if not ov_store[target_key]:
                    del ov_store[target_key]

        info["label"].configure(foreground="#005fb8" if is_mod else "#222222")
        info["reset_btn"].configure(state=tk.NORMAL if is_mod else tk.DISABLED)

        # 更新当前武器有效射程展示
        if (
            layer == "component"
            and comp_class in ATTACK_COMPONENT_CLASSES
            and fname in ("range", "addRange")
            and hasattr(self, "weapon_range_info_var")
        ):
            comp = self.snapshot.vanilla_bundle.components_by_key[target_key]
            self.weapon_range_info_var.set(self._format_weapon_range_text(comp))

        # 更新标题、左侧列表行、子页签星标与底栏统计
        if len(self.selected_key) == 4:
            witem = self.snapshot.vanilla_bundle.world_by_key[self.selected_key]
            w_ov = self.world_overrides.get(self.selected_key, {})
            self.item_title_var.set(f"{witem.display_name}{'  [已修改]' if w_ov else ''}")
            self.reset_item_btn.configure(state=tk.NORMAL if w_ov else tk.DISABLED)
            iid = self._encode_iid(self.selected_key)
            if self.tree.exists(iid):
                self.tree.item(
                    iid,
                    values=(
                        witem.display_name,
                        witem.affiliation_name,
                        witem.go_name,
                        self._build_world_diff_summary(witem, w_ov),
                    ),
                    tags=("modified",) if w_ov else (),
                )
        else:
            item = self.snapshot.vanilla_bundle.by_key[self.selected_key]
            cfg_mod = self._is_config_modified(self.selected_key)
            self.item_title_var.set(f"{item.display_name}{'  [已修改]' if cfg_mod else ''}")
            self.reset_item_btn.configure(state=tk.NORMAL if cfg_mod else tk.DISABLED)
            iid = self._encode_iid(self.selected_key)
            if self.tree.exists(iid):
                is_enemy = is_enemy_affiliation(item.affiliation)
                tags = (
                    ("enemy_mod",) if cfg_mod else ("enemy_unmod",)
                ) if is_enemy else (("modified",) if cfg_mod else ())
                self.tree.item(
                    iid,
                    values=(
                        item.display_name,
                        item.affiliation_name,
                        item.asset_name,
                        self._build_config_diff_summary(item),
                    ),
                    tags=tags,
                )

        self._update_subtab_tab_badges(self.selected_key)
        self._update_footer_summary()

    def _on_reset_single_field(self, ed_key: tuple[str, Any, str]) -> None:
        if self.snapshot is None:
            return
        info = self._field_editors.get(ed_key)
        if not info:
            return
        vanilla_val = info["vanilla_val"]
        spec: FieldSpec = info["spec"]
        self._suppress_entry_trace = True
        try:
            if info["kind"] == "bool":
                v = 1 if int(vanilla_val) == 1 else 0
                info["var"].set(v)
                info["widget"].configure(text="启用" if v == 1 else "关闭")
            else:
                info["var"].set(format_entry_text_by_spec(spec, vanilla_val))
        finally:
            self._suppress_entry_trace = False
        self.validation_var.set("")
        self._apply_single_field_override(ed_key, vanilla_val)

    def _on_reset_selected_item(self) -> None:
        if self.selected_key is None:
            return
        if len(self.selected_key) == 4:
            self.world_overrides, _ = reset_world_keys_to_vanilla(
                self.world_overrides, [self.selected_key]
            )
        else:
            self.overrides, self.component_overrides, _ = reset_config_and_component_keys_to_vanilla(
                self.overrides, self.component_overrides, [self.selected_key]
            )
        self.refresh_item_list()

    def _update_footer_summary(self) -> None:
        cfg_fields = sum(len(v) for v in self.overrides.values())
        comp_fields = sum(len(v) for v in self.component_overrides.values())
        world_fields = sum(len(v) for v in self.world_overrides.values())
        total_fields = cfg_fields + comp_fields + world_fields
        if total_fields == 0:
            self.footer_summary_var.set("待应用修改: 0 项（当前配置与原版完全一致）")
        else:
            self.footer_summary_var.set(
                f"待应用修改: 共 {total_fields} 项参数"
                f"（配置 {len(self.overrides)} 对象/{cfg_fields} 项 · "
                f"战斗组件 {len(self.component_overrides)} 实例/{comp_fields} 项 · "
                f"地图资源 {len(self.world_overrides)} 点/{world_fields} 项）"
            )

    def _on_clear_search(self) -> None:
        self.search_var.set("")

    def _on_browse_dir(self) -> None:
        picked = filedialog.askdirectory(
            title="选择游戏 Dust Front RTS_Data 目录",
            initialdir=str(self.data_dir if self.data_dir.exists() else self.workspace_dir),
        )
        if picked:
            self.game_dir_var.set(picked)
            self.refresh_workspace()

    def _on_manual_dir_apply(self) -> None:
        self.refresh_workspace()

    def _on_load_selected_preset(self) -> None:
        if self.snapshot is None:
            self._error("无法加载预设", "请先选择有效的游戏 Dust Front RTS_Data 目录。")
            return
        label = self.preset_var.get()
        path = self._preset_choices.get(label)
        if path is None:
            self.overrides = {}
            self.component_overrides = {}
            self.world_overrides = {}
            self.batch_undo_stack.clear()
            self.undo_batch_btn.configure(state=tk.DISABLED)
            self.refresh_item_list()
            return
        self._load_preset_from_path(path)

    def _load_preset_from_path(self, path: Path) -> None:
        assert self.snapshot is not None
        try:
            res = load_preset_file(path, self.snapshot.vanilla_bundle)
        except PresetError as exc:
            self._error("预设加载失败", str(exc))
            return
        self.overrides = res.overrides
        self.component_overrides = res.component_overrides
        self.world_overrides = res.world_overrides
        self.batch_undo_stack.clear()
        self.undo_batch_btn.configure(state=tk.DISABLED)
        self.refresh_item_list()
        if res.warnings:
            self._warn(
                "预设兼容提示",
                f"已加载预设「{res.preset.name}」，但以下条目在当前版本中不存在并已跳过：\n\n"
                + "\n".join(res.warnings[:10]),
            )

    def _on_save_preset(self) -> None:
        if self.snapshot is None:
            self._error("无法保存预设", "请先选择有效的游戏目录。")
            return
        self.commit_current_field_edits()
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        name = simpledialog.askstring(
            "保存为预设", "请输入预设名称（将保存为 Schema v2 预设）：", parent=self.root
        )
        if not name or not name.strip():
            return
        safe_stem = "".join(
            ch if ch not in r'\/:*?"<>|' else "_" for ch in name.strip()
        )
        target = self.presets_dir / f"{safe_stem}.json"
        if target.exists() and not self._confirm(
            "覆盖确认", f"预设文件 {target.name} 已存在，是否覆盖？"
        ):
            return
        save_preset_file(
            target,
            name.strip(),
            f"自定义预设 ({name.strip()})",
            self.snapshot.vanilla_bundle,
            self.overrides,
            component_overrides=self.component_overrides,
            world_overrides=self.world_overrides,
        )
        self.refresh_preset_dropdown()
        self._info("保存成功", f"预设已保存至：\n{target}")

    def _on_import_preset(self) -> None:
        if self.snapshot is None:
            self._error("无法导入", "请先选择有效的游戏目录。")
            return
        picked = filedialog.askopenfilename(
            title="导入预设 JSON 文件",
            initialdir=str(self.presets_dir if self.presets_dir.exists() else self.workspace_dir),
            filetypes=[("JSON 预设文件", "*.json"), ("所有文件", "*.*")],
        )
        if picked:
            self._load_preset_from_path(Path(picked))

    def _on_export_preset(self) -> None:
        if self.snapshot is None:
            self._error("无法导出", "请先选择有效的游戏目录。")
            return
        self.commit_current_field_edits()
        picked = filedialog.asksaveasfilename(
            title="导出当前修改为 Schema v2 JSON 预设",
            initialdir=str(self.presets_dir if self.presets_dir.exists() else self.workspace_dir),
            defaultextension=".json",
            filetypes=[("JSON 预设文件", "*.json")],
        )
        if not picked:
            return
        out = Path(picked)
        save_preset_file(
            out,
            out.stem,
            f"由配置器导出的自定义修改 ({out.stem})",
            self.snapshot.vanilla_bundle,
            self.overrides,
            component_overrides=self.component_overrides,
            world_overrides=self.world_overrides,
        )
        total_cnt = (
            sum(len(v) for v in self.overrides.values())
            + sum(len(v) for v in self.component_overrides.values())
            + sum(len(v) for v in self.world_overrides.values())
        )
        self._info("导出成功", f"已导出 {total_cnt} 项三层参数修改至：\n{out}")

    def _on_batch_all_minerals_dialog(self) -> None:
        if self.snapshot is None:
            self._error("无法修改", "请先选择有效的游戏目录。")
            return
        self.commit_current_field_edits()
        raw_val = simpledialog.askinteger(
            "一键修改全部标准矿脉储量",
            "请输入全部 7 个标准 Mineral 矿脉的新储量（原版均为 2000，允许 1 ~ 999999）：",
            initialvalue=10000,
            minvalue=1,
            maxvalue=999_999,
            parent=self.root,
        )
        if raw_val is None:
            return
        self.apply_batch_all_minerals(raw_val)

    def apply_batch_all_minerals(self, new_val: int) -> int:
        """供界面与测试调用的一键设置全部标准矿脉储量方法。"""
        assert self.snapshot is not None
        prev_snapshot = (
            clone_overrides(self.overrides),
            clone_component_overrides(self.component_overrides),
            clone_world_overrides(self.world_overrides),
        )
        new_world, changed = apply_batch_all_minerals_value(
            self.snapshot.vanilla_bundle, self.world_overrides, new_val
        )
        self.batch_undo_stack.append(prev_snapshot)
        self.undo_batch_btn.configure(state=tk.NORMAL)
        self.world_overrides = new_world
        self.refresh_item_list()
        return changed

    def _run_batch_operation(self, op_name: str, *, skip_confirm: bool = False) -> int:
        if self.snapshot is None:
            self._error("无法批量修改", "请先选择有效的游戏目录。")
            return 0
        self.commit_current_field_edits()
        targets = list(self.filtered_keys)
        if not targets:
            self._info("无匹配对象", "当前筛选列表为空，没有可操作的对象。")
            return 0

        if self.current_tab_script == WORLD_TAB_KEY:
            if op_name != "reset_filtered":
                self._info(
                    "请使用矿脉批量工具",
                    "「地图资源点」页签支持在「更多批量 -> 一键修改全部 7 个标准矿脉储量」或右侧单点调整，或执行重置操作。",
                )
                return 0
            world_targets: list[WorldKey] = [t for t in targets if len(t) == 4]
            if not skip_confirm and not self._confirm(
                "批量重置确认",
                f"确定将当前筛选出的 {len(world_targets)} 个地图资源点重置为原版值吗？",
            ):
                return 0
            prev_snapshot = (
                clone_overrides(self.overrides),
                clone_component_overrides(self.component_overrides),
                clone_world_overrides(self.world_overrides),
            )
            new_world, changed = reset_world_keys_to_vanilla(self.world_overrides, world_targets)
            self.batch_undo_stack.append(prev_snapshot)
            self.undo_batch_btn.configure(state=tk.NORMAL)
            self.world_overrides = new_world
            self.refresh_item_list()
            return changed

        cfg_targets: list[ConfigKey] = [t for t in targets if len(t) == 2]
        vbundle = self.snapshot.vanilla_bundle
        aff_stats = count_targets_by_affiliation(vbundle, cfg_targets)

        desc_map = {
            "time_half": "建造/研发/冷却时间设为原版 ×0.5",
            "time_x2": "建造/研发/冷却时间设为原版 ×2",
            "minerals_half": "矿物消耗设为原版 ×0.5",
            "minerals_x2": "矿物消耗设为原版 ×2",
            "gears_half": "零件需求设为原版 ×0.5",
            "pop_x2": "人口提供上限设为原版 ×2",
            "pop_x5": "人口提供上限设为原版 ×5",
            "unlock_max_count": "解除建造数量限制 (maxCount → 0)",
            "hp_x2": "最大血量设为原版 ×2（自动同步 curHp）",
            "hp_half": "最大血量设为原版 ×0.5（自动同步 curHp）",
            "dmg_x2": "全部武器伤害设为原版 ×2",
            "dmg_half": "全部武器伤害设为原版 ×0.5",
            "speed_x1_5": "移动速度设为原版 ×1.5",
            "speed_half": "移动速度设为原版 ×0.5",
            "weapon_cd_half": "武器攻击冷却设为原版 ×0.5",
            "reset_filtered": "重置所有字段为原版值（含战斗组件）",
        }

        if not skip_confirm:
            enemy_warn_block = ""
            if aff_stats["enemy"] > 0:
                enemy_warn_block = (
                    f"\n⚠️【敌方影响警告】本次范围包含 {aff_stats['enemy']} 个敌方 AI 对象"
                    f"（变种人 {aff_stats['enemy_mutants']} / 叛军 {aff_stats['enemy_rebels']} / 机器人 {aff_stats['enemy_robots']}）！\n"
                    "确定要一并修改敌方数值吗？\n"
                )
            msg = (
                f"即将对以下筛选范围执行：「{desc_map[op_name]}」\n"
                f"共 {aff_stats['total']} 项对象明细：\n"
                f"  • 我方：{aff_stats['player']} 项（帝国 {aff_stats['player_empire']} / 雇佣兵 {aff_stats['player_merc']}）\n"
                f"  • 敌方：{aff_stats['enemy']} 项（变种人 {aff_stats['enemy_mutants']} / 叛军 {aff_stats['enemy_rebels']} / 机器人 {aff_stats['enemy_robots']}）\n"
                f"  • 中立：{aff_stats['neutral']} 项"
                f"{enemy_warn_block}\n"
                "注：全部倍率基于原版基准计算，支持点击「撤销上步批量」恢复。是否继续？"
            )
            if not self._confirm("批量操作确认", msg):
                return 0

        prev_snapshot = (
            clone_overrides(self.overrides),
            clone_component_overrides(self.component_overrides),
            clone_world_overrides(self.world_overrides),
        )
        new_ov = clone_overrides(self.overrides)
        new_comp = clone_component_overrides(self.component_overrides)

        if op_name == "time_half":
            new_ov, changed = apply_batch_time_factor(vbundle, new_ov, cfg_targets, 0.5)
        elif op_name == "time_x2":
            new_ov, changed = apply_batch_time_factor(vbundle, new_ov, cfg_targets, 2.0)
        elif op_name == "minerals_half":
            new_ov, changed = apply_batch_int_cost_factor(vbundle, new_ov, cfg_targets, "minerals", 0.5)
        elif op_name == "minerals_x2":
            new_ov, changed = apply_batch_int_cost_factor(vbundle, new_ov, cfg_targets, "minerals", 2.0)
        elif op_name == "gears_half":
            new_ov, changed = apply_batch_int_cost_factor(vbundle, new_ov, cfg_targets, "gears", 0.5)
        elif op_name == "pop_x2":
            new_ov, changed = apply_batch_population_factor(vbundle, new_ov, cfg_targets, 2.0)
        elif op_name == "pop_x5":
            new_ov, changed = apply_batch_population_factor(vbundle, new_ov, cfg_targets, 5.0)
        elif op_name == "unlock_max_count":
            new_ov, changed = apply_batch_unlock_max_count(vbundle, new_ov, cfg_targets)
        elif op_name == "hp_x2":
            new_comp, changed = apply_batch_hp_factor(vbundle, new_comp, cfg_targets, 2.0)
        elif op_name == "hp_half":
            new_comp, changed = apply_batch_hp_factor(vbundle, new_comp, cfg_targets, 0.5)
        elif op_name == "dmg_x2":
            new_comp, changed = apply_batch_weapon_damage_factor(vbundle, new_comp, cfg_targets, 2.0)
        elif op_name == "dmg_half":
            new_comp, changed = apply_batch_weapon_damage_factor(vbundle, new_comp, cfg_targets, 0.5)
        elif op_name == "speed_x1_5":
            new_comp, changed = apply_batch_move_speed_factor(vbundle, new_comp, cfg_targets, 1.5)
        elif op_name == "speed_half":
            new_comp, changed = apply_batch_move_speed_factor(vbundle, new_comp, cfg_targets, 0.5)
        elif op_name == "weapon_cd_half":
            new_comp, changed = apply_batch_weapon_cooldown_factor(vbundle, new_comp, cfg_targets, 0.5)
        elif op_name == "reset_filtered":
            new_ov, new_comp, changed = reset_config_and_component_keys_to_vanilla(
                new_ov, new_comp, cfg_targets
            )
        else:
            return 0

        self.batch_undo_stack.append(prev_snapshot)
        self.undo_batch_btn.configure(state=tk.NORMAL)
        self.overrides = new_ov
        self.component_overrides = new_comp
        self.refresh_item_list()
        return changed

    def _on_undo_batch(self) -> None:
        if not self.batch_undo_stack:
            return
        ov, comp_ov, world_ov = self.batch_undo_stack.pop()
        self.overrides = ov
        self.component_overrides = comp_ov
        self.world_overrides = world_ov
        if not self.batch_undo_stack:
            self.undo_batch_btn.configure(state=tk.DISABLED)
        self.refresh_item_list()

    def _on_archive_and_rebuild(self) -> None:
        if not self._confirm(
            "归档旧备份并重建新基准",
            "检测到当前游戏 sharedassets0.assets 与已有原版备份不一致。\n"
            "将把旧版备份与元数据重命名为 *.old 归档保留，并以当前文件重新建立原版基准。\n"
            "请确认当前游戏文件确为您想要作为原版基准的版本！是否继续？",
        ):
            return
        try:
            archived, _, _ = archive_old_backup_and_rebuild(
                self.data_dir, allow_unknown_baseline=True
            )
        except Exception as exc:
            self._error("重建基准失败", str(exc))
            return
        self.refresh_workspace()
        self._info(
            "基准已重建",
            "已归档旧备份并建立新的原版基准：\n"
            + "\n".join(str(p.name) for p in archived),
        )

    def _on_apply_to_game(self, *, launch: bool) -> None:
        if self.snapshot is None:
            self._error("无法应用", "请先选择有效的游戏目录。")
            return
        if not self.commit_current_field_edits():
            self._error("输入未通过校验", self.validation_var.get() or "请先修正无效数值。")
            return

        allow_unknown = False
        while True:
            try:
                new_sha, count = apply_overrides_to_game(
                    self.data_dir,
                    self.overrides,
                    component_overrides=self.component_overrides,
                    world_overrides=self.world_overrides,
                    allow_unknown_baseline=allow_unknown,
                )
                break
            except ProcessRunningError as exc:
                self._warn("请先关闭游戏", str(exc))
                return
            except ExternalUpdateDetectedError as exc:
                if self._confirm(
                    "检测到游戏更新或外部修改",
                    f"{exc}\n\n是否现在将旧版备份归档为 .old，并以当前游戏文件重建新基准？",
                ):
                    self._on_archive_and_rebuild()
                return
            except BaselineConfirmationRequiredError as exc:
                if self._confirm(
                    "未知版本基准确认",
                    f"{exc}\n\n如果您确认当前游戏目录中的文件确为干净原版（非其他第三方 MOD），点「是」继续建立基准并应用；点「否」取消。",
                ):
                    allow_unknown = True
                    continue
                return
            except Exception as exc:
                self._error("应用补丁失败", str(exc))
                return

        self.refresh_workspace()
        if launch:
            try:
                launch_game_launcher(self.data_dir)
            except Exception as exc:
                self._warn(
                    "补丁已生效，但启动失败",
                    f"修改已写入（{count} 项，SHA-256: {new_sha[:12]}...），但无法启动 {LAUNCHER_EXE_NAME}：\n{exc}",
                )
                return
            self._info(
                "应用并启动成功",
                f"已成功写入 {count} 项三层参数改动，并已拉起 {LAUNCHER_EXE_NAME}！",
            )
        else:
            self._info(
                "应用成功",
                f"已成功基于干净原版备份写入 {count} 项三层参数改动！\n"
                f"当前文件 SHA-256: {new_sha[:16]}...\n"
                "（已完整保留 resources.assets 中文汉化）",
            )

    def _on_restore_vanilla(self) -> None:
        if self.snapshot is None:
            self._error("无法还原", "请先选择有效的游戏目录。")
            return
        if not self._confirm(
            "确认还原原版",
            "确定要将 Dust Front RTS_Data\\sharedassets0.assets 还原为干净原版吗？",
        ):
            return
        try:
            vanilla_sha = restore_vanilla_to_game(self.data_dir)
        except ProcessRunningError as exc:
            self._warn("请先关闭游戏", str(exc))
            return
        except ExternalUpdateDetectedError as exc:
            self._error("已拦截不安全的还原操作", str(exc))
            return
        except Exception as exc:
            self._error("还原原版失败", str(exc))
            return

        self.refresh_workspace()
        self._info("还原成功", f"已还原为干净原版文件（SHA-256: {vanilla_sha[:16]}...）。")


def run_gui(workspace_dir: Path, initial_game_dir: Path | None = None) -> int:
    """启动 V2 桌面 GUI 主循环（按屏幕比例居中自适应）。"""
    _enable_dpi_awareness()
    root = tk.Tk()
    root.title("《灰烬战争 (Dust Front RTS Demo)》外部可视化 MOD 配置与补丁器 V2")
    sw = max(1024, root.winfo_screenwidth())
    sh = max(720, root.winfo_screenheight())
    init_w = min(max(1240, int(sw * 0.80)), sw - 40)
    init_h = min(max(760, int(sh * 0.84)), sh - 70)
    pos_x = max(10, (sw - init_w) // 2)
    pos_y = max(10, (sh - init_h) // 2 - 15)
    root.geometry(f"{init_w}x{init_h}+{pos_x}+{pos_y}")
    root.minsize(1000, 640)
    ModConfiguratorApp(
        root,
        workspace_dir=workspace_dir,
        initial_game_dir=initial_game_dir,
    )
    root.mainloop()
    return 0
