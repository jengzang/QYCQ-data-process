# 方言匹配与清洗规则说明

本文档整理当前仓库中已经落地的村庄匹配、方言清洗、OCR/异形字纠正与写回规则。

说明：当前流程里的“方言匹配”并不是用方言文本直接匹配村庄，而是先把 JNU Excel 行匹配到 `villages.db` 的 `rowid`，再按这个 `rowid` 清洗、聚合和写回方言值。

## 1. 主要文件

| 文件 | 作用 |
| --- | --- |
| `mapping_config.json` | 层级字段映射、后缀集合、候选建议阈值 |
| `scripts/build_village_mapping.py` | 市、镇、行政村、自然村逐级匹配 |
| `scripts/export_jnu_villages_db.py` | 把匹配结果落入 `villages_fromJNU.db.jnu_villages` |
| `scripts/normalize_jnu_dialects.py` | 把原始方言文本清洗成结构化字段 |
| `scripts/build_dialect_write_values.py` | 生成单行写回值与 rowid 聚合写回值，并导出 review 产物 |
| `scripts/rebuild_and_fill_dialect_empty_only.py` | 只向 `villages.db.方言分布` 为空的记录补写方言 |
| `scripts/apply_standardize_dialect_values.py` | 对最终方言值做同家族去粗留细、去重、排序 |
| `artifacts/rule_registry.json` | 已确认规则与长期规则口径登记 |

## 2. 总体流程

1. 从 `Village.xlsx` 读取 JNU 行，关键字段包括 `归属市`、`归属镇`、`归属行政村`、`村名`、`村居民使用语言情况`。
2. 从 `villages.db` 的 `广东省自然村` 表读取基础库行，以 SQLite `rowid` 作为当前匹配和写回身份。
3. 逐级匹配 `市 -> 镇 -> 行政村 -> 自然村`。
4. 将自然村匹配结果写入 `villages_fromJNU.db.jnu_villages`。
5. 从 `jnu_villages.dialect_raw` 清洗出 `jnu_dialect_clean`。
6. 将每行方言渲染成写回值，并按 `matched_db_rowid` 聚合。
7. 只给 `villages.db` 中 `方言分布` 为空的记录补值，不覆盖已有值。
8. 对最终值做标准化整理。

## 3. 村庄层级匹配规则

### 3.1 文本归一化

匹配前统一执行：

- `unicodedata.normalize('NFKC', value)`
- 去掉首尾空白
- 删除所有空白字符

这会把全角/半角等兼容字符先归一，但不会做通用错字纠正。

### 3.2 层级顺序与父级门控

匹配顺序固定为：

1. `city`
2. `town`
3. `admin`
4. `natural`

子级只会在父级状态允许时继续匹配。允许状态包括：

- `exact`
- `suffix_normalized`
- `manual_confirmed`
- `manual_confirmed_out_of_scope`
- `ambiguous_normalized_allowed`

如果父级没有匹配上，子级状态会成为 `blocked_by_parent`。

### 3.3 后缀归一化

匹配先尝试精确匹配；失败后会循环去掉配置中的尾部后缀，再比较基础名。

后缀集合来自 `mapping_config.json`：

| 层级 | 后缀 |
| --- | --- |
| 市级 | `市`、`地区`、`自治州` |
| 镇级 | `街道办事处`、`街道办`、`民族乡`、`办事处`、`街道`、`镇`、`乡`、`街` |
| 行政村级 | `村民委员会`、`居民委员会`、`村委会`、`居委会`、`行政村`、`居民区`、`管理区`、`社区`、`大队`、`村` |
| 自然村级 | `村民小组`、`自然村`、`小组`、`新村`、`老村`、`社区`、`村`、`庄`、`寨`、`屯`、`坊`、`围`、`屋`、`里`、`社`、`巷`、`洞`、`坪`、`岗` |

匹配状态含义：

| 状态 | 含义 |
| --- | --- |
| `exact` | 归一化后完全相等，且唯一 |
| `ambiguous_exact` | 完全相等但候选不唯一 |
| `suffix_normalized` | 去后缀后相等，且唯一 |
| `ambiguous_normalized` | 去后缀后相等但候选不唯一 |
| `unmatched` | 没有候选 |
| `manual_confirmed` | 来自人工确认，且确认值在当前候选范围内 |
| `manual_confirmed_out_of_scope` | 来自人工确认，但确认值不在当前候选范围内，用于跨镇等补确认 |
| `ambiguous_row_scope` | 名称匹配到了多条 `rowid`，且无法唯一确定具体行 |

### 3.4 候选建议不是自动匹配

`suggest_candidates()` 使用 `difflib.SequenceMatcher` 生成建议：

- 默认最低分 `0.58`
- 默认最多输出 `8` 个候选
- 如果基础名互相包含，最低提升到 `0.92`
- 如果原始名互相包含，最低提升到 `0.95`

这些建议只写入 review CSV，不直接自动确认。

### 3.5 人工确认规则入口

人工确认集中在 `outputs/manual_confirmed_mappings.csv`，键为：

- `level`
- `parent_scope`
- `source_value`

确认值会重新参与 `build_village_mapping.py`。自然村如果有重复 `rowid`，可以通过 `source_suggestions` 中的 `user_confirm_row_scope:` 或 `duplicate_min_rowid:` 提供行范围提示。

## 4. 方言清洗规则

### 4.1 输入与输出

输入字段：

- `jnu_villages.dialect_raw`

清洗输出表：

- `jnu_dialect_clean`

主要结构化字段：

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

### 4.2 方言大类

当前识别的大类为：

- `粤`
- `客家`
- `闽`
- `少数民族`
- `土话`
- `官话`
- `湘语`

LLM 辅助判定层允许额外使用：

- `其他`

`其他` 只用于原始方言无法可靠归入上述七类时；使用 `其他` 时仍应尽量给出小类，例如 `其他·越南语`。如果只能判断为泛称方言而没有小类证据，可写作 `其他`，并标记人工复核。

大类识别基于 `FAMILY_RULES` 正则。例如：

| 大类 | 典型触发词 |
| --- | --- |
| 粤 | `粤方言`、`粤语`、`白话`、`广府话`、`四邑话`、`台山话`、`阳江话`、`高州话` 等 |
| 客家 | `客家方言`、`客家话`、`涯话`、`上莞话`、`清化话`、`叶潭话`、`蓝口话` 等 |
| 闽 | `闽方言`、`闽南语`、`潮州话`、`潮汕话`、`学佬话`、`雷州话`、`海话` 等 |
| 少数民族 | `壮话`、`壮语`、`瑶话`、`瑶语`、`畲话`、`蓝田话` 等 |
| 土话 | `虱婆声`、`虱话`、`潭岭话`、`黄圃话`、`土话` |
| 官话 | `普通话`、`旧时正话`、`四川话`、`重庆话`、`军话`、`官话` |

如果文本开头明确出现大类前缀，例如 `使用客家方言`、`粤语`、`白话`、`潮汕话`，会优先采用前缀识别结果。

### 4.3 细类识别

细类来自 `SUBGROUP_PATTERNS`，包括但不限于：

- 粤类：`四邑话`、`台山话`、`恩平话`、`阳春白话`、`吴川话`、`广宁话`、`清远白话`、`化州话`、`阳江话`、`高要话`、`鼎湖话`、`沙田话`
- 客家类：`涯话`、`上莞话`、`清化话`、`黄村话`、`叶潭话`、`蓝口话`、`仁化董塘话`、`仁化长江话`
- 闽类：`潮汕话`、`潮州话`、`潮州语`、`学佬话`、`雷州话`、`海丰话`、`福佬话`
- 少数民族类：`连山壮话`、`瑶语`、`瑶族方言`、`畲话`、`蓝田话`
- 土话类：`虱婆声`、`潭岭话`、`黄圃话`、`尖米话`、`船话`、`船婆声`
- 官话类：`普通话`、`旧时正话`、`四川话`、`重庆话`、`军话`

当某个片段只识别出一个大类时，会过滤掉不属于该大类的细类，避免一个片段被错误拉成混合。

### 4.4 多成分与混合

文本会按以下分隔符切分：

- `，`
- `、`
- `；`
- `/`

同时会把 `及` 替换为 `和`。注意当前代码不会按 `和` 再切分，它主要依赖后续正则识别多个家族。

判定逻辑：

- 没有识别到家族：`primary_family = None`
- 识别到一个家族：`primary_family = 该家族`
- 识别到多个家族：`primary_family = 混合`
- 多个家族文本记录到 `mixed_family_text`
- 多个细类记录到 `mixed_subgroup_text`

### 4.5 置信度

`clean_confidence` 规则：

| 置信度 | 条件 |
| --- | --- |
| `high` | 单一清晰家族，且没有额外说明因素 |
| `medium` | 混合、多片段、含使用说明、括号内容、民系标签、口音/标话/土话等 |
| `low` | 未识别出家族和细类 |

当前库中已观察到的数量约为：

- `high`: 70145
- `medium`: 10850
- `low`: 988

## 5. OCR/错字/异形字处理

当前 OCR 纠错不是通用相似字算法，而是通过两张规则表处理：

- `ALIAS_SUBGROUPS`：别名、细类归一化、部分 OCR 归一
- `DIRECT_RAW_VALUE_MAP`：整段原文直接映射到 `(family, subgroup)`

### 5.1 常见大类 OCR 归一

| 原始/OCR 形态 | 归一结果 |
| --- | --- |
| `粤方盲` | `粤` |
| `粤方育` | `粤` |
| `粤方首` | `粤` |
| `粵方言` | `粤` |
| `客家方盲` | `客家` |
| `客家方音` | `客家` |
| `客家方官` | `客家` |
| `客家方宙` | `客家` |
| `専方言`、`專方言` | `粤` |
| `岑方言`、`考方言`、`毒方言`、`邮方言` | `粤` |
| `闫方言`、`闻方言`、`闽万言` | `闽` |

### 5.2 细类/别名归一

| 原始/OCR 形态 | 归一结果 |
| --- | --- |
| `高阳片阳江话` | `阳江话` |
| `潮州话`、`潮州语`、`潮州方言`、`潮汕方言` | `潮汕话` |
| `雷话`、`雷州方言` | `雷州话` |
| `畬话`、`畬话方言` | `畲话` |
| `虱话` | `虱婆声` |
| `军声` | `军话` |
| `偃话` | `涯话` |
| `四色话`、`四包话`、`尊方言四巨话`、`粤言语四色话` | `四邑话` |
| `粤方言古话`、`粤方言能古话`、`粤方言催古话`、`粤方言佳古话`、`粤方言候古话`、`粤方言健古话`、`催古话` | `能古话` |
| `霉方言湛江白洁` | `粤·湛江白话` |

### 5.3 使用/通用前缀

部分前缀会通过直接映射或家族前缀规则消化：

- `使用潮汕方言 -> 闽·潮汕话`
- `通用闽南语 -> 闽`
- `使用古话 -> 粤·能古话`
- `通用旧时正话 -> 官话·旧时正话`
- `通用重庆话 -> 官话·重庆话`
- `以普通话为主 -> 官话·普通话`

### 5.4 不是 OCR 纠错的内容

以下内容会作为说明信息保留或降低置信度，不直接当成方言类别：

- `广府民系`
- `客家民系`
- `潮汕民系`
- 括号内容
- `使用`、`通用`、`部分`、`同时`、`互通` 等使用说明
- `口音`、`标话`、`土话`、`古话`、`蛇声`、`虱婆声` 等泛化捕获标签

## 6. 写回值生成与聚合

### 6.1 单行写回值

`render_single_value()` 的渲染规则：

| 结构化结果 | 写回值 |
| --- | --- |
| 单一大类 + 细类 | `大类·细类` |
| 单一大类，无细类 | `大类` |
| 混合家族 | 按组件拼接 |
| 无大类但有细类 | 细类 |
| 无可识别结果 | 空 |

示例：

- `粤` + `四邑话` -> `粤·四邑话`
- `闽` + `潮汕话` -> `闽·潮汕话`
- `客家` + 空 -> `客家`

### 6.2 rowid 聚合

同一个 `matched_db_rowid` 可能对应多条 JNU 行。聚合规则：

- 收集所有非空单行写回值
- 去重
- 按家族顺序排序
- 同一大类下，如果有细类值，优先保留细类，去掉裸大类
- 跨家族成分保留

家族排序：

1. `粤`
2. `客家`
3. `闽`
4. `土话`
5. `官话`
6. `湘语`
7. `少数民族`

拼接符为 `、`。

### 6.3 标准化写回

`apply_standardize_dialect_values.py` 会进一步执行：

- 同家族细类优先
- 同家族裸类在已有细类时去掉
- 跨家族成分保留
- 其他无法识别为家族组件的值保留为原组件

### 6.4 写回保护

`rebuild_and_fill_dialect_empty_only.py` 的保护原则：

- 只更新 `villages.db.广东省自然村.方言分布` 为空的记录
- 不覆盖已有非空方言值
- 写回前自动备份 `villages.db`
- 写回后用 `villages.db.bak.20260616_040829` 做基线核对

## 7. Review 产物

方言相关 review 产物位于 `artifacts/dialect_review/`：

| 文件 | 作用 |
| --- | --- |
| `dialect_raw_grouping_review.csv` | 按原始方言文本分组，查看同一 raw 的建议写回值是否稳定 |
| `complex_mixed_rowid_review.csv` | 多家族、多组件、粗细混合的 rowid 列表 |
| `complex_mixed_value_summary.csv` | 复杂聚合值汇总 |
| `dialect_review_summary.json` | 方言 review 总览 |
| `final_value_standardization_rowid_diff.csv` | rowid 聚合标准化前后差异 |
| `final_value_standardization_villages_db_diff.csv` | `villages.db` 标准化前后差异 |

匹配相关 review 产物位于 `outputs/`：

- `manual_review_candidates.csv`
- `town_unresolved.csv`
- `admin_village_unresolved.csv`
- `natural_village_unresolved.csv`
- `unmatched_and_ambiguous.json`

## 8. 当前已知待确认点

以下点建议后续人工确认后再改规则：

1. `容家方盲` 在 `ALIAS_SUBGROUPS` 中映到 `粤`，但在 `DIRECT_RAW_VALUE_MAP` 中映到 `客家`。由于整段直接映射优先，这个值当前作为整段出现时会走 `客家`，但规则口径存在冲突。
2. `dialect_review_summary.json` 中曾出现类似 `客家、粤、客家`、`粤、粤、客家` 的复杂值，说明部分旧 review 产物或聚合结果可能还包含标准化前痕迹；调整规则后应重新跑 `normalize_jnu_dialects.py`、`build_dialect_write_values.py` 和标准化脚本。
3. 部分 OCR 映射如 `毒方言 -> 粤`、`邮方言 -> 粤`、`每方台 -> 粤`、`闻方言 -> 闽` 属于经验规则，建议保留来源或样例，避免后续误扩展。
4. 当前 OCR 规则是白名单映射，不会自动把所有形近字改成目标字；新增规则应优先加入 `artifacts/rule_registry.json` 说明依据，再同步到代码。

## 9. 修改规则后的建议运行顺序

如果只修改方言清洗规则：

```bash
python3 scripts/normalize_jnu_dialects.py
python3 scripts/build_dialect_write_values.py
python3 scripts/preview_standardize_dialect_values.py
```

如果确认要写回 `villages.db` 空值：

```bash
python3 scripts/rebuild_and_fill_dialect_empty_only.py
python3 scripts/apply_standardize_dialect_values.py
```

如果修改村庄匹配规则或人工确认：

```bash
python3 scripts/build_village_mapping.py
python3 scripts/export_jnu_villages_db.py
python3 scripts/normalize_jnu_dialects.py
python3 scripts/build_dialect_write_values.py
```
