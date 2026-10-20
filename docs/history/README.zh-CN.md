# 历史记录

[English](README.md) | [简体中文](README.zh-CN.md)

这个目录是已完成工作项的永久、紧凑索引。它让 `docs/work/` 保持较小，同时不
丢失决策、验收标准和交接记录：这些内容保留在最后一个仍包含完整工作项的
commit 里。

## 目录结构

```text
docs/history/
  2026-10.md          # 英文月度记录
  2026-10.zh-CN.md    # 同月的中文记录
```

按月份一个文件，英文和中文始终成对存在；一行对应一个已归档事项。不要创建
年度文件。

## 一行的含义

```markdown
| 2026-10-21 | BUG-0001 | bug | Execution tree 渲染完整图 | [2088326](...) | [工作项](...) | [#21](...) |
```

- `Commit` 指向最后一个仍包含 `docs/work/<ID>/` 的提交。
- `详情` 指向同一个提交里的工作项目录。
- `PR` 指向完成该事项的 pull request。

不要把删除工作项的那个 commit 用作 `Commit` 链接，因为那里已经没有工作项了。

## 归档

工作项必须已经以 `status: done` 和 `completed` 日期提交：

```bash
make archive-item ID=BUG-0001
```

命令会按完成月份向中英文两个文件各追加一行，删除 `docs/work/<ID>/`，并重新
生成 `docs/work/INDEX.md`。审核后再单独提交。

## 规则

- ID 永不复用；`new_work_item.py` 同时扫描进行中和已归档的 ID。
- 重新打开事项时使用新 ID，并在 `related: ["OLD-ID"]` 中引用旧 ID。
- 除修正坏链接外不要手工改行；正常写入应使用归档脚本。
- 中英文表格的顺序、ID 和 commit SHA 必须一致。
