# 贡献指南

感谢你帮助改进信网权一审管辖助手。

## 规则

1. 测试、样例和 Issue 里**只用虚构数据**。
2. 管辖结论必须来自 `scripts/jurisdiction.py`，不得凭模型记忆作答。
3. 新增法院 / 标的额门槛 / 局部例外数据，须在 JSON 里写明出处，并加一条 `--selftest` 用例。
4. 不得用地址关键词自动判定特殊园区。
5. 无法锁定唯一法院时，保持 `precise: false` 并降低置信度。不得编造法院名称。

## 开发

```console
python scripts/jurisdiction.py --selftest
```

改数据或规则 → 加自检用例 → 全部通过才能合并。

## Pull request

- 改动小、可审
- 行为变化时更新 README / CHANGELOG
- CI 须在 Ubuntu、Windows、macOS 的 Python 3.10–3.12 上通过
