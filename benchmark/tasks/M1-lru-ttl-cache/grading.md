# M1 判定标准（隐藏，不进入运行环境）

参考实现在 `reference/`（4 个文件，约 170 行）。隐藏套件已用它验证：**45 passed / 0 failed**。

## 自动判定 — 70 分

分两步：

```bash
# 1) 模型自己写的测试必须能过
python -m pytest tests -q

# 2) 隐藏套件
python -m pytest _verify -q
```

得分：

| 项 | 分 | 说明 |
|---|---|---|
| 模型自测通过 + 数量达标（≥12 且无 sleep） | 15 | 全过且 ≥12 得满分；有失败按 `15 × passed/total` 折算；不足 12 个按 `15 × n/12` 再折算 |
| 隐藏套件通过率 | 55 | `55 × passed / 45` |

隐藏套件（45 项）分布：

| 分区 | 数量 | 检查点 |
|---|---|---|
| 包结构 | 5 | `__all__`、四个文件存在、无禁止文件、无多余文件、`CacheStats` 是 frozen dataclass |
| 时钟注入 | 1 | 冻结假时钟下永不过期，且 `time_fn` 确实被调用 |
| 构造校验 | 12 | `capacity` 非正 → ValueError；非 int（含 bool）→ TypeError；默认 ttl ≤0 → ValueError |
| 基础操作 | 11 | 参考场景、default 值、覆盖刷新、LRU 淘汰序、`len ≤ capacity`、delete、clear 保留统计、keys 顺序、快照不可变 |
| TTL 语义 | 12 | 到点即过期（`>=`）、per-entry 覆盖、`ttl=None` 覆盖、省略参数用默认、坏 ttl、set 重置 ttl、purge、`in` 不计 hit/miss、delete 过期项、**过期项优先于淘汰**、keys 排除过期 |
| 并发与性能 | 3 | 8 线程 × 2000 次无异常、RLock 可重入路径不死锁、hot path 近似 O(1)（20k 次操作，容量 500 vs 10000 的单次耗时不得放大 5 倍以上） |

## 规范遵守 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 文件清单严格一致（4 个，无 `README.md`/`pyproject.toml`/`setup.py`） | 6 | 由 `test_only_expected_files` 自动覆盖 |
| 无第三方依赖（`cachetools` / `pydantic` 一律不允许） | 5 | 检查 import |
| `tests/` 下没塞 `conftest.py` 或额外文件 | 4 | 目录快照 |

## 代码质量 — 15 分

| 项 | 分 | 判定 |
|---|---|---|
| 用 `OrderedDict.move_to_end` / 双向链表实现 O(1)，而非每次排序或线性查找 | 5 | 人工 + `test_hot_path_scales` |
| 三个模块职责清晰，`__init__.py` 只做再导出 | 4 | 人工 |
| sentinel 用私有模块级对象（`_UNSET = object()`），而非 `"default"` 字符串或 `-1` 魔数 | 3 | 人工 |
| 锁的粒度一致、无嵌套锁、无 `try/except` 吞异常 | 3 | 人工 |

## 常见失败模式（打分时重点看）

1. **`ttl=None` 与省略 ttl 没区分开** —— 规格第 6 条明确要求两者行为不同，必须用 sentinel。
   直接写 `def set(self, key, value, ttl=None)` 会让 `ttl=None` 走默认 TTL，测试立刻挂。
2. **过期判定用 `>` 而非 `>=`** —— 恰好在 `t0+ttl` 时刻必须已过期，`test_expiry_is_inclusive_at_deadline` 专抓。
3. **淘汰时不先回收过期项** —— 规格第 9 条。`test_expired_entries_are_reclaimed_before_eviction`
   要求此时 `evictions == 0`。这是本任务最容易漏的语义。
4. **`__contains__` / `delete` / `keys` 误记 hit/miss** —— 四个计数器各自的触发条件要分清：
   - `hits`：仅 `get` 命中活跃项
   - `misses`：仅 `get`（缺失或过期）
   - `evictions`：仅因容量淘汰活跃项
   - `expirations`：`get`/`in`/`delete`/`purge_expired`/淘汰前回收，都算
5. **`clear()` 顺手把统计也清了** —— 规格第 17 条明确不清。
6. **`keys()` 返回 LRU→MRU 顺序**（反了），或返回 `dict_keys` 而非 `list`。
7. **`stats()` 返回可变对象或返回自身引用** —— 后续操作会改变已返回的快照。
8. **`capacity=True` 未拒绝** —— `isinstance(True, int)` 为真，要显式排除 bool。
9. **用 `time.monotonic()` 而不是 `self._time_fn()`** —— 假时钟失效，一批 TTL 测试连锁失败。
10. **起后台线程做主动清理** —— 规格第 14 条明确要求惰性过期，无线程无定时器。
11. 模型自测用 `time.sleep(1.1)` —— 违反第 25 条，`test_model_test_suite_is_substantial` 会挂。
