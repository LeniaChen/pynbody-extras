# BUG-0001: Result 的 Execution tree 只渲染根节点

## 背景

`Result.execution_tree` 是一次计算运行的运行时视图。它的父子结构与
`CalculatorBase.dependency_tree` 和 `Result.report_node_tree()` 应该对应，
只是每一行额外带有执行信息（耗时、缓存、observer）。默认的 `rich` HTML repr
会把这段文本放在 “Execution tree” 区域。

## 实际行为

使用 `tests/calculate_helpers.py` 里共享 filter 的 pipeline：

```text
p<combined>  [2.84 ms; cache=store]
```

`result.execution_tree` 只有一行，而 `result.report_node_tree()` 有五行：

```text
p<combined>
├─ MassSum<property>
│  └─ RBelow<filter>
└─ TempMean<property>
   └─ RBelow<filter>
```

在 `rich` HTML repr 中，“Execution tree” 的 `<pre>` 同样只有这一行。
`simple` HTML repr 只列出 `.execution_tree` 这个可下钻属性，不内联内容；
这个布局差异是有意设计，不属于本 bug。

## 期望行为

Execution tree 应该渲染完整图结构，父子关系与 node tree 一致：

```text
p<combined> [...]
├─ MassSum<property> [...]
│  └─ RBelow<filter> [...]
└─ TempMean<property> [...]
   └─ RBelow<filter> [...]
```

共享的 `RBelow` 会出现在两个分支上，但它的子树只展开一次。第二次出现时按
“hit” 处理，不再重复向下遍历。

## 复现方式

```python
import sys

sys.path.insert(0, "tests")

from calculate_helpers import make_pipeline, make_sim

pipeline = make_pipeline()
result = pipeline.run(make_sim())

print(result.execution_tree)      # 一行
print(result.report_node_tree())  # 五行
```

## 根因

`pynbodyext/core/calculate/display.py` 里的 `tree_lines()` 在 `walk()` 之前
调用了一次 `children(root)`，进入 `walk()` 后又调用了一次：

```python
root_children = list(children(root))   # 第一次
...
walk(root, "", 1)                      # 再次调用 children(root)
```

`ResultQuery.execution_tree()` 传入的 `children_of()` 带状态：

```python
if current.node_id in rendered_nodes:
    return []
rendered_nodes.add(current.node_id)
return ResultQuery.display_children_of(result, current)
```

第一次调用把根节点加入 `rendered_nodes`；第二次调用因此返回 `[]`，根节点的
子节点从未被遍历。这违反了 `tree_lines(children=...)` 应该是纯访问器的隐含
约定。

## 验收标准

- [x] 对上述 fixture，`result.execution_tree` 包含所有可达节点（五行，
      包括两个分支上的共享 filter）。
- [x] 共享节点会以 hit 形式再次出现，但子树不会重复展开。
- [x] 父子结构与同一结果的 `result.report_node_tree()` 一致。
- [x] `rich` HTML card 的 Execution tree `<pre>` 中包含 `MassSum`、
      `TempMean` 和 `RBelow`。
- [x] `max_depth=0` 时仍使用共享措辞 `... N nodes hidden`。
- [x] 新增的回归测试在修复前失败、修复后通过。

## 测试计划

- 在 `tests/test_calculate_render.py` 中用 `make_pipeline()` 增加回归测试。
- 断言 execution tree 与 node tree 的行数一致。
- 断言三个节点标签都出现在 execution tree 中。
- 断言 `rich` HTML repr 的 “Execution tree” 区域包含子节点标签。
- 运行 `make check` 和 `make test-all`，并运行 `ruff`、`mypy`。

## 设计说明

最低限度是让 `tree_lines()` 只计算一次 `children(root)`，并把结果传给
`walk()`。更稳妥的做法是让 `execution_tree` 的回调幂等，或把“已经展开”的
状态从 `children` 回调中移出去，使契约显式化，避免同类问题再次出现。

### 采用的修复

两者都做，改动保持最小：

1. `tree_lines()` 只计算一次 `children(root)`，并把列表传给 `walk()`；
   `walk()` 现在接收节点的子节点列表而不是节点本身，因此每一行最多调用一次
   `children`。docstring 写明了调用顺序契约（先序遍历、先 `label` 后
   `children`、每行最多一次 `children`）。
2. `ResultQuery.execution_tree()` 在 `label` 回调里判断“首次出现还是重复出现”
   （`labelled_nodes` / `collapsed_nodes`）。`children_of()` 只读取这个状态，
   所以对同一行调用两次会得到相同的子节点。

同一个重复调用还导致 `max_depth >= 1` 时 `... N nodes hidden` 行丢失：
`execution_tree(max_depth=1)` 和 `max_depth=2` 都只渲染出根节点那一行。
本次修复同样覆盖了这种情况，并有单独的测试。

## 非目标

- 重新设计 execution tree 的标签或性能元数据。
- 修改 `simple` HTML card 的下钻布局。
- 增加新的 cache/observer 字段。

## 结果

已在 PR #23 中修复（`cb61b15`、`21e0a08`）。

- 对 `make_pipeline()` fixture，`result.execution_tree` 现在完整渲染五行；
  第二个 `RBelow` 显示为 `[cache=hit]`。
- 修复前（红）：execution tree 只有根节点一行，
  `test_tree_lines_asks_for_each_lines_children_at_most_once` 失败
  （`children("root")` 被调用两次）。
- 修复后（绿）：`tests/test_calculate_render.py` 中五个新测试在
  macOS / Python 3.11.7 上全部通过。同一次 `make test` 共
  797 通过 / 6 失败 / 3 跳过；6 个失败与本条无关，分别记录为
  BUG-0002 和 BUG-0003。

## 待决问题

- 重复出现的共享节点是否需要显式标记（例如 `[hit]`），还是保持现有的
  `hit_occurrence` 行为？除非修复必须改变，否则保持现状。
  - 结论：修复不需要改变；重复出现仍渲染为 `label  [cache=hit]`，且不带子树。
