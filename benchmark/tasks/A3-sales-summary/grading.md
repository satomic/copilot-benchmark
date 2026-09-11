# A3 判定标准（隐藏，不进入运行环境）

## 自动判定 — 70 分

```bash
python -m pytest _verify -q
```

得分 = `70 × passed / total`。测试项分布：

| 测试 | 数量 | 检查点 |
|---|---|---|
| `test_empty` | 1 | 空输入 → `[]` |
| `test_reference_example` | 1 | task.md 里给出的参考例 |
| `test_output_key_set_and_types` | 1 | 键顺序 + `count` 为 int 非 bool + total/avg 为 float |
| `test_first_seen_casing_wins` | 1 | 大小写不敏感分组、首现原样输出 |
| `test_missing_and_blank_amounts_count_as_zero` | 1 | 缺失/None/空串/纯空白 → 0.0 且**仍计入 count** |
| `test_bool_amount_is_one` | 1 | `True` → 1.0（不特殊处理） |
| `test_sort_by_total_desc_then_region_ci_asc` | 1 | 双键排序，第二键大小写不敏感 |
| `test_rounding` | 1 | `round(x, 2)` 语义 |
| `test_avg_uses_unrounded_total` | 1 | **avg 必须用未舍入的 total 计算** |
| `test_input_not_mutated` | 1 | 不得原地修改入参 |
| `test_errors` | 6 | 错误消息逐字节匹配、0-based 索引、校验顺序 |
| `test_no_extra_public_names` | 1 | 只暴露 `summarize` |
| **合计** | **17** | |

## 规范遵守 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 只创建 `sales.py`，无多余文件 | 8 | 出现自建测试/README/临时脚本各扣 3 |
| 无第三方依赖（未引入 pandas） | 4 | 检查 import |
| 未越界读写 | 3 | 检查会话记录 |

## 代码质量 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 分组用 `dict` 累加而非 O(n²) 重复扫描 | 5 | 人工 |
| 校验与聚合职责分离，错误消息集中构造 | 5 | 人工 |
| 无死代码 / 命名规范 | 5 | 人工 |

## 常见失败模式（打分时重点看）

1. **avg 用舍入后的 total 计算** —— 规格明确要求先算 avg 再舍入，`test_avg_uses_unrounded_total` 专门抓这个。
2. **空/缺失 amount 的行没计入 count** —— 常被当成"跳过该行"。
3. **分组输出用了最后一次出现的大小写**（或直接用 lower 后的形式）。
4. **排序第二键大小写敏感** —— `"Beta"` 与 `"alpha"` 顺序会错。
5. `count` 用 `bool` 或 numpy 类型；`total` 在整数场景返回 `int` 而非 `float`。
6. **校验顺序错** —— 同一行既缺 region 又有非法 amount 时，必须先报 missing region。
7. 原地 `row["amount"] = float(...)` 污染入参。
8. 错误消息用 `str(value)` 而非 `repr(value)`（`'abc'` 少了引号）。
