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
│   │       ├── pdf_converter.py      # Markdown -> PDF 转换
│   │       └── pdf_styles.py         # PDF 样式与解析
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
