# A1 判定标准（隐藏，不进入运行环境）

## 自动判定 — 70 分

```bash
python -m pytest _verify -q
```

得分 = `70 × passed / total`。测试项分布：

| 测试 | 数量 | 检查点 |
|---|---|---|
| `test_known_values` | 27 | 已知值逐一比对，含全部减法对 |
| `test_full_round_trip` | 1 | 1..3999 全量往返解码 |
| `test_out_of_range_raises_value_error` | 5 | `0 / -1 / -3999 / 4000 / 10000` → `ValueError` |
| `test_bad_type_raises_type_error` | 7 | 含 `True/False`（bool 是 int 子类，最易漏） |
| `test_import_is_silent` | 1 | import 无 stdout/stderr |
| `test_no_extra_public_names` | 1 | 只暴露 `to_roman` |
| **合计** | **42** | |

## 规范遵守 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 只创建 `roman.py`，无多余文件 | 8 | `ls` 对比；出现 `README.md` / `requirements.txt` / 自建测试 / 临时脚本各扣 3，扣完为止 |
| 无第三方依赖、无网络访问 | 4 | 检查 import 与 usage JSON 里的工具调用 |
| 未越界读写本文件夹之外 | 3 | 检查会话记录中的 `view` / `create` / shell 路径 |

## 代码质量 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 实现简洁（查表 + 贪心，非 3999 分支硬编码） | 6 | 人工 |
| 错误信息可读（不是裸 `raise ValueError`） | 4 | 人工 |
| 无死代码 / 无调试残留 / 命名规范 | 5 | 人工 |

## 常见失败模式（打分时重点看）

1. **`bool` 未拒绝** —— `isinstance(True, int)` 为真，必须显式排除 `bool`。这是本任务最主要的区分点。
2. 类型校验与范围校验顺序颠倒，导致 `to_roman(5.0)` 抛 `ValueError` 而非 `TypeError`。
3. 用 `if/elif` 硬编码千位百位十位个位（能过测试但质量分低）。
4. 顺手加了 `from_roman` 或 CLI 入口 —— 违反"只暴露 `to_roman`"与"不创建多余文件"。
