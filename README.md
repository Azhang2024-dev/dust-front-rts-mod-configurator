# Dust Front RTS Demo MOD Configurator（灰烬战争外部可视化 MOD 配置与补丁器 v2.0.0）

适用于 **Dust Front RTS Demo (`D-35-1`, Unity `2020.3.3f1` IL2CPP)** 的纯 Python 3.12 标准库（`tkinter`/`ttk`）桌面端可视化参数配置与等长二进制补丁工具。

## 核心特性

- **零依赖原生界面**：100% Python 3.12 标准库实现，无第三方包依赖。
- **汉化完整兼容**：只读解析 `Dust Front RTS_Data/resources.assets` 中的中文化名词，绝不修改汉化资源文件。
- **等字节原位数值补丁**：仅原位覆写 `sharedassets0.assets` 内定长 4 字节（`int32` / `float32`）数值字段，严格保持文件总长度不变（`76,600,076` 字节），包含写入前共享 Prefab 冲突校验与 `.tmp` 原子替换。
- **实战阵营过滤与防误改保护（V2）**：
  - 区分 **我方（帝国） / 雇佣兵 / 敌方（变种人 / 叛军 / 机器人） / 中立地图物件**，默认仅展示与批量作用于「我方（帝国）」。
  - 列表包含敌方单位时弹出醒目警告条与「一键切回我方（帝国）」快捷按钮；批量修改二次确认框展示各阵营对象明细。
- **全配置 + 关联组件 + 地图资源点编辑（V2）**：
  - 顶层 5 类对象：`建筑 (63)`、`单位 (66)`、`科技升级 (40)`、`战术支援 (7)`、`地图资源 (9)`。
  - 右侧 4 个分标签检查器：`经济与建造`、`生命与护甲`、`武器火力`、`机动/视野/后勤`，覆盖 `HP`、`AutoAttack_*`、`MovePattern_*`、`UnitComponent`、`BuildComponent`、`HealRange`、`Bunker`、`Regeneration`、`OilPump`、`Harvester`、`FogOfWarUnit` 等组件。
  - 支持多血量节点与多武器槽位切换、单位全武器快捷倍率与参数同步、`HP.maxHp → curHp` 自动双写。
- **安全备份与预设生态**：
  - 自动建立并校验原版 SHA-256 备份（`sharedassets0.assets.vanilla_backup`），支持一键还原原版。
  - 检测游戏主程序与启动器运行状态，避免文件占用冲突。
  - 兼容 Schema v1 与 v2 JSON 预设导入/导出（内置 `presets/limited_mod_1022.json` 等预设）。

## 快速使用

1. 确保本工具文件夹位于游戏根目录下（即上级目录包含 `Dust Front RTS_Data/`），且已安装 **Python 3.12+**（含 `tcl/tk`）。
2. 双击 [`启动MOD配置器.bat`](启动MOD配置器.bat) 启动图形界面；或命令行运行：
   ```powershell
   python -m mod_configurator.main --game-dir "你的游戏根目录路径"
   ```
3. 在界面中调整参数或导入预设，点击 **应用修改到游戏** 或 **应用并启动游戏**。

## 开发与测试

运行全套单元测试与 GUI 布局验证（全部在临时目录隔离执行，不会修改真实游戏目录）：

```powershell
python -m unittest discover -s tests -v
```

启动器自检：

```cmd
启动MOD配置器.bat --check
```

## 目录结构

- `mod_configurator/`：核心解析、补丁、备份、预设管理与 `tkinter` GUI 模块
- `presets/`：Schema v1 / v2 JSON 参数预设
- `tests/`：单元、集成及高 DPI 窗口布局自动化测试
- `PRD与施工文档.md` / `PRD与施工文档_V2.md`：V1 / V2 产品需求与二进制协议规格文档
- `启动MOD配置器.bat`：Windows 一键自检与无窗口启动脚本
