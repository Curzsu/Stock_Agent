# LangSmith 追踪

项目使用 [langchain-ai/langsmith-python](https://github.com/langchain-ai/langsmith-python)
维护的 Python SDK，依赖固定为 `langsmith==0.14.17`。迁移后 PyPI 包名仍是 `langsmith`；
这里通过 PyPI 安装，不从已归档的 `langsmith-sdk` 仓库安装。

## 配置与启动

1. 在 LangSmith 创建 API Key，确认所属区域与 workspace 类型。
2. 编辑本机 `agents/.env`，参考下例；不要将密钥提交到 Git。
3. 在项目根目录安装依赖并重启服务：

```powershell
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe backend/server.py
```

Project-based workspace 使用：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=填写你的密钥
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=finex-dev
LANGSMITH_TRACING_SAMPLING_RATE=1
```

Agent-based workspace 先在 LangSmith 创建 agent，然后复制其**标识符**，不是显示名称。
去掉 `LANGSMITH_PROJECT`，改用：

```dotenv
LANGSMITH_AGENT_ID=你的agent标识符
LANGSMITH_AGENT_ENVIRONMENT=development
```

环境支持 `local`、`development`、`staging`、`production`。区域 Endpoint 应与账号一致，
EU 区使用 `https://eu.api.smith.langchain.com`，APAC 区使用 `https://apac.api.smith.langchain.com`，
AWS US 区使用 `https://aws.api.smith.langchain.com`。Key 不能跨区域使用；组织级密钥必要时设置 `LANGSMITH_WORKSPACE_ID`。
如果公共 `/info` 正常，而带 Key 的项目读写都返回 `403`，也要核对目标 Workspace ID。
本项目可通过 `LANGSMITH_WORKSPACE_ID` 明确工作区；仅设置 project 名称不能替代工作区选择。
具体以 LangSmith 设置页提供的配置为准，参见
[官方 LangChain 接入说明](https://docs.langchain.com/langsmith/trace-with-langchain) 和
[agent/environment 路由说明](https://docs.langchain.com/langsmith/log-traces-to-agent)。

未设置 `LANGSMITH_TRACING=true` 或没有 Key 时，分析路径不创建追踪客户端、不上传。
现有本地日志继续保留。正常追踪由 SDK 后台批量发送，服务退出时最多等 5 秒刷新；
强制结束进程可能丢失尚未发送的记录。网络或鉴权失败请查 SDK 警告；本地业务分析不依赖云端写入成功。

## 查看一次分析

在目标 project 或 agent/environment 内，用 `metadata.analysis_id` 搜索 Web 任务的分析 ID：

- `finex.analysis`：完整研究的父 trace；CLI 也会生成分析 ID。
- `finex.agent.fundamental/technical/value/news/summary`：五个角色，各有独立 span。
- 角色下的 LangGraph、模型调用和工具调用：由原生 LangChain 追踪自动记录，每一轮都有输入、输出、耗时和响应元数据。
- `mcp.queue`：等候共享工具锁的耗时；`mcp.execute`：获得锁后的实际调用耗时。工具名在 `metadata.tool`。
- `finex.retry`：单项/汇总重试的新 trace，保留原 `analysis_id`，并带 `metadata.retry`；并发分析不会共享父 span。

Agent 捕获异常并返回 `*_analysis_error` / `summary_error` 时，其业务 span 仍会被标记失败。
父研究存在失败维度时也记录错误，即使部分研究足以生成报告；这不改变页面原有的部分成功行为。
超时取消时可看到已经完成的模型轮次和取消/超时的位置。队列等待不计入现有工具超时的规则保持不变。

## Token 与数据范围

模型 span 保存供应商实际返回的 `usage_metadata` / `token_usage` 与 `finish_reason`，
记录发生在应用校验之前，所以 `length` 截断不会因为应用随后拒收文本而丢掉已返回的用量。
供应商没有返回用量、请求尚未返回就超时的情况，精确 token 仍然未知；不要把未知当成 0。
自定义模型别名也可能需要在 LangSmith 配置价格映射，才能准确计算费用。历史丢失的记录不能补回。

开启后，原生追踪会上传提示词、模型回答、工具参数/结果以及 LangGraph 状态中的研究数据。
自定义业务 span 只添加分析 ID、股票、角色、重试及状态，不添加 API Key。
可设置 `LANGSMITH_HIDE_INPUTS=true` / `LANGSMITH_HIDE_OUTPUTS=true` 隐藏对应正文；
分析 ID、股票等元数据仍会保留，SDK 的 Key 应通过服务端环境变量注入。

开发排障默认 `LANGSMITH_TRACING_SAMPLING_RATE=1`；上线后可按量降低，例如 `0.1`。
采样会减少可查到的分析，不保证每次失败都会被保留。按请求量与实际 trace 用量设置预算。

## 验证

离线回归运行真实 SDK/LangChain 回调，使用内存客户端替换上传边界，验证并行隔离、
父子层级、截断用量、错误状态、MCP 等待与执行以及重试，不调用付费模型、不上传研究数据：

```powershell
$env:PYTHON_DOTENV_DISABLED='1'
venv\Scripts\python.exe -m unittest discover -s tests -p test_observability.py -v
```

首次真实验收：配置 Key 和目标并重启后，发起一次正常研究，再在云端按 `analysis_id` 查到
父 trace、五路角色、模型 token 和 MCP 阶段；重试失败角色后确认出现同 ID 的 `finex.retry`。
只有这一步能证明你的网络、Key、workspace 和区域配置实际可用。
