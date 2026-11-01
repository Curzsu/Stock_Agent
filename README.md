# FINEX - AI 智能股票分析系统

基于 LangGraph 多智能体架构的 A 股智能分析平台，集成 MCP 协议实现多维度股票评估。

![image-20260808121518331](images-README/image-20260808121518331.png)

![image-20260808121616327](images-README/image-20260808121616327.png)

## 功能特性

- **多维度分析**：从基本面、技术面、价值面、新闻面四个角度全面评估股票
- **多智能体协作**：基于 LangGraph 的 DAG 工作流，四个分析 Agent 并行执行
- **MCP 协议集成**：通过 Model Context Protocol 统一接入 A 股数据源
- **实时进度追踪**：支持异步任务处理，前端实时轮询分析进度
- **综合报告生成**：AI 自动生成结构化股票分析报告
- **涂鸦 PDF 报告**：基于 Pandoc + Eisvogel 排版，蜡笔人物融入奶油色封面，配合手写感标题、涂鸦编号和彩色表格，支持中文、目录与公式
- **真实行情展示**：首页展示上证指数日终行情及交易日期，行情不可用时明确提示，不使用模拟价格填充
- **结果有效性校验**：空响应、未完成的工具调用和因输出上限截断的模型响应会进入失败状态，避免被当作成功报告
- **故障恢复**：报告加载失败自动尝试最多三次，也可手动重新加载；MCP 数据连接失效后，后续分析或单项重试会重建会话

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   (HTML/CSS/JavaScript)                      │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP/WebSocket
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                          │
│                   (RESTful API)                              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   LangGraph Workflow                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │基本面Agent│ │技术面Agent│ │价值面Agent│ │新闻面Agent│       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
│       │            │            │            │              │
│       └────────────┴────────────┴────────────┘              │
│                          │                                   │
│                          ▼                                   │
│                  ┌──────────────┐                           │
│                  │  汇总 Agent   │                           │
│                  └──────────────┘                           │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server                                │
│              (A股数据工具集 - 20+ Tools)                      │
│   实时行情 | 历史K线 | 财务指标 | 资金流向 | ...              │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| AI 框架 | LangGraph, LangChain |
| 数据协议 | MCP (Model Context Protocol) |
| 数据源 | Baostock, A股行情接口 |
| LLM | OpenAI 兼容 API (OpenRouter 等) |
| PDF 排版 | Pandoc 3 + Eisvogel 3.5.1 + XeLaTeX / Tectonic |

Google AI Studio 的 Gemini Key 可配合 Google 的 OpenAI 兼容接口使用：
`https://generativelanguage.googleapis.com/v1beta/openai/`，模型填写账号可用的 Gemini 模型 ID。
四个分析 Agent 使用共享兼容层，在本项目的非流式多轮工具调用中原样保留并回传
`extra_content.google.thought_signature`，避免工具已执行、提交结果时却因缺少签名而被拒绝。
兼容层与离线回归基于 `langchain-openai>=1.1.11,<2.0`。

当四路分析都未取得有效结果时，系统会明确报错并停止汇总，不会再用常识推演生成投资结论。
部分维度缺失时只汇总成功取得的信息，并标明缺失项。修复前已生成的缺数据报告需重新发起分析。

## 快速开始

### 环境要求

- Python 3.10+
- uv (Python 包管理器)

### 安装步骤

1. **克隆项目**

```bash
git clone https://github.com/your-username/finex.git
cd finex
```

2. **创建虚拟环境**

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. **安装依赖**

```bash
pip install -r requirements.txt
```

4. **配置环境变量**

```bash
# 复制配置模板
cp agents/.env.example agents/.env

# 编辑 .env 文件，填入你的 API Key
# OPENAI_API_KEY=your-api-key-here
# OPENAI_BASE_URL=https://api.openai.com/v1
```

5. **启动服务**

```bash
# Windows
scripts\start_server.bat

# Linux/Mac
bash scripts/start_server.sh

# 或手动启动
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8100
```

6. **访问应用**

打开浏览器访问 http://localhost:8100

### PDF 报告环境

PDF 在后台独立生成；Markdown 报告和在线阅读不依赖排版工具。
模板固定使用 [Eisvogel 3.5.1](https://github.com/Wandmalfarbe/pandoc-latex-template/releases/tag/v3.5.1)，
随项目分发并保留 BSD-3-Clause 许可证。FINEX 暖色主题独立存放，方便升级上游模板。
封面插画资源随 `pdf_templates/assets` 分发；生成报告时直接复用本地图片，不需要调用图像模型。
正文章节使用薄荷、蓝、淡紫和蜜桃色标签，配合微倾斜的编号贴纸、手绘下划线和蓝色列表标记。
摘要与风险卡片使用圆角便签和轻量纸张阴影；页边的太阳、星星轨迹和小叶子按页轮换，页码收在淡黄色标签上。
中文标题优先使用楷体，英文标题优先使用
Comic Sans MS；缺少系统字体时使用 TeX 自带的 FandolKai / TeX Gyre 字体。
封面中文使用更圆润的幼圆体，缺少该字体时回退到 FandolHei；人物收在右下方，约占封面底部三成高度，为标题留出空间。
正文会自动加粗 ROE、毛利率、市盈率等财务术语和带单位的指标数值；已有加粗、代码、公式与链接地址保持完整。
摘要与风险分别使用薄荷色、蜜桃色提示卡片，基本面、估值与投资建议中的完整标签列表会转成信息表，
技术面与新闻保留简短要点。新报告也会按这些规则生成 Markdown；旧报告无需再次调用模型即可重新排版。

Windows x64 可安装到项目的 `.tools/pdf`，不修改全局 PATH：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_pdf.ps1
```

脚本从官方 GitHub 发布页下载固定版本 Pandoc 3.13、Tectonic 0.17.0，并校验 SHA-256。
首次使用 Tectonic 时会联网下载所需 LaTeX 包，后续使用本地缓存；报告在本机排版。
Linux/macOS 需安装 [Pandoc 3](https://pandoc.org/installing.html) 和
[Tectonic](https://tectonic-typesetting.github.io/en-US/install.html)，也可使用带有 XeLaTeX、
xeCJK、TikZ、KOMA-Script 等包的 TeX Live / MiKTeX。模板所需包见
[Eisvogel 官方说明](https://github.com/Wandmalfarbe/pandoc-latex-template#required-latex-packages)。

可在 `agents/.env` 自定义排版工具、中文字体和超时，修改后重启服务：

```dotenv
# 通常无需指定，自动发现项目便携工具和 PATH 中的程序
# PANDOC_PATH=C:/path/to/pandoc.exe
# PDF_LATEX_ENGINE=tectonic
# PDF_CJK_FONT=Noto Sans CJK SC
PDF_TIMEOUT_SECONDS=300
```

默认优先使用 XeLaTeX，找不到时使用 Tectonic；中文字体在 Windows 为 Microsoft YaHei，
其他平台为 FandolHei-Regular.otf。自定义字体必须已安装或在 LaTeX 字体库中可用。

无需重新分析或调用模型，即可为已有 Markdown 生成新版 PDF：

```bash
python scripts/generate_pdf.py "agents/reports/md/report_example.md" --date 2026-10-31
```

输出路径沿用 `reports/md/文件名.md` → `reports/pdf/文件名.pdf`；其他目录则输出到 Markdown 旁边。
已生成的旧 PDF 保持原样，手动执行上述命令可重新排版。
每次生成使用独立临时目录，仅在成功后替换成品；字体缺失、工具缺失或超时会记录明确失败状态，
前端会停止等待，不会下载半成品。

## 项目结构

```
finex/
├── backend/                    # 后端服务
│   └── server.py              # FastAPI 主程序 (REST API + LangGraph 调度)
├── frontend/                   # 前端页面
│   └── index.html             # 单页应用 (Glassmorphism 风格)
├── agents/                     # AI 多智能体系统
│   ├── src/
│   │   ├── main.py            # Agent 编排主入口 (CLI)
│   │   ├── agents/            # 各领域 Agent (基于 create_react_agent)
│   │   │   ├── fundamental_agent.py   # 基本面分析
│   │   │   ├── technical_agent.py     # 技术面分析
│   │   │   ├── value_agent.py         # 价值面分析
│   │   │   ├── news_agent.py          # 新闻面分析
│   │   │   └── summary_agent.py       # 汇总分析 (生成最终报告)
│   │   ├── tools/             # MCP 工具集成
│   │   │   ├── mcp_client.py         # MCP 客户端 (进程级单例)
│   │   │   ├── mcp_config.py         # MCP 服务连接配置
│   │   │   └── openrouter_config.py  # OpenRouter 配置
│   │   └── utils/             # 共享工具模块
│   │       ├── state_definition.py   # AgentState 状态定义 (TypedDict)
│   │       ├── workflow_builder.py   # build_workflow() 工作流工厂
│   │       ├── agent_config.py       # Agent 共享配置 (递归深度/超时/LLM 参数)
│   │       ├── baostock_helper.py    # Baostock 线程安全访问
│   │       ├── stock_extractor.py    # 股票代码/名称提取 (共享模块)
│   │       ├── execution_logger.py   # 执行日志
│   │       ├── llm_clients.py        # LLM 客户端管理
│   │       ├── logging_config.py     # 日志配置
│   │       ├── pdf_converter.py      # Pandoc 调用、原子发布、后台 PDF 任务
│   │       ├── pdf_styles.py         # Markdown 与封面元数据
│   │       └── pdf_templates/        # Eisvogel 模板、许可证与 FINEX 暖色主题
│   ├── reports/               # 生成的分析报告 (md/ + pdf/, gitignored)
│   └── .env                   # 环境配置 (gitignored)
├── mcp-server/                 # MCP 数据服务 (A 股行情/财务/宏观数据)
│   ├── mcp_server.py          # MCP 服务器入口 (FastMCP)
│   ├── pyproject.toml         # MCP 服务项目配置
│   ├── src/
│   │   ├── baostock_data_source.py   # Baostock 数据源实现
│   │   ├── data_source_interface.py  # 数据源接口
│   │   ├── utils.py           # Baostock 登录上下文与通用取数
│   │   ├── formatting/        # 数据格式化
│   │   │   └── markdown_formatter.py
│   │   └── tools/             # MCP 工具集
│   │       ├── stock_market.py       # 股票行情工具
│   │       ├── financial_reports.py  # 财务报表工具
│   │       ├── analysis.py           # 分析工具
│   │       ├── indices.py            # 指数工具
│   │       ├── macroeconomic.py      # 宏观经济工具
│   │       ├── market_overview.py    # 市场概览工具
│   │       ├── news_crawler.py       # 新闻爬取工具
│   │       └── date_utils.py         # 日期工具
│   └── tests/                 # MCP 服务测试
│       └── test_crawl_news_no_model.py
├── scripts/                    # 启动脚本
│   ├── start_server.bat       # Windows 启动脚本
│   └── start_server.sh        # Linux/Mac 启动脚本
├── tests/                      # 测试套件
│   ├── test_baostock_concurrency.py   # Baostock 并发安全
│   ├── test_agent_failure_handling.py # Agent 失败处理
│   ├── test_workflow_builder.py       # 工作流工厂拓扑
│   ├── test_stock_extractor.py        # 股票代码提取
│   ├── test_pdf_path.py               # PDF 路径推导
│   ├── test_summary_agent_lazy_torch.py # summary_agent 懒加载
│   └── test_end_to_end.py             # 端到端冒烟测试
├── docs/                       # 设计文档
├── images-README/              # README 截图资源
├── requirements.txt            # Python 依赖 (web 应用核心)
├── AGENTS.md                   # Agent 工作流配置
├── TODO.md                     # 待办事项
└── README.md
```

## 持续集成与测试

GitHub Actions 在 PR 和默认分支 `v2.0` 的 push 后自动运行一个 `checks` 作业：
Python/JavaScript 语法检查、前端测试，以及应用和 MCP 的离线回归。
不需要配置 API Key，也不会调用真实模型或行情服务。

本地使用 Python 3.10、Node.js 22 和 uv 0.8.12，复现同一套检查：

```bash
python -m compileall -q backend agents/src mcp-server/src mcp-server/mcp_server.py scripts tests mcp-server/tests
node --check frontend/workbench.js
node --test tests/frontend/test_workbench.cjs

python -m pip install -r requirements-test.txt
python scripts/run_ci_tests.py app

uv sync --locked --directory mcp-server --python 3.10
uv run --locked --no-sync --directory mcp-server python ../scripts/run_ci_tests.py mcp
```

最后检查 MCP 实际运行环境中的依赖版本（先完成上面的同步）：

```bash
# Linux/macOS
UV_PYTHON=3.10 UV_LOCKED=1 UV_NO_SYNC=1 python scripts/run_ci_tests.py runtime
```

```powershell
# Windows PowerShell
$env:UV_PYTHON = "3.10"
$env:UV_LOCKED = "1"
$env:UV_NO_SYNC = "1"
python scripts/run_ci_tests.py runtime
```

执行脚本会忽略本机 `.env` 并按文件启动独立 Python 进程，避免 Agent 与 MCP
都使用 `src` 包名造成冲突；失败、超时或未收集到测试都会返回失败状态。
历史联网诊断脚本不纳入这套回归。结果直接查看 Actions 日志。

需要阻止失败 PR 合并时，在 GitHub 仓库规则中将 `checks` 设为必过检查。

## API 文档

### 启动分析

```http
POST /api/analyze
Content-Type: application/json

{
  "query": "比亚迪"
}
```

响应：
```json
{
  "analysis_id": "abc12345",
  "status": "started",
  "message": "Analysis started for: 比亚迪"
}
```

### 查询状态

```http
GET /api/status/{analysis_id}
```

响应：
```json
{
  "analysis_id": "abc12345",
  "status": "running",
  "progress": {
    "fundamental": "completed",
    "technical": "running",
    "value": "completed",
    "news": "completed",
    "summary": "waiting"
  }
}
```

### 获取结果

```http
GET /api/result/{analysis_id}
```

### 健康检查

```http
GET /api/health
```

## 支持的股票

支持 A 股主流上市公司，包括但不限于：

- 贵州茅台 (600519)
- 比亚迪 (002594)
- 宁德时代 (300750)
- 中国平安 (601318)
- 招商银行 (600036)
- 腾讯控股 (00700)
- 阿里巴巴 (09988)
- ...

## 配置说明

### baostock 连接与黑名单保护

Web 行情/股票校验与 MCP 数据工具共用 `finex_data/baostock_runtime.py`。
同一状态目录下的进程通过操作系统文件锁串行访问；锁覆盖登录、查询、全部分页、登出和关闭连接。
查询结果先完整读入内存，再释放连接，避免 Web 的闲置连接与 MCP 登录重叠。
因此每次查询会建立和关闭会话，可能增加请求耗时；进程退出后系统自动释放锁。

收到 `10001011` 时立即停止重试，并将本地暂停记录保存到 `.runtime/baostock/blacklist.json`。
暂停期间 Web/MCP 请求均直接返回错误，不连接 baostock；服务重启也保留该记录。
若磁盘写入失败，错误日志会明确提示，此时仅本进程能保留暂停保护，需先恢复状态目录的可写性。
默认保护 6 小时，`BAOSTOCK_BLACKLIST_COOLDOWN_SECONDS` 可设置至少 60 秒的有限秒数。
这只是本地保护期限，不能解除官方黑名单，也不代表官方届时一定释放；实际释放时间见
[官方黑名单页面](https://www.baostock.com/blacklist)。到期后的下一个请求才会尝试登录，仍被拒绝则再次暂停。

默认状态目录在项目根目录。若同一机器运行多个项目副本，需为所有实例设置相同的绝对路径
`FINEX_BAOSTOCK_STATE_DIR`，并保证它们使用相同共享运行时；本项目的锁无法协调其他机器或外部程序。
请勿删除正在使用的 `access.lock`，否则可能破坏进程间互斥。修改环境变量后重启服务。

页面中的 API 配置仅允许在运行服务的本机，通过 `localhost`、`127.0.0.1` 或 `[::1]` 访问并修改。更换 Base URL 时需要重新输入对应的 API Key；已有密钥不会自动用于新地址。

### 环境变量

汇总模型的输出上限由 `SUMMARY_MAX_TOKENS` 控制，默认 12000 tokens，
需符合所选模型及供应商的限制，修改后重启服务。汇总正文会被要求精简，
遇到 `length` / `max_tokens` 截断时仅自动重试一次，进一步压缩篇幅；
两次生成共用原有 480 秒超时预算（`REACT_TIMEOUT_SECONDS`）。
每次响应都会在校验前记录结束原因及供应商提供的 token 用量。
若仍失败，可在综合研判卡片点击“重试汇总”，复用已完成的分析。
失败的历史卡片也可打开；该能力依赖当前服务进程中保留的任务数据。

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API Key | 是 |
| `OPENAI_BASE_URL` | API 基础 URL（支持自定义端点） | 否 |
| `OPENAI_MODEL` | 使用的模型名称 | 否 |

## 许可证

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。
