# FINEX 轻量 CI 设计

更新日期：2026-10-24。状态：已按本设计实现工作流与本地执行脚本；尚未推送或在 GitHub runner 执行。

## 设计选择

按个人项目的维护成本设计：一个 workflow、一个 job、单一 Linux/Python 环境，自动执行已有离线测试和基础语法检查。

上一版的多作业门禁、定时维护、手动联调与兼容矩阵均移出本次范围。也不增加真实模型/行情调用、容器发布、浏览器端到端测试、专用报告平台或覆盖率门槛。

## 触发与执行环境

- 文件：`.github/workflows/ci.yml`。
- 自动触发：`pull_request`，以及 push 到已确认的仓库默认分支 `v2.0`。
- 不配置 `workflow_dispatch`、`schedule` 或任何需要人工启动的验证流程。
- 只运行一个名为 `checks` 的 job，必过检查选择 `checks`；失败步骤直接让整个 job 失败，不增加汇总 job。
- runner 使用 `ubuntu-24.04`，Python 3.10，Node 22；uv 固定版本。MCP 环境也显式选择 Python 3.10。
- 不使用版本/操作系统矩阵。设置整个 job 的超时为 15 分钟，同一 PR 新提交取消旧运行。
- 第一版不做文件路径过滤，避免漏检和必过检查 Pending。

## 一个 job 中的步骤

| 顺序 | 步骤 | 内容 |
| --- | --- | --- |
| 1 | 拉取代码、准备环境 | checkout、Python、Node、uv；缓存依赖下载目录 |
| 2 | 快速检查 | Python compileall；Node 检查外部 JavaScript 语法并执行现有前端测试 |
| 3 | 安装应用依赖 | 根 requirements.txt，加测试明确使用的 httpx 等必要依赖 |
| 4 | 应用回归 | 逐文件运行现有应用侧 unittest，包括 mock 工作流回归 |
| 5 | 安装 MCP 依赖 | 沿用现有 pyproject.toml 与 uv.lock，locked 同步并固定解释器 |
| 6 | MCP 回归 | 在 MCP 环境逐文件执行日期、新闻、财报回退测试，以及现有运行时版本检查 |

先执行成本较低的语法/前端检查，再安装 Python 依赖。失败直接停止，不使用 continue-on-error。

不引入 npm 项目：前端直接使用 `node --test tests/frontend/test_workbench.cjs`。Python 使用内置 unittest，不迁移 pytest，不新增 Ruff/actionlint 工具链。

## 测试如何运行

沿用现有测试，通过一个短 Python 脚本按文件启动 unittest discovery 子进程；每个文件设置 180 秒超时，输出用例结果，任意失败返回非零退出码。使用标准库即可，不建设测试调度框架或额外分类配置文件。

必须分进程：`agents/src` 与 `mcp-server/src` 包名相同，混合收集会产生导入冲突；现有工作流测试也注明同进程运行的 PyO3 限制。

- **应用侧**：根 tests 下的现有离线回归，包括 Agent 失败处理、会话/API 配置、Baostock 并发、行情转换、股票提取、PDF 路径、工作流、MCP 客户端和懒加载测试。`test_end_to_end.py` 已 mock 模型/MCP/PDF，属于这一组。
- **MCP 侧**：`mcp-server/tests/test_date_utils.py`、`mcp-server/tests/test_crawl_news_no_model.py`、`tests/test_mcp_data_fallbacks.py`，使用 MCP 环境执行。
- **运行时检查**：依赖安装完成后执行已有 `tests/test_mcp_runtime.py`，确保其 uv 子进程使用相同、已同步的 MCP 环境，不重新解析或下载依赖。
- **排除诊断脚本**：`tests/test_mcp_direct.py`、`tests/test_langchain_mcp.py`、`mcp-server/test_baostock.py`、`agents/test_extraction.py` 不纳入自动测试发现；这些脚本存在路径、联网或失败只打印的问题，本次不改造它们，也不配置人工运行入口。

根 tests 按文件自动发现，显式排除/路由上述特殊文件；MCP tests 同样自动发现。新增普通测试文件无需修改白名单。每个待测文件必须实际收集到测试，收集为零不能算通过。

本版复用已有回归，不另建 HTTP/MCP/PDF 真实进程冒烟套件。它覆盖业务回归，尚不保证真实外部服务或完整部署链路可用。

## 保留的基本约束

- 不配置真实 API key，也不复制本机 .env；测试使用假配置和 mock，不消耗模型额度。
- 修正已知 mock 缺口，测试不访问真实模型、行情和新闻服务；不额外建设覆盖所有子进程的网络拦截框架。
- 设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`TZ=Asia/Shanghai`、`USE_LOCAL_MODEL=api`；runner 捕获输出时显式使用 UTF-8。
- 缓存包下载目录，不缓存整套虚拟环境；缓存键关联依赖文件、Python 和系统。
- 根应用暂沿用 requirements.txt，不把依赖管理迁移或全量锁文件建设作为首版 CI 的前提。依赖下限可能导致版本漂移，这是明确保留的限制；出现依赖兼容问题时固定相关版本。MCP 继续检查现有锁文件一致性。
- 默认 `permissions: contents: read`，checkout 不保留写凭证，Actions 固定完整 commit SHA。不使用 pull_request_target 执行 PR 代码。
- 结果直接看 Actions 原生日志，不额外上传 artifacts 或生成报告。日志不得打印密钥或完整环境变量。

## 接入时的小修正

1. PDF 路径保持主机原生语义；测试分别用 ntpath/posixpath 验证 Windows 与 POSIX 行为，不再把两种路径语义混在一个断言中。
2. 新闻测试补齐文章正文 HTTP 请求 mock，并验证真实解析出的正文内容；不再尝试访问 example.com。
3. 在新建的 Python 3.10 应用环境和独立 locked Python 3.10 MCP 环境逐文件确认回归。原先 Windows 卡顿已定位到沙箱阻止 asyncio 内部 socket，放行该系统调用后验证通过。
4. 根应用的 Baostock 下限与 MCP 对齐为 0.9.3；requirements-test.txt 显式声明 httpx、packaging、支持忽略 .env 的 python-dotenv，并固定 uv 0.8.12。

这些修正限定在让现有离线测试可靠执行所需的范围，不扩展为业务重构。

## 最终改动与验收

已增加 `.github/workflows/ci.yml`、一个标准库测试执行脚本及其失败/超时/空收集回归，并小幅更新依赖声明、现有测试和 README。

验收：PR 或默认分支 push 后自动运行；无需 API key、人工启动或额外服务；现有回归失败或超时会让 `checks` 失败；忽略本机 .env，在干净依赖环境中可复现。

热缓存运行目标约 3–5 分钟，实际以首次 GitHub 执行结果校准。若需要阻止失败 PR 合并，可在 GitHub 仓库规则中将 `checks` 设为必过项；单纯提交 YAML 不会自动启用分支保护。

应用、MCP 和运行时回归已在独立新建的 Python 3.10 环境通过，前端 28 项通过（本地 Node 24，工作流固定 Node 22）。工作流 YAML 与四个 Action 的固定提交和输入参数已核验。GitHub Ubuntu runner 尚未实际运行，Linux 和 Node 22 的最终结果以首次自动运行为准。
