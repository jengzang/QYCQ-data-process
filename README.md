# villages_matching

用于把 `Village.xlsx`（JNU 自然村方言数据）与 `villages.db`（广东省自然村基础库）建立层级匹配，并在中间库 `villages_fromJNU.db` 中沉淀匹配结果、方言归并结果和后续 review 产物。

项目当前可确认分为三阶段：

1. 匹配阶段
   - 目标：把 `归属市 -> 归属镇 -> 归属行政村 -> 村名` 逐级对应到 `villages.db` 的唯一 `rowid`
   - 主要脚本：`scripts/build_village_mapping.py`
   - 辅助脚本：
     - `scripts/infer_town_confirmations.py`
     - `scripts/infer_admin_confirmations.py`
     - `scripts/apply_natural_rule_d.py`
     - `scripts/confirm_duplicate_natural_min_rowid.py`

2. 中间库落库阶段
   - 目标：把匹配结果落到 `villages_fromJNU.db`
   - 主要脚本：`scripts/export_jnu_villages_db.py`
   - 当前库内主表：
     - `jnu_villages`
     - `match_summary`

3. 方言归并阶段
   - 目标：把 `dialect_raw` 归并成结构化字段，并生成 review 产物
   - 已确认入口：`scripts/normalize_jnu_dialects.py`
   - 当前可重建表：
     - `jnu_dialect_clean`
     - `jnu_dialect_clean_summary`
   - 当前已知 review 产物目录：`artifacts/dialect_review/`
     - `dialect_raw_grouping_review.csv`
     - `dialect_review_summary.json`
     - `complex_mixed_rowid_review.csv`
     - `complex_mixed_value_summary.csv`

注意：仓库里“基础归并脚本”可以直接重建 `jnu_dialect_clean`，但“把归并结果继续聚合为最终写回值（例如 `final_write_value` / `final_write_value_by_rowid`）”的后半段脚本入口，目前在现有 `scripts/` 目录中还未完全重新定位；不过对应 review 产物已经存在，说明这一步历史上确实跑通过。

## 数据文件

- `Village.xlsx`
  - JNU 原始 Excel 数据
- `villages.db`
  - 目标基础库，主表是 `广东省自然村`
- `villages_fromJNU.db`
  - 中间库，保存匹配结果与方言归并结果
- `mapping_config.json`
  - 层级字段映射、后缀清洗规则、建议阈值

## 当前确认的主表结构

### `villages.db`
表：`广东省自然村`

关键字段：
- `市级`
- `区县级`
- `乡镇级`
- `行政村`
- `自然村`
- `方言分布`
- `搜索用`

无声明主键；匹配/写回默认依赖 SQLite `rowid`。

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
- `matched_db_rowid`
- `match_status`

表：`match_summary`
- 保存匹配总数、匹配率和状态分布

表：`jnu_dialect_clean`
- 由 `scripts/normalize_jnu_dialects.py` 重建
- 当前字段包括：
  - `dialect_raw_norm`
  - `primary_family`
  - `mixed_family_text`
  - `family_tags_json`
  - `primary_subgroup`
  - `mixed_subgroup_text`
  - `subgroup_tags_json`
  - `accent_tags_json`
  - `identity_tags_json`
  - `usage_notes_json`
  - `paren_notes_json`
  - `segments_json`
  - `clean_confidence`

表：`jnu_dialect_clean_summary`
- 保存归并摘要统计

## 已确认的运行顺序

### 1. 重新构建匹配 CSV
```bash
python3 scripts/build_village_mapping.py
```

输出目录：`outputs/`

关键文件：
- `city_mapping.csv`
- `town_mapping.csv`
- `admin_village_mapping.csv`
- `natural_village_mapping.csv`
- `manual_confirmed_mappings.csv`
- `matching_summary.json`

### 2. 必要时跑匹配补充规则
处理自然村后缀扩展歧义：
```bash
python3 scripts/apply_natural_rule_d.py
python3 scripts/build_village_mapping.py
```

处理重复 row 的最小 rowid 自动确认：
```bash
python3 scripts/confirm_duplicate_natural_min_rowid.py
python3 scripts/build_village_mapping.py
```

如有镇/行政村反推确认脚本，也是在重跑主 mapping 前后使用：
```bash
python3 scripts/infer_town_confirmations.py
python3 scripts/infer_admin_confirmations.py
python3 scripts/build_village_mapping.py
```

### 3. 把最新匹配结果落到中间库
```bash
python3 scripts/export_jnu_villages_db.py
```

这一步会重建 `villages_fromJNU.db`，因此如果中间库里已有别的后续产物，应当在运行前确认是否需要备份。

### 4. 运行基础方言归并
```bash
python3 scripts/normalize_jnu_dialects.py
```

这一步会：
- 删除并重建 `jnu_dialect_clean`
- 删除并重建 `jnu_dialect_clean_summary`

### 5. 查看 review 产物
```text
artifacts/dialect_review/
```

当前已知重要产物：
- `dialect_raw_grouping_review.csv`
- `dialect_review_summary.json`
- `complex_mixed_rowid_review.csv`
- `complex_mixed_value_summary.csv`

## 当前已确认的匹配结果

当前一轮最终匹配结果（以唯一 `rowid` 可写回为准）：

- 市级：`18 / 18`，`100.0000%`
- 镇级：`995 / 1008`，`98.7103%`
- 行政村级：`12379 / 13361`，`92.6503%`
- 自然村级：`66333 / 81983`，`80.9107%`

自然村状态分布：
- `suffix_normalized = 48612`
- `exact = 8844`
- `manual_confirmed = 6733`
- `unmatched = 13718`
- `ambiguous_row_scope = 1167`
- `blocked_by_parent = 2821`
- `ambiguous_normalized = 88`

这些结果已同步进：
- `villages_fromJNU.db.jnu_villages`
- `villages_fromJNU.db.match_summary`

## 当前确认的方言归并规则来源

`normalize_jnu_dialects.py` 里已内置大量规则：
- `FAMILY_RULES`
- `SUBGROUP_PATTERNS`
- `ALIAS_SUBGROUPS`
- `DIRECT_RAW_VALUE_MAP`

已确认包含的归并方向示例：
- `高阳片阳江话 -> 阳江话`
- `潮州话 -> 潮汕话`
- `粤方言古话 -> 能古话`
- `客家方言阳春倔话 -> 客家·阳春涯话`
- `土话 / 官话 / 湘语` 这些扩展类目也已经在规则中出现

## 当前已知风险

1. `scripts/export_jnu_villages_db.py` 会直接删除重建 `villages_fromJNU.db`
   - 如果中间库里已有后续产物，先备份再运行

2. `scripts/normalize_jnu_dialects.py` 目前只重建“基础归并层”
   - 它不会直接生成旧库里曾经出现的 `final_write_value` / `final_write_value_by_rowid`
   - 后半段“按 rowid 聚合最终写回值”的脚本链路仍需继续定位

3. 匹配流程强依赖 `outputs/manual_confirmed_mappings.csv`
   - 这里保存了很多人工确认与规则化确认
   - 误删会直接影响重跑结果

## 建议工作流

如果只是想在当前仓库基础上恢复到“匹配 + 基础方言归并”状态，推荐：

```bash
python3 scripts/build_village_mapping.py
python3 scripts/export_jnu_villages_db.py
python3 scripts/normalize_jnu_dialects.py
```

如果想尽量复现历史完整流程，建议顺序：

```bash
python3 scripts/build_village_mapping.py
# 必要时补跑各类 infer / rule 脚本
python3 scripts/export_jnu_villages_db.py
python3 scripts/normalize_jnu_dialects.py
# 然后继续定位“final_write_value / by_rowid 聚合”的后半段脚本
```

## 当前仓库状态说明

本 README 反映的是当前仓库中“已经确认存在且可运行”的流程，不对缺失脚本做虚构推断。
若后续重新找到了“最终写回值聚合阶段”的脚本，应补充到本 README 的第三阶段后半段部分。
