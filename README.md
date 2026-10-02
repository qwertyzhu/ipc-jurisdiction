# ipc-jurisdiction

**信息网络传播权纠纷 · 一审管辖助手**

输入被告住所地、标的额等连接点，**确定性规则查表**算出该向哪个法院起诉，**杜绝大模型在管辖和法条上的法律幻觉**。

底层计算引擎本地离线运行（Python 3.10+ 仅标准库）。支持作为命令行工具独立使用，也可作为 Agent Skill 无缝接入 Claude Code、Codex、Antigravity、Trae 等智能体。

[![CI](https://github.com/qwertyzhu/ipc-jurisdiction/actions/workflows/ci.yml/badge.svg)](https://github.com/qwertyzhu/ipc-jurisdiction/actions/workflows/ci.yml)
[![许可证](https://img.shields.io/github/license/qwertyzhu/ipc-jurisdiction)](LICENSE)

- **免安装在线版**：[GitHub Pages 单页工具](https://qwertyzhu.github.io/ipc-jurisdiction/)（亦可双击本地 `docs/index.html` 离线使用）
- **早期预览**：**不替代律师判断**，不构成法律意见。立案前拨 12368 或向立案庭核对当期口径。

## 它解决什么问题

信网权一审管辖要同时判断三件事：

1. **地域管辖** — 被告住所地、侵权行为地、原告发现地，三个连接点各有适用条件
2. **级别管辖** — 标的额是否超过本省基层知产案件上限，各省不同
3. **集中管辖** — 并非每个基层法院都有知产管辖权，一个地级市通常只有一到两家

判断错了的代价是立案被退、案件被移送。这三件事依赖的是纯事实数据（各省门槛、570 家法院辖区、2962 个县级行政区归属），人脑和大模型都记不准。

**架构设计与人机分工**：
- **大模型负责**：材料阅读理解、提取非结构化连接点（省市区、诉请金额、服务器线索），以及生成起诉状管辖依据段落。
- **规则引擎负责**：管辖判定与法条归位。同样的输入永远得到确定性的、可追溯到具体司法文件的结论，彻底斩断大模型“凭幻觉瞎编管辖法院”的风险。

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

## 三种使用方式

| 方式 | 适合场景 | 运作机制与数据隐私 | 数据版本 |
|---|---|---|---|
| **AI Agent Skill**（推荐） | 智能体工作流（Claude Code / Codex / Trae / Antigravity 等） | **大模型抽参数 + 本地脚本查表 + 大模型写文书**。案卷需经云端大模型语义理解，注意商业秘密脱敏 | **现行**（含 2026-08-06 华苑调整） |
| **本地命令行 (CLI)** | 开发者 / 批量处理 / 极致隐私需求 | 本地终端离线运行 `python scripts/jurisdiction.py`，不联网、不调用任何大模型、零数据上传 | **现行**（含 2026-08-06 华苑调整） |
| **浏览器单页版** | 律师免 Python 环境快速点选查表 | 浏览器纯前端 JavaScript 本地计算，双击 `docs/index.html` 或访问网页，不上传后端 | 2026-07-15 快照，**不含华苑调整** |

> **Agent 纪律**：把本目录放到智能体的 `skills/` 下即加载 `SKILL.md`。**模型只抽参数和解读输出，禁止凭记忆算管辖。** 涉及天津南开 / 西青 / 华苑的案件，须使用现行 Python 引擎。

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

## 安全与数据隐私

- **底层引擎离线保密**：Python 脚本与单页 HTML 判定引擎完全在本地离线运行，无任何网络请求，不写日志，不缓存案件数据。
- **Agent 模式隐私提示**：若将本仓库作为 Skill 挂载到云端 AI 智能体，案件材料输入会发送至宿主大模型服务商。对于敏感或涉密案件，建议**仅向大模型提供脱敏后的连接点地址与金额**，或直接使用本地命令行 (CLI) 纯离线执行。
- **开源协作纪律**：Issue / PR **禁止**粘贴真实起诉状、工商内档、公证书或当事人身份，请使用虚构地址复现。详见 [SECURITY.md](SECURITY.md)。

## 许可证

[Apache-2.0](LICENSE)
