# 《灰烬战争 (Dust Front RTS Demo)》外部可视化 MOD 配置与补丁器 — V2 迭代 PRD 与施工文档

> **文档状态**：基于 `sharedassets0.assets`、`globalgamemanagers.assets`、`resources.assets` 与 IL2CPP `global-metadata.dat` 全量实测探查编制，涵盖 **「必做项：敌我分类与防误触」** 与 **「第二梯队：本体战斗 / 机动 / 视野 / 经济后勤组件修改」**；全部新增二进制协议均已对 D-35-1 原版资产完成 100% 只读解析验证。

---

# 第一部分：V2 PRD（产品需求文档）

## 1. 迭代目标、兼容性与版本边界

### 1.1 核心目标与 V1 继承约束
- **保持 V1 零风险基座**：依然零代码注入 / 不改 DLL、100% Python 3.12 标准库零第三方依赖、仅原地覆写 `Dust Front RTS_Data\sharedassets0.assets` 中的定长 4 字节字段（保持 `76,600,076` 字节文件尺寸与偏移结构不变），100% 兼容 `resources.assets` 中文汉化。
- **保留全部 V1 安全机制**：继续严格忽略旧版 `10/16` `.bak`，复用 `vanilla_backup.meta.json` 状态机、跨版本更新 `.old` 归档拦截、双进程占用检测及原子替换。
- **Presets 向下兼容承诺**：
  - V2 **100% 兼容导入所有 V1 预设**（`schema_version: 1`，包括内置 `presets/limited_mod_1022.json`）；
  - V2 导出新预设升级为 **`schema_version: 2`**（同时保留 V1 的 `changes` 数组结构并扩展挂载组件与地图资源字段）。

### 1.2 V2 范围边界（Out of Scope）
- **暂不包含**第一梯队未选中的模块（`BlueprintConfig` 20 个蓝图改装件、`AbilityConfig` 26 个单位主动技能、`RtsObjectConfig.maxModificators` 等）以及第三梯队（跨文件修改 `level1` 的全局人口上限 `ResourcesTeams.maxGameLimit`、修改 `resources.assets` 的 `RanksConfig` 经验表），上述项继续留作 V3 备选。
- **仅修改静态序列化数值**：如 `Harvester.mining` 与 `Harvester.timeMining` 等 Unity 未序列化的 C# 运行时私有字段不存在于 `.assets` 文件中，V2 坚决不做虚标。

---

## 2. 功能模块设计

### F5（必做项）：敌我实战归属分类与批量防误触保护

#### 2.1 自动修正游戏原版归属标错与缺失
经对 176 项配置资产交叉核查，游戏原版 `faction` 字段存在标错与缺失（例如叛军精炼厂 `y_Refinery_Build` 标成了帝国、帝国战壕 `r_Trench_Build` 标成了中立、7 个战术支援没有 `faction` 字段、中立阵营混杂玩家雇佣兵与地图卡车）。V2 引入**「实战归属 (`Affiliation`)」**字段，统一覆盖全游戏配置：

| 实战归属分类 | 包含对象清单 | 数量统计 | 原版修正说明 |
| :--- | :--- | :---: | :--- |
| **`我方·帝国`** | `r_*` 建筑（含 `r_Trench_Build`，剔除 `y_Refinery_Build`）、`r_*` 单位、全部 40 项 `r_*` 科技升级、5 项 `r_*` 战术支援 | **96**（23 建筑 + 28 单位 + 40 科技 + 5 战术） | 修正 `r_Trench_Build`（原标中立→我方·帝国）；排除错标的 `y_Refinery_Build`；补充 5 个 `r_*` 战术支援归属 |
| **`我方·雇佣兵`** | 6 个 `merc_*` 玩家可雇佣单位（Desolator 重坦、Luch 激光坦克、掠夺者、TV 机甲、Rafa 装甲车、蝎子火炮） | **6**（6 单位） | 从原版「中立/雇佣兵」中剥离可雇佣兵种，避免与地图物件混改 |
| **`敌方·变种人`** | `g_*` 建筑与单位 + 2 项变种人战术支援（`TacticalInfuse`、`mutantBirdBombardment`） | **27**（12 建筑 + 13 单位 + 2 战术） | 补充 2 项变种人技能归属，避免把敌方 AI 空袭冷却改短 |
| **`敌方·叛军`** | `y_*` 建筑（含 `y_Refinery_Build`）与 `y_*` 单位 | **18**（9 建筑 + 9 单位） | 将错标为帝国的 `y_Refinery_Build` 准确划归叛军 |
| **`敌方·机器人`** | `b_*` 建筑与单位 | **13**（6 建筑 + 7 单位） | 均无 `mainPrefab`，属于 Demo 占位配置 |
| **`中立/地图物件`** | 废弃矿场、医疗站、掩体、民用建筑、废墟、中立卡车（`CargoTruck*`）及地图资源点（7 标准矿脉 + 2 独立油井） | **25**（13 建筑 + 3 单位 + 9 地图资源点*） | 剔除 `r_Trench_Build` 与 6 个雇佣兵，独立出地图公共资源 |

> *注：地图资源点页签独立统计为 `9` 项（7 个标准 192B 矿脉 + 2 个未绑定配置的独立 `OilPump`；另 2 个 `OilPump` 已直接关联至 `r_MassFabricator_Build` 与 `OilPump_Build`）。*

#### 2.2 默认仅看我方、全页签筛选与防误触警报
1. **默认锁定我方**：工具启动时，顶部归属筛选**默认选中 `我方（帝国）`**；同时支持切换为：`我方（帝国）` / `我方 + 雇佣兵` / `敌方（全部敌方）` / `敌方·变种人` / `敌方·叛军` / `敌方·机器人` / `中立/地图物件` / `全部（含敌我）`。
2. **全配置页签生效**：归属筛选框在 **建筑 / 单位 / 科技升级 / 战术支援** 全部 4 个配置页签均可用（不再对战术支援禁用），彻底隔离玩家与敌方战术支援技能。
3. **实时作用域指示与警示条**：
   - 批量工具栏旁常驻显示作用域标签，例如：`当前批量作用范围：【我方（帝国）· 单位配置】共 28 项`。
   - 一旦当前筛选列表包含任何**敌方对象**，工具栏立即亮起醒目橙红警告：`⚠️ 当前范围包含敌方对象 (X 项)，执行批量修改将同时影响敌方！`
4. **弹窗分组统计 + 双向批量倍率**：
   - 点击任何批量按钮后，确认弹窗必须按**「我方 X 项 / 敌方 Y 项 / 中立 Z 项」**明细展示，若含敌方则显式加粗警示二次确认。
   - 新增批量工具（一律基于原版基准值计算并支持一键撤销）：
     - 经济与时间双向：`建造/研发/冷却时间 ×0.5` / `×2`、`矿物消耗 ×0.5` / `×2`、`零件需求 ×0.5`、`人口提供 ×2` / `×5`
     - 战斗与机动双向：`最大血量 ×2` / `×0.5`、`武器伤害 ×2` / `×0.5`、`移动速度 ×1.5` / `×0.5`（可在「更多批量工具」或工具栏按需调用，方便**加强我方**或切至敌方阵营后**削弱/加强敌方 AI**）

---

### F6（第二梯队）：单位/建筑本体战斗、机动、视野、经济与后勤修改

#### 2.3 10 类实测可改组件清单（全部位于 `sharedassets0.assets`）

1. **生命与护甲（`HP`，覆盖 107/129 个配置共 110 个 `HP` 实例）**
   - `maxHp`（最大血量，int32，**底层自动联动写入 `curHp`**，防止单位出生时不满血）
   - `maxExtraHp`（额外护盾/装甲血量，int32）
   - `sidesArmore`（启用前后方向分面护甲，bool 勾选 `0/1`）
   - `frontArmore`（正面护甲，int32）、`rearArmore`（背面护甲，int32）
   - `fireResist` / `gasResist` / `areaResist`（火焰 / 毒气 / 爆炸范围抗性，float32，**允许原版负数弱点如步兵 `-0.8`**，范围 `[-2.0, 1.0]`）
   - *注：`hpType`（护甲类型枚举）设为只读。*

2. **武器火力、射程与射速（`AttackComponent` 5 大子类全覆盖，共 106 个武器挂载实例）**
   - 统一兼容 `AutoAttack_MG`、`AutoAttack_Cannon`、`AutoAttack_Projectile`、`AutoAttack_Flamer`、`AutoAttack_Laser` 全部 5 类武器。
   - **武器本体属性**：`MoveAttack`（允许移动射击，bool）、`SpeedTower`（炮塔转向速度，float32）、`fogCheck`（无视战争迷雾/需探测视野开关，bool）、`minRange`（最小射程，float32）、`range`（基础射程，float32）、`addRange`（**额外射程增量**，float32，可为负值，例如界面明示：`总射程 ≈ 基础 range + addRange`）、`coolDownShot`（攻击冷却间隔，float32 秒）。
   - **内嵌 `Weapon` (`gun`) 伤害与溅射属性**：`gun.range`（爆炸/溅射半径，float32）、`gun.cleanDamage`（纯净/穿透保底伤害，int32）、`gun.damageToVehicle`（对载具伤害，int32）、`gun.damageToInfantry`（对步兵伤害，int32）、`gun.damageToBuild`（对建筑伤害，int32）。
   - **多武器交互支持**：如 `r_Bronenosets_Unit`（重装突破坦克）或 `r_MCV_BuildMobile`（机动建造车）挂载多个炮塔时，右侧提供**武器下拉选择器**（显示挂载路径如 `attack` / `siegeMode` / `mg`），并提供**「将该武器调整同步至同单位全部武器」**或批量工具自动覆盖全部武器。

3. **机动性（`MovePattern`，覆盖 `TankPattern` / `CarPattern` / `SmoothPattern` 共 50 个可移动单位）**
   - `clearSpeed`（移动速度，float32）、`angularSpeed`（车身转向角速度，float32）、`acceleration`（加速度，float32）。

4. **视野半径（`UnitComponent` 109 个配置 + `FogOfWarUnit` 2 个飞行/特殊单位）**
   - `UnitComponent.fowRadius`（基础开雾半径，float32，原版统一 `12.0`）
   - `FogOfWarUnit.radius`（大视野组件，float32，仅 `r_Zeppelin_Unit` 与 `merc_DreadMK0_Unit` 挂载，原版 `16.0`）

5. **采矿车（`Harvester`，2 项：帝国 `r_Harvester_Unit` `250`、变种人 `g_Harvester_Unit` `550`）**
   - `supplyMax`（单次矿仓最大容量，int32）、`onlyNormalMinerals`（仅采集普通矿石限制，bool）。

6. **产矿建筑与油井（`OilPump`，共 4 项：2 项关联建筑配置 + 2 项独立地图物件）**
   - 已关联配置：`r_MassFabricator_Build`（质量制造机，`cooldown=1.0, addRes=5`）、`OilPump_Build`（废弃矿场，`cooldown=2.5, addRes=5`）。
   - 独立地图组件（归入「地图资源点」页签）：`CaptureTerritory`（`cooldown=1.0, addRes=5`）、`SiloTower_midStrat`（`cooldown=1.0, addRes=10`）。
   - 可调字段：`cooldown`（产矿周期，float32 秒）、`addRes`（每次产矿量，int32）。

7. **矿脉资源点（`Mineral`，7 项标准 `192B` 矿脉 Prefab，排除 `36B` `MineralPrefabDeploy`）**
   - 可调字段：`minerals`（初始/储量数值，int32，7 个实例原版均为 `2000`）。
   - 在「地图资源点」页签提供**「一键修改全部 7 个标准矿脉储量」**快捷操作（避免 6 个同名 `MineralPrefab` 逐个手动点击）。

8. **运兵车与碉堡（`Bunker`，共 6 个关联对象：`r_Bunker_Build`、`r_Trench_Build`、`r_BMP_Unit`、`r_BTR_Unit`、`CargoTruckBus_Unit`、`HeavyCover_Build`）**
   - 可调字段：`maxUnits`（最大容纳小队数，int32）、`addVision`（驻军额外视野加成，int32）、`canShootback`（允许舱内还击，bool）。

9. **医疗与维修组件（`HealRange` 9 项 + `Regeneration` 5 项）**
   - `HealRange`（医疗站、修理台、基地车/起重机自动修理等）：`coolDownScan`（治疗扫描间隔，float32 秒）、`range`（作用半径，int32）、`heal`（每次治疗/修复血量，int32）。
   - `Regeneration`（MCV、重坦、前哨站等被动回血）：`RegenHP`（每次回复血量，int32）、`timer`（回血周期，float32 秒）。

10. **生产队列加速与折扣（`BuildComponent`，17 个可生产建筑/移动基地单位）**
    - `discount`（造兵/建筑折扣比例 `0.0~0.95`，float32，原版 `0.0`）
    - `timeMultiplier`（队列生产速度倍率 `0.1~20.0`，float32，原版 `1.0`）
    - `maxBuildings`（同时队列/建筑限制数，int32）。

#### 2.4 V2 界面布局升级方案
- **顶层 5 大页签**：`建筑配置 (63)` | `单位配置 (66)` | `科技/学说升级 (40)` | `战术支援技能 (7)` | `地图资源点 (9)`
- **左侧列表**：保留三列消歧展示（`中文名称 | 实战归属 | 内部资产名 (m_Name) | 改动摘要`），切换页签时 `地图资源点` 固定显示 `中立/地图物件`。
- **右侧属性面板升级为 4 个子页签**（当选中无 Prefab 的 20 个占位/静态对象时，战斗/机动子页签显示明确提示「该对象未关联战斗 Prefab (`mainPrefab=0`)」）：
  1. **`经济与建造`**：保留 V1 全部 `PriceResources` / `maxCount` / `coolDown` / `useInFog`（含主要/高级分层折叠）。
  2. **`生命与护甲`**：展示挂载的 `HP` 组件（含多子体支持如 `AATower_midStrat`）及 `Regeneration` 被动回血。
  3. **`武器火力`**：子武器下拉框 + 当前武器 12 项伤害/射程/射速参数 + `MoveAttack` / `fogCheck` 开关 + 同单位全部武器快捷倍率按钮。
  4. **`机动/视野/后勤`**：动态展示该对象挂载的 `MovePattern`、`UnitComponent.fowRadius`、`FogOfWarUnit`、`Harvester`、`OilPump`、`Bunker`、`HealRange`、`BuildComponent` 参数（未挂载的模块自动隐藏，保持面板清爽）。

---

# 第二部分：V2 施工文档（二进制协议与技术规范）

## 1. 实战归属分类判定规则（纯只读静态映射）

在 `unity_assets.py` 中新增常量与确定性判定函数 `resolve_affiliation(script, asset_name, raw_faction)`：
1. **已明确雇佣兵**：`MERC_ASSET_NAMES = {"merc_DreadMK0_Unit", "merc_LaserTank_Unit", "merc_Marauder_Unit", "merc_Mechbot_Unit", "merc_Rafa_Unit", "merc_Scorpion_Unit"}` -> `"player_merc"`（`我方·雇佣兵`）。
2. **明确敌我战术支援**：`ENEMY_TACTICAL_MUTANTS = {"TacticalInfuse", "mutantBirdBombardment"}` -> `"enemy_mutants"`；其余 `r_*` 战术支援 -> `"player_empire"`（`我方·帝国`）。
3. **科技升级**：`UpgradeConfig` 当前全为 `r_*` -> `"player_empire"`。
4. **前缀纠偏 + 原版 `faction` 兜底**（仅对 `BuildConfig` / `UnitConfig`）：
   - `asset_name.startswith("r_")` -> `"player_empire"`（自动把 `r_Trench_Build` 归回我方·帝国）
   - `asset_name.startswith("y_")` -> `"enemy_rebels"`（自动把错标的 `y_Refinery_Build` 归回敌方·叛军）
   - `asset_name.startswith("g_")` -> `"enemy_mutants"`
   - `asset_name.startswith("b_")` -> `"enemy_robots"`
   - `asset_name in MERC_ASSET_NAMES` -> `"player_merc"`
   - 其余再按 `raw_faction` 兜底映射（`0 -> "neutral"`，`1 -> "player_empire"`，`2 -> "enemy_mutants"`，`3 -> "enemy_robots"`，`4 -> "enemy_rebels"`）。
5. **归属筛选项枚举**：
   - `player_empire` (`我方（帝国）`, **GUI 启动默认**)
   - `player_all` (`我方 + 雇佣兵`)
   - `enemy_all` (`敌方（全部敌方）`)
   - `enemy_mutants` (`敌方·变种人`)
   - `enemy_rebels` (`敌方·叛军`)
   - `enemy_robots` (`敌方·机器人`)
   - `neutral` (`中立/地图物件`)
   - `all` (`全部（含敌我）`)

---

## 2. `RtsObjectConfig → mainPrefab` 与 Prefab 组件树遍历协议

### 2.1 `mainPrefab` 定位公式（已在 129/129 `BuildConfig + UnitConfig` 校验通过）
在 `ConfigItem` 解析完成 `faction (+0x00)` 与 `maxCount (+0x04)` 后，紧接 `after_max = after_req + 8`：
- `+0x00`: `prodType` (`<i`)
- `+0x04`: `isRelevant` (`<i`)
- `+0x08`: `isProduction` (`<i`)
- `+0x0C`: `sizeFixed` (`<i`)
- `+0x10`: `sizeRadius` (`<f`)
- `+0x14`: `setHeightOnStart` (`<i`)
- `+0x18`: `maxModificators` (`<i`)
- `+0x1C`: `upgrades.count` (`<i`, 记为 $U$，校验 $0 \le U \le 50$)
- 跳过 `0x20 + U * 12` 字节后即到达 **`mainPrefab`**（12B PPtr: `mp_fid (<i)`, `mp_pid (<q)`）。
- 若 `mp_fid == 0` 且 `mp_pid == 0`：记为无 Prefab 关联对象（实测共 20 项：13 个 `b_*` 机器人占位与 7 个地图静态物件）。

### 2.2 确定性深度优先组件树遍历与跨版本唯一键
1. 若 `objs_by_pid[mp_pid].class_id == 1` (`GameObject`)，根节点 `root_go_pid = mp_pid`；若为 `class_id == 114` (`MonoBehaviour`，如指向根上的 `UnitComponent`)，取其头部前 12 字节 `m_GameObject.pathID` 作为 `root_go_pid`。
2. **`GameObject (ClassID=1)` 二进制读取**：
   - `comp_count (<i)` -> 读取 `comp_count` 项 `(fid <i, pid <q)`（仅跟踪 `fid == 0` 本文件组件）-> 跳过 `m_Layer (4B)` -> 读取 `m_Name (AlignedString)`。
3. **`Transform (ClassID=4)` 二进制读取**：
   - `+0x00`: `m_GameObject (12B PPtr)` -> 取 `go_pid`
   - 跳过 `m_LocalRotation (16B) + m_LocalPosition (12B) + m_LocalScale (12B)` = 52B 起始处读取 `children_count (<i)`，按顺序读取 `children_count` 项 `(fid <i, pid <q)` 子 `Transform`。
4. **跨版本稳定标识键（ComponentKey）**：
   - 从根节点起按子节点声明顺序执行迭代式 **DFS（`reversed` 入栈保持正序弹出）**，以 `/` 拼接相对路径 `go_rel_path`（根节点为 `""` 或根 `GameObject.m_Name`；推荐以相对路径记录，根为 `"<root>"`，子节点如 `"<root>/attack"`、`"TowerLerp/mg"`）。
   - 由于 `r_Avanpost_Build` 等单位存在同一子路径下多个同名组件（如 2 个 `turretMg` 的 `AutoAttack_MG`），按遍历顺序对相同 `(config_script, config_asset_name, comp_class, go_rel_path)` 分配从 `0` 开始的 **`occ_index`**。
   - **唯一组件键**：`(config_script, config_asset_name, comp_class, go_rel_path, occ_index)`；完全脱离 `PathID`，版本小更新后依然稳定命中！
5. **独立地图资源点对象（WorldItemKey）**：
   - 收集所有 `ClassID == 114` 的 **`Mineral`**（仅保留 `body_len >= 100` 的标准 `192B` `Mineral` 矿脉，排除 `36B` 的 `MineralPrefabDeploy`，共 7 项）与未挂载在任何 `BuildConfig/UnitConfig` 下的 **`OilPump`**（共 2 项：`CaptureTerritory`、`SiloTower_midStrat`）。
   - 按所在 `GameObject` 的 `m_Name` + 同名出现顺序（仅按组件稳定特征或文件中的 `go_name` + 顺序索引 `occ_index`）分配键 `("world", comp_class, go_name, occ_index)`。

---

## 3. 第二梯队 10 类组件实测二进制偏移表（全部已 100% 校验）

对任意 `ClassID == 114` 且 `m_Script.fileID == ggm_file_id` 的组件对象：
- 先解析头部：`m_GameObject (12B) + m_Enabled (4B) + m_Script (12B) + m_Name (AlignedString)`，记对齐后结束位置为 **`body_abs`**（记 `body_len = obj_end - body_abs`）。
- 所有偏移均以 **`body_abs`** 为 `+0x00`，写入前一律严格断言 **`0 <= body_rel` 且 `body_abs + body_rel + 4 <= obj_end`**。

| 组件脚本类 (`m_ClassName`) | 实测实例数与长度特征 | 字段名 & 偏移（相对 `body_abs`） | 类型与说明 |
| :--- | :--- | :--- | :--- |
| **`HP`** | **110/110** Linked<br>固定 `body_len == 100` | `+0x0C`: `hpType`（只读）<br>`+0x10`: `maxHp`（**联动同步写 `+0x14 curHp`**）<br>`+0x18`: `maxExtraHp`<br>`+0x20`: `sidesArmore`<br>`+0x24`: `frontArmore`<br>`+0x28`: `rearArmore`<br>`+0x2C`: `fireResist`<br>`+0x30`: `gasResist`<br>`+0x34`: `areaResist` | `<i` (只读)<br>`<i` (0~999999)<br>`<i` (0~999999)<br>`<i` (bool 0/1)<br>`<i` (0~999999)<br>`<i` (0~999999)<br>`<f` (-2.0~1.0)<br>`<f` (-2.0~1.0)<br>`<f` (-2.0~1.0) |
| **`AutoAttack_MG`** / **`_Cannon`** / **`_Projectile`** / **`_Flamer`** / **`_Laser`** | **106/106** Linked<br>基类 `AttackComponent` 公共头部均相同（`body_len >= 256`） | `+0x30`: `MoveAttack`<br>`+0x6C`: `SpeedTower`<br>`+0xB4`: `fogCheck`<br>`+0xB8`: `minRange`<br>`+0xBC`: `range`<br>`+0xC0`: `addRange`<br>`+0xD4`: `coolDownShot`<br>`+0xE4`: `gun_range`（爆炸溅射半径）<br>`+0xE8`: `gun_cleanDamage`<br>`+0xEC`: `gun_damageToVehicle`<br>`+0xF0`: `gun_damageToInfantry`<br>`+0xF4`: `gun_damageToBuild` | `<i` (bool 0/1)<br>`<f` (0~5000)<br>`<i` (bool 0/1)<br>`<f` (0~500)<br>`<f` (0~500)<br>`<f` (-9.5~500)<br>`<f` (0.05~60, 若原0允许0)<br>`<f` (0~100)<br>`<i` (0~999999)<br>`<i` (0~999999)<br>`<i` (0~999999)<br>`<i` (0~999999) |
| **`TankPattern`** / **`CarPattern`** / **`SmoothPattern`** | **50/50** Linked<br>固定 `body_len` `212 / 208 / 200` | `+0x18`: `clearSpeed`<br>`+0x20`: `angularSpeed`<br>`+0x28`: `acceleration` | `<f` (0.1~100)<br>`<f` (1~3600)<br>`<f` (0.1~500) |
| **`UnitComponent`** | **109/109** Linked<br>全部 380 实例尾 `-4B` 均为 `12.0f` | `body_len - 4`: `fowRadius`（解析断言原值在 `[1.0, 200.0]`） | `<f` (1.0~200.0) |
| **`FogOfWarUnit`** | **2/2** Linked<br>固定 `body_len == 8` | `+0x04`: `radius` | `<f` (1.0~200.0) |
| **`Harvester`** | **2/2** Linked<br>固定 `body_len == 84` | `+0x30`: `onlyNormalMinerals`<br>`+0x34`: `supplyMax` | `<i` (bool 0/1)<br>`<i` (1~999999) |
| **`OilPump`** | **4/4**（2 挂载 + 2 独立）<br>固定 `body_len == 32` | `+0x18`: `cooldown`<br>`+0x1C`: `addRes` | `<f` (0.1~3600)<br>`<i` (0~999999) |
| **`Mineral`** | **7/7** 标准矿脉<br>（过滤条件 `body_len >= 100`） | `+0x04`: `minerals` | `<i` (1~999999) |
| **`Bunker`** | **6/6** Linked | `+0x34`: `addVision`<br>`+0x3C`: `canShootback`<br>`+0x4C`: `maxUnits` | `<i` (0~200)<br>`<i` (bool 0/1)<br>`<i` (0~999) |
| **`HealRange`** | **9/9** Linked<br>固定 `body_len == 116` | `+0x0C`: `coolDownScan`<br>`+0x2C`: `range`<br>`+0x58`: `heal` | `<f` (0.05~60)<br>`<i` (0~200)<br>`<i` (0~999999) |
| **`Regeneration`** | **5/5** Linked<br>固定 `body_len == 44` | `+0x24`: `RegenHP`<br>`+0x28`: `timer` | `<i` (0~999999)<br>`<f` (0.1~3600) |
| **`BuildComponent`** | **17/17** Linked | `+0x0C`: `contentMain.count` (`N`, 校验 `0<=N<=50`)<br>记 `tail = 0x10 + N * 12`:<br>`tail + 0x08`: `discount`<br>`tail + 0x0C`: `timeMultiplier`<br>`tail + 0x10`: `maxBuildings` | `<f` (0.0~0.95)<br>`<f` (0.1~20.0)<br>`<i` (0~999) |

> **关键双写保障 (`HP.maxHp → HP.curHp`)**：`HP` 序列化对象同时保存了 `maxHp (+0x10)` 与 `curHp (+0x14)`，且原版 110/110 对象均满足 `maxHp == curHp`。补丁引擎写入 `HP.maxHp` 时自动同步将完全相同的新值写入 `+0x14 curHp`，并在状态扫描比对时视作一项 `maxHp` 逻辑改动（无需在 UI 重复显示 `curHp`）。

---

## 4. V2 预设 JSON Schema 规范（`schema_version: 2`, 向下兼容 v1）

```json
{
  "schema_version": 2,
  "name": "我方强化方案示例",
  "description": "帝国单位加速降耗 + 无畏血量翻倍",
  "target_game_version": "D-35-1",
  "changes": [
    {
      "script": "UnitConfig",
      "asset_name": "r_Dreadnought_Unit",
      "field": "timeCreation",
      "value": 45.0
    }
  ],
  "component_changes": [
    {
      "config_script": "UnitConfig",
      "config_asset_name": "r_Dreadnought_Unit",
      "comp_class": "HP",
      "go_rel_path": "DreadnoughtA2",
      "occ_index": 0,
      "field": "maxHp",
      "value": 4200
    },
    {
      "config_script": "UnitConfig",
      "config_asset_name": "r_Dreadnought_Unit",
      "comp_class": "AutoAttack_Projectile",
      "go_rel_path": "DreadnoughtA2/attack",
      "occ_index": 0,
      "field": "gun_damageToVehicle",
      "value": 800
    }
  ],
  "world_changes": [
    {
      "comp_class": "Mineral",
      "go_name": "MineralPrefab",
      "occ_index": 0,
      "field": "minerals",
      "value": 10000
    }
  ]
}
```

**Schema 兼容性与容错规则**：
- 加载 `schema_version == 1` 时仅读取 `changes`（`component_changes` 与 `world_changes` 置空），完美兼容所有 V1 预设。
- 加载 `schema_version == 2` 时三组均可存在，任何不存在的 `asset_name` / `go_rel_path` / `occ_index` 均温和跳过并输出警告，不崩溃、不错写。
- 导出预设时，若没有任何 `component_changes` / `world_changes` 可选择仍按 v2 规范写入（含完整三段或省略空段均合法）。

---

## 5. 施工步骤与 V2 验收标准

### 5.1 施工顺序
1. **Step 1：升级核心解析与补丁引擎 (`mod_configurator/unity_assets.py`)**
   - 实现 `resolve_affiliation()` 实战归属映射；
   - 实现 `RtsObjectConfig → mainPrefab`、DFS Prefab 图遍历、10 类组件偏移解析及越界护栏；
   - 扩展 `validate_field_value()` 支持有符号浮点抗性/射程增量及非零冷却下限校验；
   - 扩展 `patch_sharedassets_bytes()` 与还原 Diff 计算，支持 `Config` + 挂载组件（含 `HP.maxHp -> curHp` 双写）+ 独立地图资源点 3 层修改，且**不破坏任何 V1 接口与黄金 SHA-256 精确字节输出**。
2. **Step 2：升级预设与批量引擎 (`mod_configurator/preset_manager.py`, `backup_manager.py`)**
   - 支持 `schema_version: 1 / 2` 加载与导出；
   - 实现按敌我分类统计影响数量 + 基于原版基准的双向经济与战斗批量工具（血量、伤害、移速、时间、消耗、人口、矿脉批量同步）。
3. **Step 3：升级可视化界面 (`mod_configurator/gui.py`)**
   - 顶层 5 页签、默认锁定 `我方（帝国）` 筛选与全页签启用、敌方操作警告横幅、确认弹窗敌我分项明示、右侧 4 子页签（经济/血甲/武器/机动后勤）与多武器选择及同步修改支持。
4. **Step 4：扩充全量回归测试 (`tests/test_patcher.py`)**
   - **V1 7 项回归全部保留通过**（含 `0B814128...` ↔ `A20E9977...` 黄金 SHA-256）。
   - **V2 新增自动化验收用例**：
     1. 实战归属分类准确性（`r_Trench_Build` 归我方、`y_Refinery_Build` 归叛军、6 雇佣兵独立、7 战术技能分我方 5 / 敌方变种人 2）；
     2. 10 类 Prefab 与地图组件全量解析无报错（109/129 Linked、`110 HP`、`106 Attack`、`50 MovePattern`、`17 BuildComponent`、`9 HealRange`、`6 Bunker`、`5 Regeneration`、`4 OilPump`、`2 Harvester`、`2 FogOfWarUnit`、`7 Mineral`）；
     3. `HP.maxHp` 修改双写 `curHp` 验证，以及负抗性/负 `addRange` 校验、越界保护；
     4. 同名子组件（如 `r_Avanpost_Build` 双 `turretMg`、`r_MCV_BuildMobile` 四 `mgMiniTwinTurret`）按 `occ_index` 独立修改互不串位；
     5. Schema v1 向后兼容 & Schema v2 保存/加载/补丁/快照对比识别/一键还原闭环；
     6. 默认归属 `我方（帝国）` 下执行全部批量倍率时，验证敌方全部 58 项及雇佣兵/中立项受影响数为 `0`；
     7. V2 GUI 无头冒烟测试（默认我方筛选、切换 5 大页签、右侧 4 子页签渲染、多武器切换、敌方警告提示触发与 `--check` 自检）。
