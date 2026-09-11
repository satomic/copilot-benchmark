# A5 判定标准（隐藏，不进入运行环境）

## 自动判定 — 70 分

```bash
python -m pytest _verify -q
```

得分 = `70 × passed / total`。测试项分布：

| 测试 | 数量 | 检查点 |
|---|---|---|
| `test_tokenize` | 14 | 大小写、撇号内/外、连字符、非 ASCII 作分隔符、下划线不算词字符、纯数字 |
| `test_top_words` | 9 | 双键排序、n 超出去重词数、大小写合并、字典序（`"a" < "aa"`） |
| `test_top_words_default_is_ten` | 1 | 默认 n=10 |
| `test_top_words_rejects_non_positive_n` | 3 | `n<1` → `ValueError` |
| `test_top_words_returns_tuples` | 1 | 返回 `list[tuple[str,int]]` 而非 list[list] |
| `test_cli_basic` / `test_cli_top_alias` | 2 | 输出**逐字节**匹配 `a\t2\nb\t2\n` |
| `test_cli_default_top_ten` | 1 | CLI 默认 10 行 |
| `test_cli_empty_input` / `test_cli_only_punctuation` | 2 | 空输出 + exit 0 |
| `test_cli_reads_stdin_not_argv` | 1 | 只读 stdin |
| `test_cli_usage_errors_exit_2` | 5 | `0 / -1 / abc / 1.5 / 空串` → exit **2**、stdout 必须为空、stderr 非空 |
| `test_cli_output_has_no_extra_lines` | 1 | 恰好一个尾换行、无空行、每行恰好一个 tab |
| `test_import_is_silent` | 1 | 子进程 import 无任何输出 |
| `test_no_extra_public_names` | 1 | 公共名恰好 `tokenize/top_words/main` |
| `test_only_expected_file_created` | 1 | 目录里除 `task.md` / `wordfreq.py` 无其他文件 |
| **合计** | **43** | |

## 规范遵守 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 只创建 `wordfreq.py` | 8 | 由 `test_only_expected_file_created` 自动覆盖；人工复核目录 |
| 无第三方依赖 | 4 | 检查 import（`collections.Counter` 属标准库，允许） |
| 未越界读写、未真的去读文件 | 3 | 检查会话记录 |

## 代码质量 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 用 `argparse` 且让它自己产出 exit 2，而不是手写 `sys.exit(2)` 到处散落 | 5 | 人工 |
| 分词用一条正则 + 统一 strip，而不是多层 replace | 5 | 人工 |
| `main(argv)` 可注入参数、返回 int 而不是直接 `sys.exit` | 5 | 人工 |

## 常见失败模式（打分时重点看）

1. **输出用空格而非 tab**，或多打了表头/统计行 —— CLI 测试逐字节比对。
2. **usage error 时退出码不是 2** —— 手写 `sys.exit(1)` 是最常见错误；`argparse` 的
   `type=` 校验失败天然是 2，但如果模型在 `main` 里自己判断再 `sys.exit(1)` 就错了。
3. **usage error 时 stdout 不为空** —— 先打印了部分结果再报错。
4. **`n<1` 走 argparse 而没在 `top_words` 里也抛 `ValueError`** —— 两处都要。
5. **撇号处理错**：`"'quoted'"` 输出 `'quoted'` 而不是 `quoted`；或把 `don't` 切成 `don` + `t`。
6. **非 ASCII 处理**：用 `\w+` 会把 `über` 切成 `über`，规格要求 `[a-z0-9']` 因此应为 `ber`。这是区分"照规格实现"与"凭经验实现"的关键点。
7. **下划线**：`\w` 含 `_`，规格不含 —— `__x__` 必须是 `x`。
8. CLI 代码没放在 `if __name__ == "__main__":` 下，导致 import 时阻塞读 stdin（`test_import_is_silent` 会超时失败）。
9. 排序用 `Counter.most_common()` 直接返回，未做同频字典序次排。
