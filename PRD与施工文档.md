# 《灰烬战争 (Dust Front RTS Demo)》外部可视化 MOD 配置与补丁器 — PRD 与施工文档

> **文档状态**：已根据评审意见完成修订（补齐跨版本防覆写保护、外部引用与文件格式校验、`useInFog` 字段开放、字段分层与只读/输入校验规则、重名消歧展示、批量计算口径、Unity v22 完整二进制协议、Preset JSON Schema、动态 Python 启动探测及反向/异常验收用例）。

---

# 第一部分：PRD（产品需求文档）

## 1. 产品定位、目标与范围边界

### 1.1 核心定位
打造一款**零代码注入、免第三方依赖、自带原版备份与跨版本防覆写保护、全中文名称映射、跨小版本兼容**的游戏外 GUI 数值修改与预设管理工具。
- **不改游戏代码 / 不注入 DLL**：只对 `sharedassets0.assets` 中的定长 4 字节数值字段做原地覆写，文件大小与偏移结构保持 100% 不变，杜绝闪退或与 `Dust Front RTS 单机启动器.exe` 冲突。
- **与汉化 100% 兼容**：自动只读提取 `Dust Front RTS_Data\resources.assets` 中的中文译名用于界面展示，绝不修改 `resources.assets`。
- **与版本更新解耦**：预设文件按**「脚本类型 + 内部资产名 (`m_Name`) + 字段名」**存储增量修改，不绑定 `PathID`；游戏小版本更新后可直接基于新版原版基准重新应用同一份 JSON 预设。

### 1.2 V1 非目标（Out of Scope）与分发定位
- **V1 修改边界**：V1 仅覆盖 4 类 Config 的经济消耗、生产时间、资源产出、冷却时间、迷雾施放及建造数量上限等定长数值字段；**不包含**单位生命值、攻击力、射程、移动速度等 Prefab 战斗属性修改（留作 V2 调研）。
- **分发与运行定位**：V1 面向本机 Windows + Python 3.12 环境开箱运行（零第三方 pip 包依赖）；若后续需向未安装 Python 的普通玩家公开分发，将 PyInstaller 单文件 `.exe` 打包列为 V2 备选方案。

---

## 2. 可调范围、字段分层与校验规则

### 2.1 可调对象清单（V1 全量覆盖，已 100% 实测校验通过）
经对当前 `sharedassets0.assets` 全量扫描验证，以下 **4 大类共 176 个配置对象** 结构完全规整（解析成功率 `176/176`），且同类脚本下 `m_Name` 100% 唯一（0 重复）：

| 分类页签 | 对应 C# 脚本类 | 对象数量 | 开放可调字段 |
| :--- | :--- | :---: | :--- |
| **建筑配置** | `BuildConfig` | **63** | 矿物消耗 (`minerals`)、电力消耗 (`energyPrice`)、人口占用 (`limitPrice`)、零件需求 (`gears`)、建造时间 (`timeCreation`, 秒)、提供电力 (`energyProduce`)、提供人口上限 (`limitProduce`)、提供储存上限 (`siloProduce`)、建造数量上限 (`maxCount`, `0` 为不限) |
| **单位配置** | `UnitConfig` | **66** | 同上（包含机动建造车 MCV、无畏舰、采矿车及各阵营步兵/载具/战机） |
| **科技/学说升级** | `UpgradeConfig` | **40** | 主要参数：`minerals`、`limitPrice`、`timeCreation`（秒）；折叠展开区：`energyPrice`、`gears`、`energyProduce`、`limitProduce`、`siloProduce` |
| **战术支援技能** | `TacticalAbilityConfig` | **7** | 主要参数：冷却时间 (`coolDown`, 秒)、开局是否进入冷却 (`coolDownInStart`, 勾选 `0/1`)、允许在战争迷雾中使用 (`useInFog`, 勾选 `0/1`)；折叠展开区：`PriceResources` 费用/产出字段 |

### 2.2 字段分层与只读约束
1. **严格只读字段（禁止写入）**：
   - `faction`（阵营枚举：`0=中立/雇佣兵, 1=帝国, 2=变种人, 3=机器人, 4=叛军`）：仅用于界面展示与阵营筛选，禁止修改，防止破坏科技树与 AI 逻辑。
   - `onlyGlobalMinerals`、`skipLoadIfBlocked`：保持只读不开放编辑。
2. **编辑面板双层展示（「主要参数」vs「展开全部 `PriceResources` 字段」）**：
   - 实测 `TacticalAbilityConfig`（7 项）的全部 `PriceResources` 原版均为 `0`；`UpgradeConfig`（40 项）的 `energyPrice / gears / energyProduce / limitProduce / siloProduce` 原版全部为 `0`；`UnitConfig`（66 项）仅 MCV 有产出字段非零、仅 3 个重型单位消耗零件。
   - 为避免误导玩家认为所有全 0 字段均在游戏逻辑中生效，默认界面仅突出展示**「主要参数」**，其余 `PriceResources` 字段收纳在**「高级 / 全部字段（原版为 0，游戏内对该类型可能不生效）」**折叠区中。

### 2.3 数值输入校验规则
- **整数字段**（`minerals` / `energyPrice` / `limitPrice` / `gears` / `energyProduce` / `limitProduce` / `siloProduce` / `maxCount`）：
  - 允许范围 `0 <= val <= 999999`，禁止负数、小数及超出 `int32` 范围的数值。
- **浮点时间字段**（`timeCreation` / `coolDown`）：
  - 禁止负数、`NaN`、`Inf`（上限限制 `<= 99999.0`）；
  - 对**原版 `timeCreation > 0` 的对象**，下限钳制 `>= 0.5` 秒（防止建造/生产进度条因除零卡死）；对**原版即为 `0.0`** 的地图特殊物件或全局学说升级，允许保留 `0.0`。
- **布尔字段**（`coolDownInStart` / `useInFog`）：
  - 使用界面勾选框（Checkbox）编辑，内部严格仅写入 `int32(0)` 或 `int32(1)`。

---

## 3. 功能模块设计

### F1. 游戏目录状态诊断与跨版本安全备份
- **自动定位**：启动时默认关联上一级目录 `..\Dust Front RTS_Data`，支持手动浏览切换游戏数据目录。
- **精细化四态诊断**（状态栏禁止将未知文件误标为 `D-35-1` 原版）：
  - `🟢 已验证原版 (D-35-1)`：当前或基准 SHA-256 精确匹配已验证原版指纹 `0B814128...`。
  - `🔵 已启用：有限修改MOD (10月22日原版)`：SHA-256 精确匹配已知原版 MOD 指纹 `A20E9977...`。
  - `🟣 已启用：自定义修改 (共 N 项改动)`：基于已知干净基准通过本工具打补丁生成（命中 `last_applied_sha256`）。
  - `🟡 未知版本/外部修改基准（需确认）`：SHA-256 未在已知指纹中登记且非本工具最近产物，必须先由用户确认后再建立或更新基准。
- **防呆备份与跨版本更新防覆写保护**：
  - **严格忽略**游戏目录中已有的旧版 `Dust Front RTS_Data\sharedassets0.assets.bak`（`2026/10/16`，`28,990` 对象），全程不读取、不覆盖、不依靠其回滚，防止误还原旧版本导致游戏崩溃。
  - 首次打补丁前，将干净的原版文件备份至 `Dust Front RTS_Data\sharedassets0.assets.vanilla_backup`，并写入 `Dust Front RTS_Data\vanilla_backup.meta.json`（记录 `vanilla_sha256`、`last_applied_sha256`、`file_size`、`object_count`、`unity_version` 等）。
  - **已知旧 MOD 自动重建**：若玩家此前已手动将 10 月 22 日 MOD（`A20E9977...`）覆盖进游戏目录，工具检测到该指纹后会自动将那 10 个改动字段回填原版值，精确重建干净的 `D-35-1` 原版基准文件。
  - **跨版本更新拦截**：每次启动、应用补丁或点击还原前，校验当前 `Dust Front RTS_Data\sharedassets0.assets` 的 SHA-256。若已有 `vanilla_backup`，但当前游戏文件的 SHA-256 **既不等于 `vanilla_sha256` 也不等于 `last_applied_sha256`**（且非已知旧 MOD `A20E9977...`），说明游戏已更新或被外部程序替换。此时工具**强制拦截自动覆写与旧备份还原**，弹窗提示用户确认后将旧备份归档为 `sharedassets0.assets.vanilla_backup.<timestamp>.old`，再以当前新版建立新基准。

### F2. 检索、筛选、重名消歧与可视化对比编辑
- **多维过滤**：
  - 顶部切换 4 大分类页签（建筑 `63` / 单位 `66` / 科技升级 `40` / 战术支援 `7`）。
  - **阵营筛选**（建筑与单位支持）：`全部` / `帝国 (Empire, 51)` / `变种人 (Mutants, 25)` / `叛军 (Rebels, 17)` / `机器人 (Robots, 13)` / `中立/雇佣兵 (None, 23)`。
  - **关键词实时搜索**：支持同时检索中文名（如“无畏”“仓库”“起重机”）、内部资产名（如 `r_Dreadnought_Unit`）与本地化 Key（如 `unit-dreadnought`）。
  - **「仅显示已修改项」勾选框**：一键聚焦当前有改动的对象。
- **重名消歧与无译名降级展示**：
  - 实测存在 **7 组不同对象共用同一个 `nameKey`（中文名完全相同）**（例如 `build-largeCrane` 对应 `r_Crane_Build` 帝国与 `g_TreeCrane_Build` 变种人、`build-refinery` 对应 `r_Refinery_Build` 与 `y_Refinery_Build`、`support-heavyBomber` 对应 `r_heavyBombardment` 与 `mutantBirdBombardment`、`unit-assaultTruck` 对应 `y_ArkanoidTruck_Unit` 与 `y_AssaultTruck_Unit`，另有 `build-civsStructs`、`object-ostov` 各 2 个变体），以及 **4 个无译名对象**（`CargoTruckBus_Unit`、`CargoTruckFuel_Unit`、`CargoTruckRes_Unit`、`Point`）。
  - 因此左侧列表行与右侧编辑面板头部**必须固定同时展示：`中文名 | 阵营 | 内部资产名 (m_Name)`**；当译名缺失或本地化表加载失败时，优雅降级显示 `[无译名] <m_Name>`。
- **原版值 vs 当前值高亮对比**：
  - 列表与编辑面板同步呈现 **`原版值 → 当前修改值`**；凡与原版不一致的条目与字段高亮标记，并提供「单条重置为原版」按钮。

### F3. 预设管理与批量快捷工具
- **内置预设**：
  1. `有限修改MOD (10月22日原版预设)`：精确包含原 MOD 的 5 个对象、10 项参数改动（仓库人口 `30→500`、大仓库零件 `40→20` & 人口 `180→1000`、起重机零件 `50→25` & 时间 `40→25`、无畏零件 `50→25` & 时间 `90→45`、基地车 MCV 电力 `100→500` & 人口 `60→200` & 储存 `600→1000`）。
  2. `原版默认数值 (Vanilla)`：清空全部改动。
- **自定义预设**：支持将当前改动保存至 `presets/*.json`、加载已有预设、以及导入/导出分享文件。
- **批量快捷工具（作用于当前筛选/页签结果）**：
  - **计算基准统一为原版值**：所有倍率按钮一律基于每个条目的**原版基准值**计算（例如连续两次点击 `×0.5` 结果仍为原版的 `50%`，不会意外累乘为 `×0.25`）。
  - **取整与保底规则**：
    - 整数字段（矿物/零件）：`max(1, round(vanilla * factor))`（原版为 `0` 的条目保持 `0`）；
    - 浮点时间字段：`max(0.5, round(vanilla * factor, 1))`（原版为 `0.0` 的条目保持 `0.0`）；
    - 人口提供：仅作用于原版 `limitProduce > 0` 的条目。
  - **操作保护与撤销**：执行前弹出确认对话框显示「将修改当前筛选出的 X 个条目」，并支持**一键撤销上一步批量操作 / 重置当前筛选条目为原版**。
  - **按钮布局**：
    - 主工具栏高频快捷项：**建造/研发时间 `×0.5`**、**矿物消耗 `×0.5`**、**零件需求 `×0.5`**、**人口提供 `×2` / `×5`**；
    - 低频特化项（全游戏仅 `y_WheeledDom_Unit` 与 `merc_DreadMK0_Unit` 2 个单位原版 `maxCount != 0`）：**解除数量限制 (`maxCount → 0`)** 收纳至「更多批量工具」下拉菜单中。

### F4. 一键应用、还原与启动联动
- **双进程占用检测**：写入或还原前同时检测 `Dust Front RTS.exe` 与 `Dust Front RTS 单机启动器.exe` 是否运行；若在运行则弹窗阻止并提示关闭游戏后再操作。
- **「应用修改到游戏」**：从干净的 `vanilla_backup` 读取字节并打好补丁，原子替换 `Dust Front RTS_Data\sharedassets0.assets`。
- **「应用并启动游戏」**：完成替换后自动拉起 `..\Dust Front RTS 单机启动器.exe`，且显式将子进程工作目录 (`cwd`) 设为游戏根目录。
- **「一键还原原版」**：校验版本一致后，将 `sharedassets0.assets.vanilla_backup` 原子还原回游戏目录。

---

# 第二部分：施工文档（技术架构与实施规范）

## 1. 技术栈、动态启动与运行环境

### 1.1 语言与依赖策略
- **运行时**：Windows 环境下安装任意 **Python 3.12+**（经确认本机已安装 Python 3.12 及 `tkinter` / `Tcl 8.6`）。
- **依赖策略**：**100% Python 标准库**（`tkinter`, `tkinter.ttk`, `csv`, `io`, `struct`, `json`, `hashlib`, `shutil`, `pathlib`, `subprocess`, `tempfile`, `datetime`, `unittest`），**零第三方 pip 包依赖**，无需联网安装。
- **工作区既有残留说明**：MOD 目录中原有失效的 `.venv/` 目录（指向旧的 Store stub 路径）将被完全忽略、不予使用；工具不依赖任何虚拟环境，后续可按需清理 `.venv/`。

### 1.2 `启动MOD配置器.bat` 动态探测规范
禁止在脚本中硬编码包含 Store 小版本号的路径（如 `...3.12.2800.0...`），防止系统自动更新后路径失效。批处理启动器必须遵循以下规范：
1. 头部启用 `@echo off`、`setlocal EnableDelayedExpansion` 与 `chcp 65001 >nul`（兼容工作区路径中的中文、空格及 `【】` 字符）。
2. 所有 `%~dp0` 与参数路径一律使用双引号包裹。
3. 按以下优先级依次探测可用的 Python 解释器：
   1. 若存在 `uv`，尝试 `uv python find 3.12`；
   2. 优先检查免版本号 Windows Store GUI 别名 `%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw3.12.exe`（若为可执行别名且能运行则隐藏黑框启动；失败时回退控制台解释器以输出错误信息）；
   3. 通配扫描 `%ProgramFiles%\WindowsApps\PythonSoftwareFoundation.Python.3.12_*\pythonw3.12.exe` 与 `python3.12.exe`；
   4. 检查 `py -3.12` / `py -3` / `PATH` 中的 `python`（仅当命令可真正执行 `-c "import tkinter"` 且非 Store 空引导桩时才采用）。
4. 若全部探测失败或 GUI 进程异常退出（非零退出码），自动切换同步运行并执行 `pause` 显示完整诊断报错，防止窗口一闪而过。

---

## 2. 目录规划与 Preset JSON Schema

### 2.1 文件结构规划
所有新增代码、预设与测试均存放在当前 MOD 工作区目录下，保持游戏目录整洁：

```text
灰烬战争-有限修改MOD【...】/
├── PRD与施工文档.md                 # 本文档
├── 启动MOD配置器.bat                # Windows 双击启动入口（动态探测 Python 3.12 并拉起 GUI）
├── presets/
│   └── limited_mod_1022.json        # 内置预设：10月22日有限修改MOD（5个对象、10项改动）
├── mod_configurator/
│   ├── __init__.py
│   ├── main.py                      # 程序入口（支持 CLI 参数校验与 GUI 启动）
│   ├── unity_assets.py              # Unity v22 解析器、外部引用/脚本校验、汉化提取与原地补丁引擎
│   ├── backup_manager.py            # 备份建立、SHA-256 诊断、跨版本防覆写保护、进程检测与原子替换
│   ├── preset_manager.py            # 预设加载/校验/保存、增量 Diff 计算与批量倍率处理
│   └── gui.py                       # tkinter/ttk 桌面可视化界面
└── tests/
    └── test_patcher.py              # 自动化单元测试、黄金 SHA-256 正反向校验与异常保护验证
```

### 2.2 预设 JSON Schema 规范 (`presets/*.json`)
预设以增量形式存储相对于原版基准的改动，跨小版本解耦，不记录 `PathID`：

```json
{
  "schema_version": 1,
  "name": "有限修改MOD (10月22日原版)",
  "description": "原版痛点微调：仓库与MCV增容、无畏与起重机降零件与加速建造",
  "target_game_version": "D-35-1",
  "changes": [
    {
      "script": "BuildConfig",
      "asset_name": "r_Barn_Build",
      "field": "limitProduce",
      "value": 500
    },
    {
      "script": "UnitConfig",
      "asset_name": "r_Dreadnought_Unit",
      "field": "timeCreation",
      "value": 45.0
    }
  ]
}
```

**Schema 加载与容错校验规则**：
- `schema_version`：必须为受支持整数（当前仅 `1`）。
- `changes`：必须为数组；每项必须包含字符串 `script`、`asset_name`、`field` 与数值 `value`。
- **字段白名单**：`script` 必须在 4 类允许脚本内；`field` 必须属于该脚本对应的可编辑字段白名单（**拒绝** `faction`、`onlyGlobalMinerals`、`skipLoadIfBlocked` 等只读或未开放字段）。
- **数值合法性**：导入时复用 2.3 节数值校验规则（类型、范围、`NaN/Inf` 拦截）。
- **跨版本缺项容错**：若未来游戏更新删除或改名了预设中的某个 `asset_name`，加载时将该条目记录进「未匹配警告列表」温和跳过并提示用户，**绝不崩溃或错误覆盖其他对象**。

---

## 3. 核心二进制协议与安全写入算法（`unity_assets.py` & `backup_manager.py`）

### 3.0 Unity SerializedFile v22 容器二进制格式摘要与护栏
所有 `.assets` 文件均按以下小/大端混合结构解析（基本字符串编码为 UTF-8）：
1. **文件头（前 20 字节）**：
   - `+0x00`: `legacy_meta_size` (`>I`), `legacy_file_size` (`>I`), **`format_version`** (`>I`), `legacy_data_off` (`>I`)
   - `+0x10`: **`endian`** (`B`, 1 字节) + 3 字节保留
2. **v22 扩展头（`+0x14`~`+0x2F`，共 28 字节，当 `format_version >= 22`）**：
   - `meta_size` (`>I`), `file_size` (`>Q`), **`data_off`** (`>Q`), `unknown` (`>Q`)
3. **元数据头部与强校验护栏**：
   - `unity_version`：以 `\x00` 结尾的 ASCII/UTF-8 C-String（如 `2020.3.3f1`）；
   - `target_platform` (`<i`)、`enable_type_tree` (`<?`, 1 字节布尔)；
   - **格式护栏**：解析开始前必须断言 **`format_version == 22`**、**`endian == 0`**（小端数据区）、**`enable_type_tree == False`** 且 `file_size == actual_len(data)`。任一不满足立即抛出异常只读中止，绝不猜测偏移写入。
4. **类型表 `m_Types`**：
   - `type_count` (`<i`)，循环读取 `type_count` 项：`class_id` (`<i`)、`is_stripped` (`<B`)、`script_type_index` (`<h`)；若 `class_id == 114` 额外读取 16 字节 `script_id`；最后读取 16 字节 `old_type_hash`。
5. **对象表 `m_Objects`**：
   - `obj_count` (`<i`)，游标**向上对齐到 4 字节边界** `(pos + 3) & ~3`；
   - 每项固定 24 字节（`<qQII`）：`path_id` (`int64`)、`byte_start` (`uint64`)、`byte_size` (`uint32`)、`type_index` (`uint32`)；对象原始数据绝对偏移为 `data_off + byte_start`。
6. **本地脚本表 `m_ScriptTypes`**：
   - `script_count` (`<i`)，每项读取 `file_id` (`<i`) -> 游标向上对齐 4 字节 -> `path_id` (`<q`)。
7. **外部依赖引用表 `m_Externals`**（`fileID` 从 `1` 开始编号，对应第 `i` 项）：
   - `ext_count` (`<i`)，循环读取：`temp_empty` (C-String)、`guid` (16B)、`ext_type` (`<i`)、`asset_path` (C-String)。

### 3.1 动态脚本类型与外部引用校验
1. 从 `sharedassets0.assets` 的 `m_Externals` 表中动态查找 `asset_path` 末尾文件名（忽略路径分隔符与大小写）等于 `"globalgamemanagers.assets"` 的条目，记其 1-based 索引为 **`ggm_file_id`**（当前 D-35-1 中为 `1`）；若找不到则中止解析。
2. 按 3.0 格式解析 `Dust Front RTS_Data\globalgamemanagers.assets` 中所有 `ClassID == 115` (`MonoScript`) 对象：
   - 依次读取：`m_Name` (`AlignedString`) -> `m_ExecutionOrder` (`<i`) -> `m_PropertiesHash` (`16B`) -> `m_ClassName` (`AlignedString`) -> `m_Namespace` (`AlignedString`) -> `m_AssemblyName` (`AlignedString`)。
3. **程序集与类名双校验**：仅当 `m_AssemblyName.removesuffix(".dll") == "Assembly-CSharp"` 且 `m_ClassName` 属于目标 4 个类名之一时，记录 `script_pid_to_class[pid] = m_ClassName`（当前 D-35-1 中对应 `BuildConfig=960`、`UnitConfig=1400`、`UpgradeConfig=1082`、`TacticalAbilityConfig=1341`）。
4. **对齐字符串读取规则 (`AlignedString`)**：读取 `length (<i)`，截取 `length` 字节按 UTF-8 解码，游标再向上 4 字节对齐 `(p + 3) & ~3`。

### 3.2 中文名称与描述映射（标准库 CSV + 优雅降级）
1. 解析 `Dust Front RTS_Data\resources.assets` 中 `ClassID == 49` (`TextAsset`) 且 `m_Name == "Localization_DUST_FRONT - Main"` 的对象（`AlignedString name` 后紧跟 `AlignedString text`）。
2. 使用 Python 标准库 `csv.reader(io.StringIO(csv_text))` 解析表头 `Keys,Russian,English`（兼容带双引号、内含逗号或多行换行的描述文本），建立 `key -> 中文文本（第 3 列）` 字典（如 `build-barn -> 仓库`、`unit-dreadnought -> 无畏舰`）。
3. **容错降级**：若 `resources.assets` 丢失、未找到目标 `TextAsset`、或特定对象的 `nameKey` 为空/未命中词典，不报错中断，界面显示 `[无译名] <m_Name>`。

### 3.3 配置对象字段偏移定位与越界校验公式（已实测 176/176 零失败）
遍历 `sharedassets0.assets` 中每个对象：必须同时满足 **`class_id == 114`**、`m_GameObject == (0, 0)` 且 **`m_Script == (ggm_file_id, script_path_id)`**（其中 `script_path_id in script_pid_to_class`）。
对命中对象以对象起始位置 `obj_abs = data_off + obj.byte_start` 为基准解析：
1. **MonoBehaviour 头部（以 `obj_rel = 0` 起算）**：
   - `+0x00`: `m_GameObject` (`int32 fileID, int64 pathID`, 12B)
   - `+0x0C`: `m_Enabled` (`uint8` + 3B 对齐 = 4B)
   - `+0x10`: `m_Script` (`int32 fileID, int64 pathID`, 12B)
   - `+0x1C`: `m_Name` (`AlignedString`)
2. **若脚本为 `BuildConfig` / `UnitConfig` / `UpgradeConfig`（继承自 `ConfigBase`）**：
   - 跳过 `configLink (12B) + icon (12B) + iconTex (12B) + genIcon (4B)` = **40 字节**；
   - 读取 `info.nameKey (AlignedString)` 与 `info.descKey (AlignedString)`；
   - 当前位置记为 **`price_rel`**，紧接着即为 `PriceResources` 定长字段区：
     - `price_rel + 0x00`: `minerals` (`<i`, int32)
     - `price_rel + 0x04`: `energyPrice` (`<i`, int32)
     - `price_rel + 0x08`: `limitPrice` (`<i`, int32)
     - `price_rel + 0x0C`: `gears` (`<i`, int32)
     - `price_rel + 0x10`: `timeCreation` (`<f`, float32)
     - `price_rel + 0x14`: `onlyGlobalMinerals` (`<i`, 只读)
     - `price_rel + 0x18`: `energyProduce` (`<i`, int32)
     - `price_rel + 0x1C`: `limitProduce` (`<i`, int32)
     - `price_rel + 0x20`: `siloProduce` (`<i`, int32)
     - `price_rel + 0x24`: `skipLoadIfBlocked` (`<i`, 只读)
     - `price_rel + 0x28`: `requiredConfigs.count` (`<i`, 记为 $N$，校验 $0 \le N \le 100$)
   - 对 `BuildConfig` 与 `UnitConfig`（继承自 `RtsObjectConfig`），跳过 `0x2C + N * 12` 字节后：
     - `+0x00`: `faction` (`<i`, **严格只读**，`0=中立, 1=帝国, 2=变种人, 3=机器人, 4=叛军`)
     - `+0x04`: `maxCount` (`<i`, int32)
3. **若脚本为 `TacticalAbilityConfig`**：
   - 跳过 `fantomType (4B) + icon (12B)` = **16 字节**；
   - 读取 `info.nameKey (AlignedString)` 与 `info.descKey (AlignedString)`；
   - 当前位置即为 **`price_rel`**（同上解析 `PriceResources` 及 `requiredConfigs` 的 $N \times 12$ 字节）；
   - 跳过 `0x2C + N * 12` 字节后：
     - `+0x00`: `coolDownInStart` (`<i`, 布尔 `0/1`)
     - `+0x04`: `useInFog` (`<i`, 布尔 `0/1`，**开放可编辑**)
     - `+0x08`: `coolDown` (`<f`, float32, 秒)
4. **字段边界保护校验**：
   - 每个已解析可编辑字段都必须满足 **`0 <= field_rel_offset` 且 `field_rel_offset + 4 <= obj.byte_size`**，且 `data_off + obj.byte_start + obj.byte_size <= len(data)`；任何越界即判定结构变化，拒绝写入该资产。

### 3.4 安全写入、备份保护与还原流程（`backup_manager.py`）
1. **双进程占用检测**：
   - 使用 `tasklist /FO CSV /NH` 扫描进程，同时检查 **`Dust Front RTS.exe`** 与 **`Dust Front RTS 单机启动器.exe`**；若任一运行则阻断写入或还原并提示先关闭游戏/启动器。
2. **三态 SHA-256 备份管理状态机**：
   - **常量指纹**：
     - 已知原版 D-35-1：`0B81412888B764991324E531949809786C3CB808C16FD3BB9902AD528E2B76ED`
     - 已知 10/22 MOD：`A20E9977E1714B02C34F4C53B9D13C16D6CD6BC2D849C8D4DA1D7787D67F5376`
   - **场景 A（尚无 `vanilla_backup`）**：
     - 若当前游戏文件为 `0B814128...`：直接复制为 `sharedassets0.assets.vanilla_backup` 并生成 `vanilla_backup.meta.json`。
     - 若当前游戏文件为 `A20E9977...`（用户此前已手动覆盖 MOD）：解析对象并将 5 个对象 / 10 个改动字段回填原版数值，验证产物 SHA-256 精确等于 `0B814128...` 后存为 `vanilla_backup`。
     - 若当前游戏文件为其他未知 SHA-256：状态显示 `🟡 未知版本/外部修改基准（需确认）`，弹窗要求用户明确确认当前文件确实是目标原版（而非其他第三方 MOD）后，才允许以此创建 `vanilla_backup`。
   - **场景 B（已存在 `vanilla_backup` 与 `vanilla_backup.meta.json`）**：
     - 每次读取、应用、还原前比对当前 `sharedassets0.assets` 的 SHA-256：
       - 命中 `meta.vanilla_sha256`、`meta.last_applied_sha256` 或已知旧 MOD `A20E9977...`：安全放行。
       - **全部不命中**：判定游戏文件已被更新或被外部程序替换！**立即阻断写入与还原**，弹窗引导用户确认：将旧 `vanilla_backup` 及 `.meta.json` 归档为 `*.vanilla_backup.<YYYYMMDD_HHMMSS>.old`，再基于当前新版文件重建基准（不丢失任何历史文件，绝不发生旧版本覆写新版）。
3. **原地补丁与原子写入**：
   - 将干净的 `sharedassets0.assets.vanilla_backup` 读入内存 `bytearray`（约 73 MB）。
   - 对每个改动字段计算绝对偏移 `abs_offset = data_off + obj.byte_start + field_rel_offset`，校验原版数值/边界后使用 `struct.pack_into('<i', ...)` 或 `struct.pack_into('<f', ...)` 原地覆写 4 字节。
   - 先写入同目录下的临时文件 `Dust Front RTS_Data\sharedassets0.assets.<pid>.tmp`，校验写入字节长度等于原文件长度、前 20 字节与 v22 魔数无误并计算新 SHA-256。
   - 在 `try / finally` 保护下执行 `os.replace(tmp_path, target_path)` 原子覆盖，同时更新 `vanilla_backup.meta.json` 中的 `last_applied_sha256`；若因杀毒软件占用或权限问题抛出 `PermissionError / OSError`，弹窗给出清晰解锁建议并在 `finally` 中自动清理残留 `.tmp`。

---

## 4. 施工步骤与验收标准

### 4.1 施工顺序
1. **Step 1：实现核心解析、备份状态机与预设引擎**
   - 编写 `mod_configurator/unity_assets.py`、`backup_manager.py`、`preset_manager.py` 与 `presets/limited_mod_1022.json`。
2. **Step 2：编写并运行自动化验收测试 (`tests/test_patcher.py`)**
   - 必须全部通过 4.2 节全部 6 项黄金与安全验收指标（测试过程只读写临时目录，不篡改用户现有游戏文件）。
3. **Step 3：实现 GUI (`mod_configurator/gui.py`)、`main.py` 与启动脚本 (`启动MOD配置器.bat`)**
   - 验证中文界面渲染、搜索、阵营/修改过滤、重名消歧展示、双层字段折叠、预设保存加载、基于原版基准批量倍率与撤销、以及 `.bat` 启动路径探测。

### 4.2 验收标准（全项强制通过）
1. **验收指标 1（全量解析覆盖率）**：对 `sharedassets0.assets` 全量解析 `63 建筑 + 66 单位 + 40 升级 + 7 战术 = 176 项`，`0` 报错，176 项 `m_Script.fileID == ggm_file_id`，全部可调字段偏移均未越界，`Localization_DUST_FRONT - Main` 中文名正确匹配（且 4 个空 `nameKey` 对象优雅降级）。
2. **验收指标 2（正向逐字节黄金校验）**：以游戏目录原版 `sharedassets0.assets`（`0B814128...`）为输入，应用 `presets/limited_mod_1022.json`，输出文件的 SHA-256 必须与当前 MOD 目录下的 `sharedassets0.assets`（**`A20E9977E1714B02C34F4C53B9D13C16D6CD6BC2D849C8D4DA1D7787D67F5376`**）**100% 相同（76,600,076 字节零误差）**。
3. **验收指标 3（反向重建黄金校验）**：以当前 MOD 文件（`A20E9977...`）作为首次输入的临时游戏文件，触发原版基准自动重建逻辑，产出的 `vanilla_backup` SHA-256 必须精确等于原版 D-35-1 指纹（**`0B81412888B764991324E531949809786C3CB808C16FD3BB9902AD528E2B76ED`**）。
4. **验收指标 4（跨版本更新保护校验）**：在临时目录模拟已存在 `D-35-1` 备份后，将游戏目录 `sharedassets0.assets` 替换为内容不同的“假想新版文件”；验证工具在应用补丁与还原操作前均**成功拦截**、不覆盖新版文件，且归档旧备份后可安全重建新基准。
5. **验收指标 5（旧 `.bak` 隔离校验）**：在存在旧版 `.bak` 文件的临时目录中完整运行备份、打补丁与还原流程，断言旧 `.bak` 文件的内容与修改时间自始至终保持 **0 字节改动**。
6. **验收指标 6（边界与异常防护校验）**：覆盖非法负数/`NaN`/超出 `int32` 输入拦截、原版 `timeCreation > 0` 禁止写入 `<= 0`、只读字段 `faction` 拒绝预设写入、损坏预设 JSON 安全报错、未知 `asset_name` 温和跳过、模拟进程运行中拦截写入、以及原子写失败后 `.tmp` 文件自动清理。
