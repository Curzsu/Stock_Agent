# 开发与排障说明

安装、启动和常用配置见 [项目 README](../README.md)。本页保留兼容层、重试和运行环境的细节。

## Gemini 兼容层

Google AI Studio 的 Gemini Key 可配合 Google 的 OpenAI 兼容接口使用：
`https://generativelanguage.googleapis.com/v1beta/openai/`，模型填写账号可用的 Gemini 模型 ID。

四个分析 Agent 使用共享兼容层，在非流式多轮工具调用中原样保留并回传
`extra_content.google.thought_signature`，避免工具执行后提交结果时因缺少签名被拒绝。
兼容层与离线回归基于 `langchain-openai>=1.1.11,<2.0`。

## 分析结果与重试

- 四路分析均无有效结果时停止汇总；部分维度缺失时只汇总成功取得的信息，并标明缺失项。修复前已生成的缺数据报告需重新分析。
- 报告加载失败会自动尝试最多三次，也可手动重新加载。MCP 数据连接失效后，后续分析或单项重试会重建会话。
- `SUMMARY_MAX_TOKENS` 默认为 12000，需符合模型及供应商的限制。遇到 `length` / `max_tokens` 截断时，自动重试一次并压缩正文；两次尝试共用 `REACT_TIMEOUT_SECONDS` 的默认 480 秒预算。
- 每次响应在校验前记录结束原因及供应商提供的 token 用量。仍失败时，可在综合研判卡片点击“重试汇总”，复用已完成的分析。
- 失败的历史卡片也可打开；该能力依赖当前服务进程保留的任务数据。

## PDF 排版

### 独立摘要与报告表达

新报告的摘要先给核心判断，再用六个要点说明支持与反对依据、短期与中长期差异及后续验证项。
无依据时不强行给出目标价或预期收益率。摘要目标为 650–850 个非空白字符，最多 1000 个字符、12 个非空行；
公司、代码、日期与缺失维度由应用补充。结构不完整或超长时，在原有最多两次生成尝试中重写，不截断风险与数据限制。
PDF 会测量摘要高度，无法清晰放入一页时明确报错，不裁切内容。旧报告不自动补写新结论，需重新生成综合报告。

报告展示统一已知财务字段名称，如将 `roeAvg` 显示为“加权平均净资产收益率”，保留 TTM、最近季末和现金流比率分母，
并清理重复标签；旧报告的 PDF 排版也使用该规则。各路分析与汇总减少列表和指标表重复、空泛开场及写作指令残留。
数值、代码、公式和来源链接保持原样，未识别字段不作推测替换。

### 工具与字体

模板固定使用 [Eisvogel 3.5.1](https://github.com/Wandmalfarbe/pandoc-latex-template/releases/tag/v3.5.1)，
随项目分发并保留 BSD-3-Clause 许可证。FINEX 主题独立于上游模板，插画从本地资源加载，生成报告不调用图像模型。
配色、字体样式与内容排版规则见 [PDF 模板说明](../agents/src/utils/pdf_templates/README.md)。

Windows 安装脚本从官方 GitHub 发布页下载 Pandoc 3.13 和 Tectonic 0.17.0，并校验 SHA-256，工具位于项目 `.tools/pdf`。
Tectonic 首次使用需联网下载 LaTeX 包，之后使用本地缓存；报告在本机排版。
使用 TeX Live / MiKTeX 时需具备 XeLaTeX、xeCJK、TikZ、KOMA-Script 等包，详见
[Eisvogel 所需宏包](https://github.com/Wandmalfarbe/pandoc-latex-template#required-latex-packages)。

可在 `agents/.env` 配置工具、中文字体与超时，修改后重启服务：

```dotenv
# 通常无需指定，自动发现项目便携工具和 PATH 中的程序
# PANDOC_PATH=C:/path/to/pandoc.exe
# PDF_LATEX_ENGINE=tectonic
# PDF_CJK_FONT=Noto Sans CJK SC
PDF_TIMEOUT_SECONDS=300
```

默认优先使用 XeLaTeX，找不到时使用 Tectonic。中文正文字体在 Windows 为 Microsoft YaHei，
其他平台为 FandolHei-Regular.otf；自定义字体必须已安装或在 LaTeX 字体库中可用。

重新排版旧 Markdown 不调用模型，旧 PDF 保持原样直到手动生成。
每次生成使用独立临时目录，仅在成功后替换成品。字体缺失、工具缺失或超时会记录失败状态，前端停止等待，不下载半成品。

## BaoStock 连接与黑名单保护

Web 行情/股票校验与 MCP 数据工具共用 `finex_data/baostock_runtime.py`。
同一状态目录下的进程通过操作系统文件锁串行访问，锁覆盖登录、查询、全部分页、登出和关闭连接。
查询结果完整读入内存后再释放连接，避免 Web 闲置连接与 MCP 登录重叠。
每次查询会建立并关闭会话，可能增加耗时；进程退出后系统自动释放锁。

收到 `10001011` 时立即停止重试，将本地暂停记录保存到状态目录的 `blacklist.json`。
暂停期间 Web/MCP 请求直接返回错误，不连接 BaoStock；重启服务也保留该记录。
磁盘写入失败时日志会提示，此时只有当前进程保留暂停保护，需恢复状态目录的可写性。

`BAOSTOCK_BLACKLIST_COOLDOWN_SECONDS` 默认 21600 秒（6 小时），可设置至少 60 秒的有限值。
该期限仅用于本地保护，不能解除官方黑名单，也不代表官方届时一定释放。
到期后的下一个请求才会尝试登录，仍被拒绝则再次暂停；实际释放时间见 [官方黑名单页面](https://www.baostock.com/blacklist)。

默认状态目录为项目根目录下的 `.runtime/baostock`。
同机运行多个项目副本时，需设置相同的绝对路径 `FINEX_BAOSTOCK_STATE_DIR`，并使用相同共享运行时。
项目内的锁无法协调其他机器或外部程序。请勿删除正在使用的 `access.lock`，以免破坏进程间互斥；修改环境变量后重启服务。

## CI 与本地运行时检查

常用检查命令见 [项目 README](../README.md)，CI 设计与测试范围见 [CI 设计](ci-design.md)。
脚本忽略本机 `.env`，按文件启动独立 Python 进程，避免 Agent 与 MCP 都使用 `src` 包名造成冲突。
失败、超时或未收集到测试都会返回失败状态；历史联网诊断脚本不纳入离线回归。

完成 README 中的 MCP 依赖同步后，检查实际运行环境的依赖版本：

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

自动检查结果直接查看 Actions 日志。若需阻止失败 PR 合并，在 GitHub 仓库规则中将 `checks` 设为必过检查。
