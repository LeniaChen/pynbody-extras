# BUG-0002: SPH 三维渲染测试在锁定的 pynbody 2.3.3 下失败

## 背景

用 `make setup` 新建的环境（macOS、Python 3.11.7）跑 `make test`，
`tests/test_bins_sph_render.py` 里有三个测试失败。`uv.lock` 对 Python >= 3.11
把 `pynbody` 解析为 **2.3.3**（3.10 为 2.0.0），而 `pyproject.toml` 只要求
`pynbody>=2.0`。这些测试以及一处生产行为依赖更新的 pynbody：BUG-0001 的
handoff 记录了测试通过的那台机器上是 pynbody 2.8.0。

## 目标

`make setup` 创建的锁定环境能通过 `make test`；`nz != ny` 的三维
`sph_render` 永远不会悄悄给出错误结果。

## 实际行为

```text
FAILED tests/test_bins_sph_render.py::test_a_volume_render_places_the_kernel_on_the_cell_grid
  AttributeError: 'CubicSplineKernel' object has no attribute 'value'
FAILED tests/test_bins_sph_render.py::test_a_volume_render_matches_a_direct_kernel_sum
  AttributeError: 'CubicSplineKernel' object has no attribute 'value'
FAILED tests/test_bins_sph_render.py::test_an_unequal_z_resolution_renders_the_grid_it_was_asked_for
  assert (np.int64(0), ..., np.int64(0)) == (2, 3, 2)
```

有两个独立原因：

1. **kernel API（仅测试）。** pynbody 2.3.3 的 kernel 只有
   `get_value(d, h=1)`，其中 `d` 已经是 `r / h`，而且只接受标量。第 341、369、
   403 行调用的是 `kernel.value(distance, h)`，传入物理距离（第 369 行传的是
   数组）。同一文件第 260 行仍在用 `get_value(r / h)`，两种 API 混用。
2. **`to_3d_grid` 的 z 方向尺寸（生产代码）。** pynbody 2.3.3 的 `to_3d_grid`
   用 `ny` 来确定 z 方向像素。对 `(4, 6, 3)` 的网格，本应落在 `(2, 3, 2)` 的
   粒子落到了 `(0, 0, 0)`。测试注释说针对这个上游 bug 的警告已经删掉，因为
   “已修复”——但这只对新版 pynbody 成立。在 2.3.3 上，`nz != ny` 时
   `bins.sph_render[...]` 会**不带任何警告**地返回错误网格。

## 期望行为

- 用 `uv.lock` 中的版本，`make setup && make test` 能通过。
- 在 `pyproject.toml` 允许的任意 pynbody 版本下，`nz != ny` 的三维渲染要么
  正确，要么给出警告（或报错）。

## 复现方式

```bash
make setup
.venv/bin/python -c "import pynbody; print(pynbody.__version__)"   # 2.3.3
.venv/bin/python -m pytest tests/test_bins_sph_render.py -k "volume_render or unequal_z"
```

## 非目标

- 修改 SPH 视图的约定，或 `_pynbody_render` 适配层的位置参数签名
  （由 `tests/test_pynbody_render_contract.py` 固定）。
- 支持 pynbody 1.x。

## 验收标准

- [ ] `pyproject.toml` 和 `uv.lock` 在一个测试确实能通过的 pynbody 下限上
      保持一致；或者测试在下限允许的所有版本上都能通过。
- [ ] 上述三个测试在 `make setup` 创建的环境中通过。
- [ ] `tests/test_bins_sph_render.py` 使用同一个 kernel 求值辅助函数，不再
      混用 `get_value` 和 `value`。
- [ ] 对 `to_3d_grid` 存在 z 尺寸 bug 的 pynbody，`nz != ny` 的三维渲染会
      警告或报错，并有测试覆盖（或者下限排除这些版本，并有契约测试固定）。
- [ ] `make check` 和 `make test-all` 通过。

## 设计说明

有两种修法，需要维护者选择：

- **A. 提高下限。** 设 `pynbody>=X`，X 为第一个同时具备
  `Kernel.value(distance, h)` 和修复后 `to_3d_grid` 的版本，然后重新 lock。
  后果：如果 X 没有 3.10 的 wheel，Python 3.10 可能失去 pynbody 支持。
  lock 文件用的是清华镜像地址，重新 lock 需要能访问该镜像，或在保留镜像的前提下
  指定 `--index-url`。
- **B. 保持下限。** 增加一个测试辅助函数，两种 API 都能求值（有 `value(r, h)`
  就用它，否则向量化调用 `get_value(r / h, h)`）；并在三维渲染路径中，对存在
  z bug 的 pynbody 版本恢复按版本判断的警告（或绕过方案）。
  `pynbodyext/util/deps.py` 中已经有 `PYNBODY_VERSION`。

如果可以接受提高下限，A 的改动更小。无论哪种，在不受支持的 pynbody 上明确失败的
契约测试，都比给出错误数字要好。

## 测试计划

- 在锁定的 2.3.3 环境中复现（红）。
- 选 A：重新 lock，跑 `make test`（绿），并增加断言
  `pynbody.__version__ >= X` 的契约测试。
- 选 B：在 2.3.3 和新版 pynbody 上分别跑这三个测试；增加测试验证受影响版本下
  `nz != ny` 渲染会警告（若无法安装真实旧版本，用 `monkeypatch` 修改
  `PYNBODY_VERSION` 或适配层）。
- `make check`、`make test-all`。

## 结果

## 待决问题

- 哪个 pynbody 版本最先同时具备 `Kernel.value(distance, h)` 和修复后的
  `to_3d_grid` z 尺寸？（通过测试的环境是 2.8.0；确切的最早版本尚未核实。）
- 选 A 还是 B？如果 A 需要放弃 Python 3.10，是否可以接受？
