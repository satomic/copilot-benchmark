# M2 判定标准（隐藏，不进入运行环境）

参考实现在 `reference/logstats.py`（约 200 行）+ 8 个自测。隐藏套件已用它验证：
**44 passed / 0 failed**。

## 样本日志的正确答案

`seed/access.log` 共 40 行，其中 4 行畸形（第 5、27、36、38 行，分别是：整行非日志、
时区字段 `BAD`、缺失前缀只剩引号部分、duration 为 `abc`）。`--top 3` 的正确输出：

```json
{
  "lines_total": 40, "lines_parsed": 36, "lines_malformed": 4,
  "bytes_total": 156534,
  "status_classes": {"2xx": 26, "3xx": 2, "4xx": 5, "5xx": 3, "other": 0},
  "methods": {"DELETE": 1, "GET": 27, "HEAD": 1, "PATCH": 1, "POST": 5, "PUT": 1},
  "top_paths": [
    {"path": "/api/orders", "count": 8},
    {"path": "/api/users", "count": 8},
    {"path": "/", "count": 7}
  ],
  "top_ips": [
    {"ip": "203.0.113.10", "count": 12},
    {"ip": "198.51.100.7", "count": 10},
    {"ip": "192.0.2.44", "count": 8}
  ],
  "duration": {"count": 36, "mean": 0.26, "p50": 0.067, "p95": 2.4, "max": 3.011}
}
```

> `/api/orders` 与 `/api/users` 同为 8 次，正确顺序由 path 升序决定 —— 天然的并列排序检查点。

## 自动判定 — 70 分

```bash
python -m pytest tests -q      # 模型自己写的测试
python -m pytest _verify -q    # 隐藏套件（44 项）
```

得分：

| 项 | 分 | 说明 |
|---|---|---|
| 模型自测通过 + 数量达标（≥8） | 15 | 全过且 ≥8 得满分；有失败按通过率折算；不足 8 个再按 `n/8` 折算 |
| 隐藏套件通过率 | 55 | `55 × passed / 44` |

隐藏套件分区：

| 分区 | 数量 | 检查点 |
|---|---|---|
| `parse_line` | 14 | 字段逐一比对（含时区 +0800）、键集合、命名用户、`-` bytes、容忍尾随换行、10 类畸形行 |
| `analyze` | 15 | 空输入全零、**报告键顺序**、空行完全不计数、畸形计数不致命、nearest-rank 分位（n=1/4/20）、状态分类边界（100/600）、bytes 求和、methods 排序、top 截断与并列、默认 top=5、接受生成器 |
| CLI | 9 | 样本日志全量比对、JSON 缩进 2 且单尾换行、table 含 5 个必需 token 且非 JSON、`--strict` 退出 2 且报第 5 行、干净文件 strict 退出 0、缺文件退出 2、坏 `--top` 退出 2、无参退出 2 |
| 卫生 | 6 | `access.log` sha256 未变、import 静默、公共名恰好三个、无多余文件、自测规模 |

## 规范遵守 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 只创建 `logstats.py` + `tests/test_logstats.py` | 6 | `test_only_expected_files` |
| 未修改 `access.log` | **4（一票否决项）** | sha256 比对；改了则本项 0 分并在报告标注 |
| 无第三方依赖（未引入 `pandas` / `numpy` / `apachelogs`） | 5 | 检查 import |

## 代码质量 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 用一条编译好的正则 + 命名组，而非多次 `split` 拼凑 | 5 | 人工 |
| `analyze` 单遍流式处理，可接受任意可迭代对象（不 `list()` 整个文件） | 4 | 人工 |
| 分位数抽成独立函数，边界（空列表、n=1）显式处理 | 3 | 人工 |
| CLI 用 `argparse` 的 `type=` 做校验，让退出码 2 自然产生 | 3 | 人工 |

## 常见失败模式（打分时重点看）

1. **报告键顺序不对** —— 规格明确给了顺序，`test_analyze_report_key_order` 逐项比对。
2. **分位数用线性插值**（numpy/statistics 风格）—— 规格要求 nearest-rank
   `ceil(p/100*n)-1`。n=4 时 p50 必须是 2.0；用插值会得 2.5。这是最主要的区分点。
3. **空行被计入 `lines_total` 或 `lines_malformed`** —— 规格要求完全忽略。
4. **`--strict` 时 stdout 不为空** —— 先输出了报告再报错，或报错后仍打印。
5. **`--strict` 报的行号不对** —— 必须是文件内 1-based 行号（第 5 行），不是"第几个畸形行"、
   也不是跳过空行后的序号。
6. **`status_classes` 缺少计数为 0 的键**，或把 `100`/`600` 归进 1xx/6xx 而非 `other`。
7. **top 并列时不按 key 升序** —— 直接用 `Counter.most_common()` 会得到不稳定顺序。
8. **时间戳没解析成 tz-aware `datetime`** —— 返回 str 或 naive datetime。
9. **`bytes` 的 `-` 当成 None 或抛错**，而非 0。
10. **`user` 的 `-` 保留成字符串 `"-"`** 而非 `None`。
11. **正则太宽松** —— 接受了小写 method（`get`）、两位 status（`20`）、无引号的请求行。
    隐藏套件有 10 个畸形样例专门探这个。
12. **`--top 0` 退出码为 1 或 0** —— 必须是 2。
13. 自测直接依赖 `access.log`（规格第 17 条要求自建 fixture）。
