# ipc-jurisdiction

**信息网络传播权纠纷 · 一审管辖助手**

输入被告住所地、标的额等连接点，**查表**算出该向哪个法院起诉。不经过大模型推理。

本地运行，不上传案件信息。Python 3.10+，仅标准库。

[![CI](https://github.com/qwertyzhu/ipc-jurisdiction/actions/workflows/ci.yml/badge.svg)](https://github.com/qwertyzhu/ipc-jurisdiction/actions/workflows/ci.yml)
[![许可证](https://img.shields.io/github/license/qwertyzhu/ipc-jurisdiction)](LICENSE)

浏览器单页版（离线、双击即开）：<https://qwertyzhu.github.io/ipc-jurisdiction/>

> 早期预览。**不替代律师判断**，不构成法律意见。立案前拨 12368 或向立案庭核对当期口径。

## 它解决什么问题

信网权一审管辖要同时判断三件事：

1. **地域管辖** — 被告住所地、侵权行为地、原告发现地，三个连接点各有适用条件
2. **级别管辖** — 标的额是否超过本省基层知产案件上限，各省不同
3. **集中管辖** — 并非每个基层法院都有知产管辖权，一个地级市通常只有一到两家

判断错了的代价是立案被退、案件被移送。这三件事依赖的是事实性数据（各省门槛、570 家法院辖区、2962 个县级行政区归属），人脑和大模型都记不准。

本仓库把判定固化为查表程序：同样的输入永远得到同样的、可追溯到具体文件的结论。

## 60 秒上手

```console
git clone https://github.com/qwertyzhu/ipc-jurisdiction.git
cd ipc-jurisdiction
python scripts/jurisdiction.py --selftest
python scripts/jurisdiction.py --def-prov 浙江省 --def-city 杭州市 --def-district 西湖区 --amount 800000 --text
```

示例输出（杭州西湖区、诉请 80 万元）：

```
方案 1 · 被告住所地
  法院：杭州市西湖区人民法院（基层人民法院）
  依据：……标的额 80万元 ＜ 本地基层受理上限 500万元，由基层法院管辖
  定位：已按“西湖区”定位
  置信度：中
```

`--amount` 单位是**元**。默认输出 JSON；`--text` 输出可读文本。

华苑科技园（2026-08-06 起）：

```console
python scripts/jurisdiction.py --def-prov 天津市 --def-city 天津市 --def-district 西青区 --def-zone 华苑科技园 --filing-date 2026-08-06 --amount 800000 --text
```

园区归属必须人工确认后再传 `--*-zone` 或 `--*-no-special-zone`。引擎**不会**从「华苑」二字自动推定入园。

## 两种用法

| 用法 | 给谁 | 数据版本 |
|---|---|---|
| `scripts/jurisdiction.py` | 命令行 / Agent Skill | **现行**（含 2026-08-06 天津华苑调整） |
| [浏览器单页](https://qwertyzhu.github.io/ipc-jurisdiction/) | 律师本机双击 HTML | 2026-07-15 快照，**不含华苑调整** |

涉及天津南开 / 西青 / 华苑的案件，只用 Python 引擎。

把本目录放到 Claude Code / Codex / Trae 等智能体的 `skills/` 下，即加载 `SKILL.md`。纪律是：**模型只抽参数和解读输出，禁止凭记忆算管辖。**

## 覆盖范围

| 项目 | 内容 |
|---|---|
| 适用 | 影视、音乐、图文、短视频等作品的信息网络传播权侵权**一审民事**案件 |
| 不适用 | 计算机软件著作权（技术类）、专利商标不正当竞争、权属纠纷、二审再审执行 |
| 法院辖区 | 法〔2025〕167 号附件，31 省 **570** 家有知产管辖权的基层法院（2025-10-01 施行） |
| 级别管辖 | 同一附件；京沪无标的额上限；苏浙豫鄂津琼渝 500 万；广东两档；其余多为 100 万。「不含本数」——正好等于门槛归中院 |
| 互联网法院 | 法释〔2025〕14 号，**2025-11-01 起**网络著作权不再由互联网法院管辖 |
| 局部例外 | 天津华苑科技园，2026-08-06 起，见 `data/local_venue_overrides.json` |

## 已知局限（必须知悉）

1. **辖区数据系附件表格图片识别所得**（附件无文字层），存在识别误差可能。关键案件抽查原附件。
2. 各省高院可能另发细化文件；`local_venue_overrides.json` 只收录已核验的局部调整，不是全国穷尽。
3. 华苑科技园公开四至描述存在道路名称差异。引擎不做门牌自动命中，边界地块须向 12368 / 立案庭确认。
4. 浏览器单页版未同步华苑规则，见上表。

程序对不确定性的处理是**主动降级并告警**：数据为推定值或未能锁定唯一法院时，输出 `confidence: low` 和 `precise: false`。`precise: false` 时不得在文书里写死法院名。

## 数据来源

全部为公开司法文件与开源行政区划：

- 法〔2025〕167 号附件（基层知产管辖法院名单与标的额）
- 法释〔2020〕19 号第 15 条（信网权地域管辖三通道）
- 法释〔2025〕14 号（互联网法院管辖）
- 知产法院管辖规定（2020 修正）
- 天津高院 2026-08-06 华苑科技园管辖公告
- [modood/Administrative-divisions-of-China](https://github.com/modood/Administrative-divisions-of-China)（县级→地级市归位）

法〔2022〕109 号已被废止，不得再援引。

## 目录

```
SKILL.md                      Agent 工作流与纪律
scripts/jurisdiction.py       判定引擎（含 46 条 --selftest）
data/                         法院、区划、标的额、排除规则、局部例外
references/                   法条要点与文书模板
docs/index.html               浏览器单页版
```

## 安全

判定全程离线，不写日志，不缓存案件。Issue / PR **禁止**粘贴真实起诉状、工商内档、公证书或当事人身份。用虚构地址复现即可。详见 [SECURITY.md](SECURITY.md)。

## 许可证

[Apache-2.0](LICENSE)
