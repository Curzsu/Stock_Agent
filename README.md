# FINEX - AI 智能股票分析系统

基于 LangGraph 多智能体架构的 A 股智能分析平台，集成 MCP 协议实现多维度股票评估。

![image-20260401120410821](images-README/image-20260401120410821.png)

## 功能特性

- **多维度分析**：从基本面、技术面、价值面、新闻面四个角度全面评估股票
- **多智能体协作**：基于 LangGraph 的 DAG 工作流，四个分析 Agent 并行执行
- **MCP 协议集成**：通过 Model Context Protocol 统一接入 A 股数据源
- **实时进度追踪**：支持异步任务处理，前端实时轮询分析进度
- **综合报告生成**：AI 自动生成结构化股票分析报告

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
| LLM | OpenAI / Azure OpenAI / 其他兼容 API |
| 部署 | Docker, Docker Compose |

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
│   │   ├── main.py            # Agent 编排主入口
│   │   ├── agents/            # 各领域 Agent
│   │   │   ├── fundamental_agent.py   # 基本面分析
│   │   │   ├── technical_agent.py     # 技术面分析
│   │   │   ├── value_agent.py         # 价值面分析
│   │   │   ├── news_agent.py          # 新闻面分析
│   │   │   └── summary_agent.py       # 汇总分析
│   │   ├── tools/             # MCP 工具集成
│   │   │   ├── mcp_client.py         # MCP 客户端
│   │   │   └── openrouter_config.py  # OpenRouter 配置
│   │   └── utils/             # 工具函数
│   │       ├── execution_logger.py   # 执行日志
│   │       ├── llm_clients.py        # LLM 客户端管理
│   │       └── state_definition.py   # 状态定义
│   ├── logs/                  # Agent 执行日志
│   ├── reports/               # 生成的分析报告
│   └── .env                   # 环境配置
├── mcp-server/                 # MCP 数据服务
│   ├── mcp_server.py          # MCP 服务器入口
│   ├── src/
│   │   ├── baostock_data_source.py   # Baostock 数据源
│   │   ├── data_source_interface.py  # 数据源接口
│   │   └── tools/             # MCP 工具集
│   │       ├── stock_market.py       # 股票行情工具
│   │       ├── financial_reports.py  # 财务报表工具
│   │       ├── analysis.py           # 分析工具
│   │       ├── indices.py            # 指数工具
│   │       ├── macroeconomic.py      # 宏观经济工具
│   │       ├── market_overview.py    # 市场概览工具
│   │       └── news_crawler.py       # 新闻爬取工具
│   └── pyproject.toml         # MCP 服务项目配置
├── scripts/                    # 启动脚本
│   ├── start_server.bat       # Windows 启动脚本
│   └── start_server.sh        # Linux/Mac 启动脚本
├── tests/                      # 测试套件
│   ├── test_mcp_direct.py     # MCP 协议直连测试
│   └── test_langchain_mcp.py  # LangChain MCP 适配测试
├── logs/                       # 应用运行日志
├── Nasdaq Sentiment Fine-tuning Task/  # Nasdaq 情感分析微调
│   ├── data_process.py        # 数据处理
│   ├── train_qwen_sentiment.py # 情感模型训练
│   └── train_qwen_risk.py     # 风险模型训练
├── requirements.txt            # Python 依赖
└── README.md
```

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

### 环境变量

| 变量名 | 说明 | 必填 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API Key | 是 |
| `OPENAI_BASE_URL` | API 基础 URL（支持自定义端点） | 否 |
| `OPENAI_MODEL` | 使用的模型名称 | 否 |

## 许可证

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。
