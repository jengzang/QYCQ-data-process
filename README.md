# villages_matching

用于把 `Village.xlsx`（JNU 自然村方言数据）与 `villages.db`（广东省自然村基础库）建立层级匹配，并在 `villages_fromJNU.db` 中沉淀匹配结果、方言清洗结果及后续 review / 写回产物。

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

1. 明确以”距离计算”为职责的独立脚本（经纬度距离 / 最近点排序 等）
2. 以”距离排序 / 最近点候选 / 经纬度打分”命名的独立实现入口

说明：

- step3b 数据（距离候选结果）是由历史步骤产出的，当前仓库通过 `scripts/apply_step3b_admin_confirmations.py` 消费这些结果
- 但产出这些距离候选的”距离计算脚本”本身没有以独立脚本形式保留在仓库中

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

表：`jnu_dialect_llm_adjudication`
- 由 `scripts/llm_adjudicate_dialects.py` 写入
- 保存大模型对单行方言归一化结果的判定
- 默认作为 review / 辅助判定层，不直接写回 `villages.db`
- 最终值要求格式为：`大类` 或 `大类·小类`；多个成分用 `、` 连接

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

### 7.5 LLM 辅助方言判定（可选）

1. 在项目根目录创建本地 `.env`，写入 DeepSeek API key：
```bash
LLM_API_KEY=sk-你的真实key
```

可选配置：
```bash
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1/chat/completions
LLM_WIRE_API=chat_completions
```

如果要使用 DeepSeek reasoner：
```bash
LLM_MODEL=deepseek-reasoner
```

如果要使用本地 Codex 同款 sub2api responses 路由：
```bash
LLM_API_KEY=dummy
LLM_MODEL=你的_sub2api_模型名
LLM_BASE_URL=http://127.0.0.1:8080/v1
LLM_WIRE_API=responses
```

2. 先 dry-run 检查流程，不会请求大模型：
```bash
python3 scripts/llm_adjudicate_dialects.py --dry-run --limit 20
```

3. 确认 `.env` 配好后正式调用。建议先用高优先级候选、小批量、可断点模式：
```bash
python3 scripts/llm_adjudicate_dialects.py --apply --priority-candidates --limit 50 --timeout 20 --progress-every 5 --skip-existing
```

说明：
- 该步骤位于规则清洗之后、最终写回值构建之前
- 当前 prompt version 为 `dialect_llm_v2`
- 输入包括原始方言、规则清洗结果、村名、地理层级、村历史沿革、民系/迁徙线索、村名来源、建村时间、世居姓氏和居民民族
- v2 不再把完整规则文档喂给模型；`rule_baseline` 只是机器规则建议，模型需要根据原始 `dialect_raw` 做语义裁判
- 默认只选择 `low`、`medium`、`混合`、OCR 可疑记录进入 LLM 判定；如需全部非空方言行，可加 `--all-rows`
- 可加 `--priority-candidates` 只跑高价值候选，跳过明确可由规则处理的记录
- 可加 `--skip-existing` 跳过已经有真实 LLM 结果的行，适合分批续跑
- 默认不调用 API；未传 `--apply` 时等同 dry-run
- 默认 provider/model 为 DeepSeek：`deepseek-chat`
- 默认 API 地址为：`https://api.deepseek.com/v1/chat/completions`
- 默认 wire API 为：`chat_completions`
- `LLM_WIRE_API=chat_completions` 会请求 `LLM_BASE_URL`
- `LLM_WIRE_API=responses` 会请求 `LLM_BASE_URL/responses`
- 脚本会自动读取项目根目录 `.env`
- `.env` 已加入 `.gitignore`，不要提交 API key；不要把真实 key 写进 README 或代码
- 可用 `.env` 或系统环境变量覆盖：`LLM_PROVIDER`、`LLM_MODEL`、`LLM_BASE_URL`、`LLM_WIRE_API`
- API key 默认读取：`LLM_API_KEY`；也兼容旧的 `DEEPSEEK_API_KEY`
- 输出写入 `villages_fromJNU.db.jnu_dialect_llm_adjudication`
- 同时导出 review CSV：`artifacts/dialect_llm_review/llm_adjudication_review.csv`
- 每次运行会追加永久留痕 CSV：`artifacts/dialect_llm_review/runs/llm_adjudication_run_*.csv`
- 该步骤不直接覆盖 `villages.db.方言分布`
- 方言最终值要求必须有大类；小类尽量给出，证据不足可留空
- 普通格式为 `大类` 或 `大类·小类`；多个共时方言用 `、` 分隔，例如 `粤·台山话、少数民族·瑶语`
- 历时转变使用 `历史方言 → 当前方言`，例如 `客家 → 粤`、`客家·涯话 → 粤·阳春白话`
- `广府民系`、`广府方言`、`广府话`、`粤方言`、`白话` 只作为 `粤` 大类线索，不写成 `粤·广府话`；原文明确出现的口音可以保留在小类中

### 8. 构建最终写回值 / review 产物
```bash
python3 scripts/build_dialect_write_values.py
```

说明：
- 当前脚本仍以规则清洗结果为主构建写回值
- 若要让 LLM 判定结果参与最终写回，需要在 review 后再把可接受结果接入 `build_dialect_write_values.py`

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

### 9.5 回写 `Village_with_coords.xlsx`
```bash
python3 scripts/fill_village_with_coords_xlsx.py
```

说明：
- 当前已确认原始来源文件为项目根目录下的 `Village.xlsx`
- 目标输出文件为项目根目录下的 `Village_with_coords.xlsx`
- 目标 sheet 为 `Village`
- 当前脚本会先按 `Village.xlsx` 的原始列顺序与内容全量重建整张表
- 最终格式必须严格对齐 `Village.xlsx`，只在末尾额外追加两列：
  - `db_longitude`
  - `db_latitude`
- 也就是说：前 19 列保持 `Village.xlsx` 原样；不允许擅自改成匹配中间表字段视图
- 经纬度通过 `villages_fromJNU.db.jnu_villages.xlsx_row_number -> matched_db_rowid -> villages.db.rowid` 映射，从 `villages.db` 的 `longitude` / `latitude` 写入
- 如果某行没有 `matched_db_rowid`，或目标自然村在 `villages.db` 中没有经纬度，则这两列留空
- 重建前会先备份当前 `Village_with_coords.xlsx` 到 `backups/`
- 当前输出表头应与 `Village_with_coords.xlsx.bak.20260629` 一致，共 21 列：
  - `Village.xlsx` 原 19 列
  - `db_longitude`
  - `db_latitude`

### 10. 必要时做标准化整理
```bash
python3 scripts/preview_standardize_dialect_values.py
python3 scripts/apply_standardize_dialect_values.py
```

## 当前仓库状态说明

- 已确认：匹配脚本、step3b 确认脚本、cross-town 确认脚本、中间库落库脚本、方言清洗/写回脚本
- 未确认：独立距离计算实现（step3b 的距离候选数据由历史步骤产出，产出脚本本身未保留在仓库中）
