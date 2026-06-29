# villages_matching

用于把 `Village.xlsx`（JNU 自然村方言数据）与 `villages.db`（广东省自然村基础库）建立层级匹配，并在 `villages_fromJNU.db` 中沉淀匹配结果、方言清洗结果及后续 review / 写回产物。

本 README 只记录“当前仓库里已经实际查到的脚本与流程”，不把历史口头步骤当成现存脚本。

## 先纠正一个关键点

我已重新核查当前仓库：

- 没有找到任何文件明确叫 `step3b`
- 也没有找到脚本、README、注释把“step3b”直接标记为现存入口
- 当前 `scripts/` 里也没有查到明显的“距离计算脚本”命名或 `distance / haversine / geodesic / nearest` 这类实现痕迹

所以，按当前仓库可验证事实：

- 我不能确认“step3b 脚本现在还在仓库里”
- 更不能确认“当前仓库里能直接运行的 step3b 就是距离计算脚本”

如果你记忆中的 `step3b` 是“计算距离”的历史步骤，那么它目前至少不是以可直接识别的 `step3b` 名称保留在仓库里。

## 当前仓库里实际能确认的阶段

### 阶段 1：层级匹配

目标：
把 `归属市 -> 归属镇 -> 归属行政村 -> 村名` 逐级匹配到 `villages.db` 的 `rowid`。

主脚本：
- `scripts/build_village_mapping.py`

辅助脚本：
- `scripts/infer_town_confirmations.py`
- `scripts/infer_admin_confirmations.py`
- `scripts/apply_natural_rule_d.py`
- `scripts/confirm_duplicate_natural_min_rowid.py`

主要输出：
- `outputs/city_mapping.csv`
- `outputs/town_mapping.csv`
- `outputs/admin_village_mapping.csv`
- `outputs/natural_village_mapping.csv`
- `outputs/natural_village_unresolved.csv`
- `outputs/manual_confirmed_mappings.csv`
- `outputs/matching_summary.json`

### 阶段 1.5：step3b 跨镇行政村补确认（现已脚本化）

目标：
把历史上已经产出的 step3b 距离候选结果，明确落成“可再次运行”的脚本，自动把可接受的跨镇行政村确认写回 `outputs/manual_confirmed_mappings.csv`，并导出剩余待复核清单。

主脚本：
- `scripts/apply_step3b_admin_confirmations.py`

使用的数据来源：
- `artifacts/step3b_auto_accept_town_distance_le_20km_name_close.csv`
- `artifacts/step3b_relaxed_candidates_26.csv`
- `artifacts/step3b_review_town_distance_le_10km.csv`

脚本行为：
1. 把 `step3b_auto_accept_town_distance_le_20km_name_close.csv` 中 `auto_accept=yes` 的记录追加写入 `outputs/manual_confirmed_mappings.csv`
2. 把 `step3b_relaxed_candidates_26.csv` 中 `group=single_candidate` 的记录追加写入 `outputs/manual_confirmed_mappings.csv`
3. 不重复追加已经存在的 `(level, parent_scope, source_value)`
4. 生成剩余待人工复核清单：
   - `outputs/step3b_remaining_review_candidates.csv`

写回格式说明：
- 实际写入目标仍是 `outputs/manual_confirmed_mappings.csv`
- `source_suggestions` 会保留 step3b 证据，例如：
  - `step3b_auto_accept_20km_name_close:...`
  - `step3b_relaxed_single_candidate:...`
- 后续再次运行 `scripts/build_village_mapping.py` 时，这些确认会重新参与正式匹配流程

### 阶段 1.6：cross-town 自然村补确认（现已脚本化）

目标：
把已经产出的跨镇自然村直接受候选重新落成可复跑脚本，自动把可接受的自然村确认写回 `outputs/manual_confirmed_mappings.csv`，并导出剩余待复核清单。

主脚本：
- `scripts/apply_cross_town_natural_confirmations.py`

使用的数据来源：
- `outputs/cross_town_admin_natural_direct_accept_suggestions.csv`
- `outputs/cross_town_admin_natural_second_batch_safe_accept.csv`
- `outputs/cross_town_admin_natural_still_review_needed.csv`

脚本行为：
1. 把 `cross_town_admin_natural_direct_accept_suggestions.csv` 中已判为可直接接受的记录追加写入 `outputs/manual_confirmed_mappings.csv`
2. 把 `cross_town_admin_natural_second_batch_safe_accept.csv` 中 `verdict=safe_accept` 的记录追加写入 `outputs/manual_confirmed_mappings.csv`
3. 不重复追加已经存在的 `(level, parent_scope, source_value)`
4. 导出剩余待人工复核清单：
   - `outputs/natural_cross_town_remaining_review_candidates.csv`

写回格式说明：
- 实际写入目标仍是 `outputs/manual_confirmed_mappings.csv`
- `level=natural`
- `parent_scope` 格式为：`市 / 镇 / 行政村`
- 后续再次运行 `scripts/build_village_mapping.py` 时，这些确认会重新参与正式匹配流程


### 阶段 1.7：自然村 second-pass（单候选 + 去尾“村”）补确认

目标：
对 `natural_village_unresolved.csv` 中已经缩到单候选、且仅差尾部“村”字的自然村记录做第二轮自动确认，批量写回 `outputs/manual_confirmed_mappings.csv`。

主脚本：
- `scripts/apply_natural_second_pass_drop_trailing_village.py`

使用的数据来源：
- `outputs/natural_village_unresolved.csv`

脚本行为：
1. 仅处理同时满足以下条件的自然村：
   - `candidate_count=1`
   - `match_status in (ambiguous_row_scope, ambiguous_normalized)`
   - `xlsx_natural_village` 以 `村` 结尾
   - 去掉尾部 `村` 后，恰好等于唯一候选值
2. 把符合条件的记录追加写入 `outputs/manual_confirmed_mappings.csv`
3. 不重复追加已经存在的 `(level, parent_scope, source_value)`
4. 导出本轮命中清单：
   - `outputs/natural_second_pass_drop_trailing_village_review.csv`

写回格式说明：
- 实际写入目标仍是 `outputs/manual_confirmed_mappings.csv`
- `level=natural`
- `parent_scope` 格式为：`市 / 镇 / 行政村`
- `source_suggestions` 前缀为 `natural_second_pass_drop_trailing_village:`

把 `natural_village_mapping.csv` 的匹配结果写入 `villages_fromJNU.db`。

主脚本：
- `scripts/export_jnu_villages_db.py`

会重建的表：
- `jnu_villages`
- `match_summary`

注意：
- 这一步是“匹配结果落库”
- 不是距离计算步骤
- 也不是最终写回 `villages.db` 的步骤

### 阶段 3：方言清洗与归并

目标：
把 JNU 原始 `dialect_raw` 清洗成结构化字段，并生成 review 产物。

主脚本：
- `scripts/normalize_jnu_dialects.py`

后续聚合 / 写回相关脚本：
- `scripts/build_dialect_write_values.py`
- `scripts/rebuild_and_fill_dialect_empty_only.py`
- `scripts/preview_standardize_dialect_values.py`
- `scripts/apply_standardize_dialect_values.py`

其中：

1. `build_dialect_write_values.py`
   - 在 `jnu_dialect_clean` 基础上生成：
     - `final_write_value`
     - `final_write_value_by_rowid`
   - 导出 review 产物

2. `rebuild_and_fill_dialect_empty_only.py`
   - 从 `villages_fromJNU.db` 聚合出 `matched_db_rowid -> final_write_value`
   - 只给 `villages.db` 中 `方言分布` 为空的记录补值
   - 写回前自动备份当前 `villages.db`
   - 以 `villages.db.bak.20260616_040829` 作为“原始基线”对照：区分原本就有值的村庄与后续写回新增的村庄
   - 写回后校验：原则上不应覆盖原本已有值的村庄；若出现差异，当前已知 17 条仅为多成分排序变化（如 `粤方言、海话` -> `海话、粤方言`），不是新增覆盖成别的内容

3. `apply_standardize_dialect_values.py`
   - 对 `final_write_value_by_rowid` 以及 `villages.db.方言分布` 做标准化整理
   - 规则：同家族细分类保留、同家族裸类在有细类时去重、跨家族成分保留

## 当前仓库中未确认存在的内容

以下内容目前没有在仓库中查到可直接对应的脚本入口：

1. 名为 `step3b` 的脚本或明确阶段文件
2. 明确以“距离计算”为职责的现成脚本
3. 以“距离排序 / 最近点候选 / 经纬度打分”命名的独立实现入口

也就是说：

- 如果历史上确实有一个 “step3b = 距离计算” 的步骤
- 那它当前要么已经丢失
- 要么被并入别的脚本且不再保留原命名
- 要么存在于历史聊天/历史版本里，但不在当前工作区可直接识别

## 当前确认的数据文件

- `Village.xlsx`
  - JNU 原始 Excel 数据
- `villages.db`
  - 目标基础库，主表为 `广东省自然村`
- `villages_fromJNU.db`
  - 中间库，保存匹配结果与方言清洗结果
- `mapping_config.json`
  - 匹配字段映射、后缀规则、建议阈值

## 当前确认的主表

### `villages.db`
表：`广东省自然村`

关键字段：
- `市级`
- `区县级`
- `乡镇级`
- `行政村`
- `自然村`
- `longitude`
- `latitude`
- `方言分布`
- `搜索用`

说明：
- 表没有声明主键
- 当前匹配 / 写回默认依赖 SQLite `rowid`

### `villages_fromJNU.db`
表：`jnu_villages`

关键字段：
- `xlsx_row_number`
- `xlsx_city`
- `xlsx_town`
- `xlsx_admin_village`
- `xlsx_natural_village`
- `dialect_raw`
- `matched_db_city`
- `matched_db_town`
- `matched_db_admin_village`
- `matched_db_natural_village`
- `matched_db_rowid`
- `match_status`

表：`match_summary`
- 保存匹配总数、匹配率和状态分布

表：`jnu_dialect_clean`
- 由 `scripts/normalize_jnu_dialects.py` 重建
- 保存方言清洗结构化结果

## 当前确认的运行顺序

### 1. 重建匹配 CSV
```bash
python3 scripts/build_village_mapping.py
```

### 2. 补跑 step3b 跨镇行政村确认脚本
```bash
python3 scripts/apply_step3b_admin_confirmations.py
python3 scripts/build_village_mapping.py
```

说明：
- 第一个命令会把 step3b 已接受候选落到 `outputs/manual_confirmed_mappings.csv`
- 第二个命令会基于这些确认重新生成各级 mapping / unresolved 结果
- 若只想看还有哪些 step3b 候选待复核，可查看：
  - `outputs/step3b_remaining_review_candidates.csv`

### 3. 补跑 cross-town 自然村确认脚本
```bash
python3 scripts/apply_cross_town_natural_confirmations.py
python3 scripts/build_village_mapping.py
```

说明：
- 第一个命令会把 cross-town 自然村已接受候选落到 `outputs/manual_confirmed_mappings.csv`
- 第二个命令会基于这些确认重新生成 natural mapping / unresolved 结果
- 若只想看还有哪些 cross-town 自然村候选待复核，可查看：
  - `outputs/natural_cross_town_remaining_review_candidates.csv`

### 4. 补跑自然村 second-pass（单候选 + 去尾“村”）确认脚本
```bash
python3 scripts/apply_natural_second_pass_drop_trailing_village.py
python3 scripts/build_village_mapping.py
```

说明：
- 第一个命令会把单候选且仅差尾部“村”的自然村确认落到 `outputs/manual_confirmed_mappings.csv`
- 第二个命令会基于这些确认重新生成 natural mapping / unresolved 结果
- 若只想看本轮命中清单，可查看：
  - `outputs/natural_second_pass_drop_trailing_village_review.csv`

### 5. 必要时补跑其他规则 / 反推确认
```bash
python3 scripts/apply_natural_rule_d.py
python3 scripts/confirm_duplicate_natural_min_rowid.py
python3 scripts/infer_town_confirmations.py
python3 scripts/infer_admin_confirmations.py
python3 scripts/build_village_mapping.py
```

### 6. 把匹配结果写入中间库
```bash
python3 scripts/export_jnu_villages_db.py
```

### 7. 重建方言清洗表
```bash
python3 scripts/normalize_jnu_dialects.py
```

### 8. 构建最终写回值 / review 产物
```bash
python3 scripts/build_dialect_write_values.py
```

### 9. 只回填 `villages.db` 中的空方言值
```bash
python3 scripts/rebuild_and_fill_dialect_empty_only.py
```

说明：
- 这是当前仓库里已经固定下来的正式写回脚本
- 它会先重跑 `scripts/normalize_jnu_dialects.py`
- 再根据 `villages_fromJNU.db` 中的 `matched_db_rowid` 聚合写回值
- 只更新 `villages.db` 中原本为空的 `方言分布`
- 写回前会备份当前 `villages.db` 到 `backups/`
- 写回后会拿 `villages.db.bak.20260616_040829` 做基线核对，区分：
  - 原本就有值的村庄
  - 后续由本流程补写的村庄
- 当前实测：本次写回新增填充 2279 条空值；对原本非空值的 17 处差异仅为多成分排序调整，不属于把原值覆盖成别的内容

### 9.5 关于 `villages_with_coordinates.xlsx`

当前仓库可验证结论：
- 没有找到 `villages_with_coordinates.xlsx`
- 也没有找到任何现成脚本负责把结果回写到这个 Excel
- 当前 README、`scripts/`、以及仓库文件里都没有可直接运行的 “回写 villages_with_coordinates.xlsx” 固定入口

因此现在能确认的只有：
- `villages.db` 的正式写回脚本已存在：`scripts/rebuild_and_fill_dialect_empty_only.py`
- `villages_with_coordinates.xlsx` 的回写流程目前没有在当前工作区落实成可验证脚本

如果后续要补这条链路，建议按与 `villages.db` 相同的审计思路固定成脚本：
1. 先定位 `villages_with_coordinates.xlsx` 实际文件路径与目标 sheet/列名
2. 用 `matched_db_rowid` 或明确的业务主键把 `villages_fromJNU.db` / `villages.db` 的最终值映射回 Excel 行
3. 写回前复制一份原始 Excel 备份
4. 严格区分：
   - 原本已有值的单元格
   - 原本为空、允许补写的单元格
5. 写回后输出变更统计与抽样核对产物

### 10. 必要时做标准化整理
```bash
python3 scripts/preview_standardize_dialect_values.py
python3 scripts/apply_standardize_dialect_values.py
```

## 当前仓库状态说明

本 README 反映的是当前工作区里“能用代码和文件直接验证”的现状：

- 已确认：匹配脚本、中间库落库脚本、方言清洗/写回脚本
- 未确认：`step3b` 这个历史步骤名对应的现存脚本
- 未确认：当前仓库里是否还保留独立的距离计算实现

如果后续从历史聊天记录、git 历史、旧分支或旧脚本中重新找回“step3b 距离计算”的真实入口，应再把它补写进本 README。
