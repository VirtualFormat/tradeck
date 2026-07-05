# 三个独立项目 技术活文档

> **文档性质**：方案记录 + 任务拆解 + 进度跟踪。随项目演进持续更新。
> **最后更新**：2026-07-04
> **关联文档**：[tech-analysis.html](./tech-analysis.html)（完整技术分析）

---

## 1. 三个独立项目

三个项目独立开发、独立可用、独立验证。部分共用项目 1 的数据层（OpenBB Platform）。

| 项目 | 名字 | 目标 | 难度 | AI 协助周期 | 状态 |
|---|---|---|---|---|---|
| **1. 市场资讯看板** | tradeck | 全球股票行情 + 资讯展示 | ⭐⭐ 中 | 1-2 周 | 未开始 |
| **2. LLM 投资分析** | 待定 | TradingAgents-CN + MCP，个人投资助理 | ⭐⭐ 中 | 1-2 周 | 未开始 |
| **3. 量化交易** | 待定 | vectorbt/Qlib 回测 + A 股/美股实盘 | ⭐⭐⭐⭐ 高 | 2-3 周 | 未开始 |

**核心原则**：TradingAgents-CN 是决策引擎，不是数据源。项目 2 的对外数据查询走项目 1 的 OpenBB 数据层。

---

## 2. 共用关系

```
┌─────────────────────────────────────────────────┐
│ 项目 1：tradeck（独立项目）                       │
│   Next.js + shadcn/ui                            │
│   ↓ HTTP                                         │
│   OpenBB Platform（数据层，三项目共用）            │
│   - FMP/Finnhub/FRED 官方 Provider              │
│   - openbb-akshare-provider（自写）             │
├─────────────────────────────────────────────────┤
│ 项目 2：LLM 投资分析（独立项目）                   │
│   Claude/Cursor                                  │
│   ↓ MCP                                          │
│   MCP Server（自写，3-5 天）                      │
│   ↓ Python import                                │
│   TradingAgents-CN（决策引擎，不改）              │
│   ↓ 数据查询                                     │
│   OpenBB SDK（复用项目 1 数据层）                │
├─────────────────────────────────────────────────┤
│ 项目 3：量化交易（独立项目）                       │
│   回测：vectorbt + Qlib（按需）                  │
│   实盘：A 股（QMT/Ptrade）+ 美股（Alpaca/IB）    │
│   数据：复用项目 1 OpenBB 拉数据 → Parquet 归档   │
└─────────────────────────────────────────────────┘
```

| 层 | 项目 1 | 项目 2 | 项目 3 |
|---|---|---|---|
| **OpenBB Platform** | ✅ 建 | ✅ SDK 复用 | ✅ 数据源复用 |
| **openbb-akshare-provider** | ✅ 建 | ✅ 复用 | ✅ 复用 |
| **OpenBB 标准模型** | ✅ 用 | ✅ 复用 | ✅ 复用 |
| **Parquet 归档** | - | - | ✅ 建 |
| **TradingAgents-CN** | - | ✅ 用（决策引擎） | - |
| **MCP Server** | - | ✅ 建 | - |
| **vectorbt** | - | - | ✅ 用 |
| **券商 API** | - | - | ✅ 接 |

---

## 3. 项目 1：tradeck 市场资讯看板

### 3.1 技术栈

| 层 | 选型 |
|---|---|
| **前端** | Next.js 15 + shadcn/ui + Tailwind v4 |
| **图表** | TradingView Lightweight Charts + ECharts |
| **布局** | react-grid-layout（可拖拽） |
| **数据** | TanStack Query（轮询） |
| **后端** | OpenBB Platform（自带 FastAPI，200+ 路由） |
| **数据源** | FMP（全球行情）+ Finnhub（新闻）+ FRED（宏观）+ AKShare（A 股，自写 Provider） |
| **部署** | Vercel（前端）+ VPS（OpenBB） |

### 3.2 任务拆解

#### 数据层（Week 1）

- [x] **T1.1** 部署 OpenBB Platform ✅ 2026-07-05
  - [x] Docker 镜像构建（`docker/openbb/Dockerfile`，python:3.12-slim + pip install openbb）
  - [x] docker-compose.yml（OpenBB 作为 service，端口 6900）
  - [x] 启动 `openbb-api` 验证 195 个路由可用
  - [x] 验证美股报价：`AAPL 308.63 USD` ✅
  - [x] 验证 A 股报价：`600519.SS 1194.45 CNY`（贵州茅台）✅
  - [x] 验证港股历史：`0700.HK` 21 条 K 线（腾讯）✅
  - [x] 验证美股财报：`AAPL fiscal_year 2025 revenue 4161亿`（SEC 源）✅
  - [x] Swagger UI `/docs` 可访问 ✅
  - **难度**：⭐ 低 · **复杂度**：⭐
  - **备注**：免费源（yfinance/sec/federal_reserve 等 17 个 Provider）已就绪。News 端点只支持 benzinga/fmp/intrinio/tiingo（需 key），yfinance 不支持 news。

- [x] **T1.2** 写 openbb-akshare-provider 扩展 ✅ 2026-07-05
  - [x] 学习 OpenBB Provider Extension 开发（Fetcher/QueryParams/Data 三件套）
  - [x] 实现 Fetcher：A 股实时报价（`stock_individual_info_em` + `stock_bid_ask_em` 降级）
  - [x] 实现 Fetcher：A 股历史 K 线（`stock_zh_a_hist`，前复权）✅ 实测 22 条数据
  - [x] 实现 Fetcher：A 股指数历史（`stock_zh_index_daily_em`）✅ 实测 8674 条数据
  - [x] 实现 Fetcher：北向资金（`stock_hsgt_north_net_flow_in_em`）
  - [x] 实现 Fetcher：融资融券（`stock_margin_detail_szse`）
  - [x] 实现 Fetcher：龙虎榜（`stock_lhb_detail_em`）
  - [x] 实现 Fetcher：板块/概念（`stock_board_concept_name_em` + `stock_board_industry_name_em`）
  - [x] 注册到 OpenBB，`provider="akshare"` 可用 ✅ 18 个 Provider
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐
  - **备注**：本地容器东方财富封 IP，实时报价类接口不可用；历史 K 线/指数历史可用。生产 VPS 部署后需重新验证实时报价。

- [ ] **T1.3** VPS 部署 OpenBB Platform
  - [ ] 选 VPS
  - [ ] Docker 部署 OpenBB
  - [ ] 配置 HTTPS
  - **难度**：⭐ 低 · **复杂度**：⭐

#### 前端（Week 2-3）

- [ ] **T1.4** Next.js 项目初始化
  - [ ] `npx create-next-app@latest`（App Router + TS + Tailwind v4）
  - [ ] `npx shadcn@latest init`（New York 风格 + 深色主题）
  - [ ] 配置 OpenBB API 客户端 + TanStack Query
  - **难度**：⭐ 低 · **复杂度**：⭐

- [ ] **T1.5** 大盘指数总览页
  - [ ] 指数卡片组件（复用 tradeck 经验）
  - [ ] 数据：上证/深证/创业板 + 恒生 + 标普/纳指/道指
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

- [ ] **T1.6** 个股详情页
  - [ ] 搜索框（Cmd+K）
  - [ ] K 线图（TradingView LC）
  - [ ] 基本面卡片
  - [ ] 财报模块
  - **难度**：⭐⭐⭐ 高 · **复杂度**：⭐⭐⭐

- [ ] **T1.7** 新闻流页
  - [ ] 新闻列表（Finnhub）
  - [ ] 过滤 + 情绪标签
  - **难度**：⭐ 低 · **复杂度**：⭐

- [ ] **T1.8** 宏观数据页
  - [ ] 宏观日历
  - [ ] 关键指标卡片（CPI/PMI/利率）
  - [ ] 国债收益率曲线
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

- [ ] **T1.9** 自选股 + 筛选器
  - [ ] 自选股管理（localStorage）
  - [ ] 筛选器（OpenBB screen）
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

- [ ] **T1.10** 热力图 + 部署
  - [ ] 板块热力图（ECharts TreeMap）
  - [ ] 部署到 Vercel
  - [ ] 配置域名 + HTTPS
  - **难度**：⭐ 低 · **复杂度**：⭐

**项目 1 里程碑 M1**：连续 2 周每天打开看板，不回退到同花顺

---

## 4. 项目 2：LLM 投资分析

### 4.1 技术栈

| 层 | 选型 |
|---|---|
| **决策引擎** | TradingAgents-CN（5 分析师 + Research Manager + Trader + Risk Manager） |
| **LLM 接口** | MCP Python SDK |
| **LLM** | Claude Opus 4（或任意 OpenAI 兼容） |
| **数据查询** | OpenBB SDK（复用项目 1） |
| **依赖** | Redis + MongoDB（TradingAgents-CN 用） |
| **分发** | 开源 MCP server |

### 4.2 任务拆解

#### TradingAgents-CN 部署（Week 4）

- [ ] **T2.1** 部署 TradingAgents-CN
  - [ ] Redis + MongoDB 起
  - [ ] 配置 AKShare/Tushare（providers/china/ 已就绪）
  - [ ] 验证 CLI 跑通：输入 AAPL → 5 分析师全流程
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

- [ ] **T2.2** 学 TradingAgents-CN 接口
  - [ ] 理解 graph.propagate 流程
  - [ ] 理解 5 分析师 + Research Manager + Trader + Risk Manager 职责
  - [ ] 确认对外暴露的调用点
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

#### MCP Server（Week 5）

- [ ] **T2.3** 写 MCP Server
  - [ ] `pip install mcp`
  - [ ] 项目结构
  - [ ] 简单查询工具（调 OpenBB SDK）：get_quote/get_financials/get_news/get_macro/screen_stocks/compare_stocks
  - [ ] 深度分析工具（调 TradingAgents-CN）：analyze_stock/quick_research/risk_assessment/get_research_report
  - [ ] MCP Inspector 测试
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

- [ ] **T2.4** Claude Desktop 接入
  - [ ] 配置 `claude_desktop_config.json`
  - [ ] 测试：自然语言查询端到端
  - [ ] 测试：多步推理
  - **难度**：⭐ 低 · **复杂度**：⭐

- [ ] **T2.5** 开源分发
  - [ ] README 文档
  - [ ] Docker 化
  - [ ] 发布到 GitHub
  - **难度**：⭐ 低 · **复杂度**：⭐

**项目 2 里程碑 M2**：LLM 生成的分析比"自己查 3 个网站"快 2 倍以上

---

## 5. 项目 3：量化交易

### 5.1 技术栈

| 层 | 选型 |
|---|---|
| **回测** | vectorbt（向量化，主力）+ Qlib（AI 因子，按需） |
| **数据处理** | Polars + DuckDB |
| **数据归档** | Parquet（按日分区） |
| **研究环境** | Marimo notebook |
| **A 股实盘** | QMT / Ptrade / 迅投 |
| **美股实盘** | Alpaca / Interactive Brokers |
| **风控** | 仓位管理 + 止损止盈 + 最大回撤 |
| **监控** | 飞书 / Telegram 推送 |

### 5.2 任务拆解

#### 回测引擎（Week 6-7）

- [ ] **T3.1** 数据归档层
  - [ ] OpenBB SDK 拉历史数据
  - [ ] 存 Parquet（按日分区）
  - [ ] DuckDB 查询层
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

- [ ] **T3.2** vectorbt 策略回测
  - [ ] 安装 vectorbt + 学习 API
  - [ ] 策略 1：双均线
  - [ ] 策略 2：RSI 超买超卖
  - [ ] 策略 3：动量
  - [ ] 回测报告
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

#### 参数寻优（Week 8-9）

- [ ] **T3.3** 网格参数寻优
  - [ ] vectorbt 参数网格
  - [ ] 万级组合并行计算
  - [ ] 热力图可视化
  - **难度**：⭐⭐⭐ 高 · **复杂度**：⭐⭐⭐

- [ ] **T3.4** 组合优化
  - [ ] PyPortfolioOpt 均值-方差优化
  - [ ] 多策略权重分配
  - [ ] walk-forward 验证
  - **难度**：⭐⭐⭐ 高 · **复杂度**：⭐⭐⭐

#### 实盘执行（Week 10-12）

- [ ] **T3.5** A 股实盘（QMT/Ptrade）
  - [ ] 券商开户 + API 权限开通
  - [ ] 写 broker adapter
  - [ ] Paper trading 验证
  - **难度**：⭐⭐⭐⭐ 很高 · **复杂度**：⭐⭐⭐⭐

- [ ] **T3.6** 美股实盘（Alpaca）
  - [ ] Alpaca 账户
  - [ ] 写 broker adapter
  - [ ] Paper trading 验证
  - **难度**：⭐⭐⭐ 高 · **复杂度**：⭐⭐⭐

- [ ] **T3.7** 风控系统
  - [ ] 仓位管理（最大持仓限制）
  - [ ] 止损止盈
  - [ ] 最大回撤熔断
  - **难度**：⭐⭐⭐⭐ 很高 · **复杂度**：⭐⭐⭐⭐

- [ ] **T3.8** 监控 + 告警
  - [ ] 实时持仓监控
  - [ ] 飞书/Telegram 推送
  - **难度**：⭐⭐ 中 · **复杂度**：⭐⭐

- [ ] **T3.9** Qlib AI 因子（按需）
  - [ ] 安装 Qlib
  - [ ] AKShare → Qlib 数据转换
  - [ ] 训练 LightGBM 预测模型
  - [ ] IC 分析
  - **难度**：⭐⭐⭐⭐ 很高 · **复杂度**：⭐⭐⭐⭐

**项目 3 里程碑 M3**：至少 1 个策略在回测中有效（夏普 > 1）且样本外稳定 + Paper trading 1 个月通过

---

## 6. 进度跟踪

### 当前状态

**整体进度**：██░░░░░░░░ 20%
**当前阶段**：项目 1 进行中，T1.2 完成，进入 T1.3（VPS 部署）或 T1.4（前端）

### 项目进度

| 项目 | 进度 | 状态 | 开始 | 完成 |
|---|---|---|---|---|
| 1. tradeck 看板 | 20% | 🔄 进行中 | 2026-07-05 | - |
| 2. LLM 投资分析 | 0% | 未开始 | - | - |
| 3. 量化交易 | 0% | 未开始 | - | - |

### 任务明细

#### 项目 1（10 任务）

| ID | 任务 | 难度 | 状态 | 开始 | 完成 |
|---|---|---|---|---|---|
| T1.1 | 部署 OpenBB Platform | ⭐ | ✅ 2026-07-05 | 2026-07-05 |
| T1.2 | 写 openbb-akshare-provider | ⭐⭐ | ✅ 2026-07-05 | 2026-07-05 |
| T1.3 | VPS 部署 OpenBB | ⭐ | ⬜ | - | - |
| T1.4 | Next.js 项目初始化 | ⭐ | ⬜ | - | - |
| T1.5 | 大盘指数总览页 | ⭐⭐ | ⬜ | - | - |
| T1.6 | 个股详情页 | ⭐⭐⭐ | ⬜ | - | - |
| T1.7 | 新闻流页 | ⭐ | ⬜ | - | - |
| T1.8 | 宏观数据页 | ⭐⭐ | ⬜ | - | - |
| T1.9 | 自选股 + 筛选器 | ⭐⭐ | ⬜ | - | - |
| T1.10 | 热力图 + 部署 | ⭐ | ⬜ | - | - |

#### 项目 2（5 任务）

| ID | 任务 | 难度 | 状态 | 开始 | 完成 |
|---|---|---|---|---|---|
| T2.1 | 部署 TradingAgents-CN | ⭐⭐ | ⬜ | - | - |
| T2.2 | 学 TradingAgents-CN 接口 | ⭐⭐ | ⬜ | - | - |
| T2.3 | 写 MCP Server | ⭐⭐ | ⬜ | - | - |
| T2.4 | Claude Desktop 接入 | ⭐ | ⬜ | - | - |
| T2.5 | 开源分发 | ⭐ | ⬜ | - | - |

#### 项目 3（9 任务）

| ID | 任务 | 难度 | 状态 | 开始 | 完成 |
|---|---|---|---|---|---|
| T3.1 | 数据归档层 | ⭐⭐ | ⬜ | - | - |
| T3.2 | vectorbt 策略回测 | ⭐⭐ | ⬜ | - | - |
| T3.3 | 网格参数寻优 | ⭐⭐⭐ | ⬜ | - | - |
| T3.4 | 组合优化 | ⭐⭐⭐ | ⬜ | - | - |
| T3.5 | A 股实盘（QMT/Ptrade） | ⭐⭐⭐⭐ | ⬜ | - | - |
| T3.6 | 美股实盘（Alpaca） | ⭐⭐⭐ | ⬜ | - | - |
| T3.7 | 风控系统 | ⭐⭐⭐⭐ | ⬜ | - | - |
| T3.8 | 监控 + 告警 | ⭐⭐ | ⬜ | - | - |
| T3.9 | Qlib AI 因子（按需） | ⭐⭐⭐⭐ | ⬜ | - | - |

### 里程碑

| 里程碑 | 验证标准 | 状态 |
|---|---|---|
| M1 | 连续 2 周每天用看板，不回退到同花顺 | ⬜ |
| M2 | LLM 分析比"自己查 3 个网站"快 2 倍 | ⬜ |
| M3 | 至少 1 个策略夏普 > 1 + Paper trading 1 个月通过 | ⬜ |

---

## 7. 决策记录

### 7.1 已决策（2026-07-04）

| 决策 | 选择 | 理由 |
|---|---|---|
| 项目 1 名字 | 保留 tradeck | 已有 GitHub 仓库 + 品牌认知 |
| 项目 1 前端 | 自建 Next.js + shadcn/ui | AGPL 协议风险 + 完全可控 |
| 项目 1 数据层 | OpenBB Platform | 省 2-3 周数据层开发 |
| A 股数据接入 | 自写 openbb-akshare-provider | 官方无 AKShare Provider |
| 项目 2 决策引擎 | TradingAgents-CN | A 股/港股/美股分区已就绪 + Apache 2.0 |
| 项目 2 集成方式 | MCP 包装 TradingAgents-CN | 通用协议，任意 LLM 接入 |
| 项目 3 回测 | vectorbt | 向量化快 + 简单 |
| 项目 3 AI 因子 | Qlib（按需） | 学习成本高，验证后投入 |
| 项目 3 实盘 | A 股 QMT/Ptrade + 美股 Alpaca/IB | 用户确认 |
| TradingAgents-CN 角色 | 决策引擎（非数据源） | 对外数据查询走 OpenBB |

### 7.2 待决策

| 决策点 | 选项 | 决策时机 |
|---|---|---|
| 项目 2/3 名字 | 待定 | 启动时 |
| VPS 选型 | Hetzner / DigitalOcean / 腾讯轻量 | T1.3 前 |
| 是否下载 OpenBB 源码 | SDK 即可 / 源码参考 | T1.1 时 |
| Tushare 是否引入 | 按需 | 项目 3 深度 A 股时 |
| Qlib 是否投入 | 看 T3.2-T3.4 结果 | 项目 3 后期 |

---

## 8. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| FMP 数据不完整 | 中 | 中 | 数据层抽象，可换 Polygon |
| OpenBB 学习曲线 | 低 | 低 | 1 天看 Quick Start |
| akshare-provider 卡住 | 中 | 中 | 先用 FMP A 股兜底 |
| TradingAgents-CN 部署复杂 | 中 | 中 | Docker 一键起 |
| LLM 决策质量 | 中 | 高 | 不盲从，人工复核 |
| 回测过拟合 | 高 | 高 | 样本内外 + walk-forward |
| A 股实盘合规 | 中 | 高 | 确认券商 API 权限 |
| 实盘风控失效 | 中 | 很高 | 三道防线 + Paper trading |

---

## 9. 变更记录

| 日期 | 变更 | 原因 |
|---|---|---|
| 2026-07-03 | 初始方案（单项目两阶段） | 初次规划 |
| 2026-07-03 | 架构修正：自建 FastAPI → OpenBB Platform | 自建重复造轮子 |
| 2026-07-04 | 重构为三个独立项目 | 用户明确三个独立项目 |
| 2026-07-04 | TradingAgents-CN 替代原 MCP 自建 | CN 版已配置 A 股/港股/美股 + Apache 2.0 |
| 2026-07-04 | 项目 3 加入实盘（A 股 + 美股） | 用户明确要做实盘 |

---

## 10. 参考资源

### 官方文档
- [OpenBB Platform Docs](https://docs.openbb.co/odp/)
- [OpenBB Provider Extension](https://docs.openbb.co/odp/python/developer/extension_types/provider)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [vectorbt 文档](https://vectorbt.dev/)
- [Qlib 文档](https://github.com/microsoft/qlib)
- [TradingAgents-CN](https://github.com/)（本地已 clone）

### 本地参考项目
- `/home/zhaoqg/projects/TradingAgents-CN` — 项目 2 决策引擎
- `/home/zhaoqg/projects/TradingAgents` — 原版（对比参考）
- `/home/zhaoqg/projects/tickflow-stock-panel` — 项目 3 借鉴（回测+策略）
- `/home/zhaoqg/projects/OpenStock` — 项目 1 UI 借鉴（不 fork）

### 关联文档
- [tech-analysis.html](./tech-analysis.html) — 完整技术分析

---

## 使用说明

**活文档，随项目进展持续更新**：

1. **开始任务时**：⬜ → 🔄 + 填开始日期
2. **完成任务时**：🔄 → ✅ + 填完成日期
3. **每周回顾**：更新进度百分比
4. **方案变更**：决策表加行 + 变更记录原因
5. **遇到新决策点**：加到"7.2 待决策"

**状态图标**：⬜ 未开始 · 🔄 进行中 · ✅ 完成 · ⚠️ 阻塞 · ❌ 取消

**难度参考**：⭐ 低（半天内） · ⭐⭐ 中（1-3 天） · ⭐⭐⭐ 高（3-5 天） · ⭐⭐⭐⭐ 很高（1 周+）
