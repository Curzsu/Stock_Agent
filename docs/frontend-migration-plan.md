# FINEX React 前端重构实施计划

本计划落实 [React 前端架构](frontend-architecture.md)，在 `codex/react-frontend-architecture` 上按阶段推进。每阶段交付一个能独立验证的结果。本轮以本机试用为交付目标。PostgreSQL 由 Docker Compose 启动，FastAPI 继续在 Windows 宿主机通过项目虚拟环境运行，监听 `127.0.0.1`。React 工作台使用 `/react-preview/`，旧首页 `/` 用于对照。用本机账号验证同源会话、任务归属、PostgreSQL 持久化和私有报告下载。正式上线、公网接入和对外开放账号留待另行规划。

## 视觉验收

以旧版 `frontend/index.html` 和 `frontend/workbench.css` 渲染出的页面为基准，已有页面和状态尽量按 1:1 迁移。每阶段用相同数据和状态对照至少 1280px 桌面和 390px 手机视口，核对布局、留白、字体、背景、边框、圆角、阴影及控件状态。首页动效在默认和减少动态效果两种设置下对照。新增的登录等页面沿用同一套视觉样式。

阶段 3 对照首屏、搜索框、示例标签和研究进度。阶段 4 对照历史、报告目录、正文和下载状态。阶段 8 从本机预览入口做整页对照，记录可见差异。

## 进度与接续

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| 1 | React 工程、独立入口和详情刷新 | 已完成 |
| 2 | 视觉基础、研究阶段规则与行情 | 已完成 |
| 3 | 发起研究、URL 恢复、进度轮询与局部结果 | 已完成 |
| 4 | 失败重试、报告、PDF、历史与离线主流程 | 已完成 |
| 5 | 后端响应契约、Docker PostgreSQL、个人会话与任务归属 | 已完成 |
| 6 | PostgreSQL 任务与报告持久化、提交幂等和并发上限 | 已完成 |
| 7 | 本机运维、登录界面与跨标签页缓存隔离 | 待实现 |
| 8 | 本机完整试用、视觉对照与恢复验证 | 待实现 |

每完成一阶段，记录验收命令和结果、涉及范围、下一阶段的起点，并保留一个本地提交。新会话先运行 `git status --short --branch` 和 `git log -5 --oneline`，阅读本文和架构文档，再从第一项未完成的验收继续。中断在阶段中间时，先核对未提交 diff 和最近一次验证。初始基线为 `63a7200`，两组旧 Node 测试共 73 项通过。

## 阶段 1 · 独立入口

- [x] 在 `frontend/` 建立 npm 锁文件、React、严格 TypeScript、Vite、React Router 和 `npm run check`。React 源码放在 `frontend/src/`，旧静态文件按 `frontend/index.html` 的现有 URL 继续提供。
- [x] 建立 `/react-preview/` 和 `/react-preview/app/analysis/:id`。FastAPI 只服务登记的预览页面与构建资源。预览走现有回环校验，开发服务器仅监听 `127.0.0.1` 并代理 `/api`。构建产物位于 `frontend/dist`。
- [x] 先用 FastAPI 行为测试锁定入口、直达刷新、缺失资源、未构建、非本机访问和旧首页。验证 `npm ci --prefix frontend`、`npm run check --prefix frontend`、生产 HTML 与哈希资源的实际响应，并跑旧 Node 回归。

预览使用 Node.js 22.13 及以上的 22.x 版本，或 Node.js 24 及以上版本。在仓库根目录安装与构建后，按 [本地启动说明](../AGENTS.md) 启动 FastAPI，打开 `http://127.0.0.1:8100/react-preview/`。

```powershell
npm.cmd ci --prefix frontend
npm.cmd run check --prefix frontend
```

开发时执行 `npm.cmd run dev --prefix frontend`，根据 Vite 输出打开 `/react-preview/`。FastAPI 仍在 `127.0.0.1:8100` 提供 API。

## 阶段 2 · 工作台基础与行情

- [x] 以 `docs/workbench-ui-reference.md` 对齐旧界面。将色板与字体放进 `frontend/src/shared/styles/`，响应式布局随页面组件维护，跨页面控件放进 `shared/ui/`。用旧工作台规则核对阶段推导和维度顺序。
- [x] 在 `features/market/` 为 `/api/market-kline` 和 `/api/stock-market` 分别建立适配。个股按标的、周期和天数缓存，指数在日线缓存基础上生成周线和月线。延迟加载 Lightweight Charts 4.1.3，支持两类 K 线、成交量、滚动、缩放、切周期及空数据提示。
- [x] 在 Vitest 验证状态规则和转换场景，在离线 Chrome 夹具中验证图表交互及 `ok: false` 的实际提示。个股图通过任务的状态快照取得股票代码。持续轮询从阶段 3 接入。

从项目根目录运行离线浏览器回归。已安装 Chromium 时，可用 `FINEX_CHROMIUM_PATH` 指定其可执行文件。

```powershell
npm.cmd exec --prefix frontend -- playwright install chromium
npm.cmd run test:browser --prefix frontend
```

## 阶段 3 · 创建、进度与局部结果

- [x] 在 `shared/api/` 建立 `fetch`、AbortSignal 和错误解析，接入 TanStack Query。首页提交 `POST /api/analyze`，成功后用服务端 ID 跳转，失败时展示原因，创建请求关闭自动重试。
- [x] 将 `/api/status/{id}` 统一进 `useAnalysisProgress`。Worker 约每 2 秒查询，失败时回退到前台定时器。切回标签即时补查，同一 ID 合并在途读请求，切换任务使旧订阅失效。保留 30 分钟等待上限和每次运行的单次完成通知。
- [x] 用 `/api/analysis/{id}/partial` 加载新完成维度，刷新恢复时补取此前已完成的维度。用离线夹具覆盖提交、页面刷新、Worker 不可用、切换 ID 时旧响应迟到、终态仍有 Agent 运行及等待超时。
- [x] 恢复旧版搜索框、示例标签和研究耗时。沿用 Lenis 1.1.14 的滚轮缓动，恢复 2.5 秒开场及行情入场动效，支持减少动态效果。桌面和手机视口对照输入框与提交按钮的外观。

## 阶段 4 · 报告、重试与历史

- [x] 已完成及部分完成的任务可以打开报告。报告路由按需加载 react-markdown 和 remark-gfm，覆盖目录、财务表格、安全链接、原始 HTML 禁用和缺失维度提示。
- [x] 失败维度和综合研判支持重试。`202` 后刷新该任务状态，清理旧报告、PDF 和局部结果缓存。`409` 补查状态。`error` 时继续展示已有研究片段。
- [x] 报告页单独呈现 PDF 状态。以单字节请求探测文件，仅当响应为 `404` 且 `detail.status=pending` 时继续检查。下载时验证完整 PDF 响应。历史列表可打开已有报告或继续查看任务进度。
- [x] CI 增加离线 Chrome 主流程，覆盖发起研究到报告、部分成功、重试、PDF 准备中、下载和历史直达。桌面和手机视口对照旧版报告区与历史卡片的背景、边框、圆角和阴影。旧版页面的回归用例继续作为本机对照基线。

## 阶段 5 · 后端契约与数据归属

- [x] 为创建、状态、局部结果、重试、报告、历史和行情声明 FastAPI 响应模型，生成 `frontend/src/shared/api/` 下的 OpenAPI 类型。CI 重新生成并检测差异，兼容阶段 3、4 使用的公开字段。私有文件位置、模型凭据和底层异常诊断留在服务端。
- [x] 在仓库根目录提供 `compose.yaml`，启动 PostgreSQL 并用 `pg_isready` 检查就绪状态。固定带 `pgvector` 的 PostgreSQL 镜像标签，用 Docker 命名卷保存数据库。端口仅绑定宿主机 `127.0.0.1`，默认 `5432`，冲突时可调整。FastAPI 通过环境变量 `DATABASE_URL` 连接，实际凭据由本机环境提供。记录 Compose 启动、连接和迁移命令。
- [x] 建立 `POST/GET/DELETE /api/session`、本机试用账号 CLI 和同源会话。用 PostgreSQL 的 `users` 和 `sessions` 表保存账号及会话，添加版本化迁移。会话 Cookie 使用 `HttpOnly` 和 `SameSite=Lax`，`Secure` 的本机 HTTP 例外只允许用于回环入口。登录校验来源，登录后的写接口同时校验来源和 CSRF 令牌。所有任务与 PDF 路径共用会话和所有者校验。私有响应使用 `Cache-Control: no-store`。
- [x] 用双账号行为测试覆盖创建、历史先按用户过滤再取最近记录、状态、局部结果、报告、重试、PDF 与匿名拒绝。匿名用 `401`，他人任务及不存在任务用 `404`。阶段 5 先交付后端能力，阶段 7 接通浏览器登录，阶段 8 在本机验收完整流程。

## 阶段 6 · 持久化与任务恢复

- [x] 扩展 PostgreSQL 表结构，持久化任务所有者、状态快照、初始输入、分维度结果、PDF 状态及私有文件位置。用与本机镜像同版本的临时 PostgreSQL 数据库验证迁移、运行更新、事务失败和重启恢复，测试数据与试用数据隔离。已完成任务重启后仍可读，未结束任务标为中断并保留已有片段。
- [x] 给每份报告分配稳定的文档 ID，登记所属任务、所有者、股票代码、报告日期、Markdown 文件位置和内容版本。Markdown 和 PDF 按任务写入宿主机的私有报告目录，文档元数据用于后续检索和引用。删除先提交数据库标记，待清理文件可在本机重启时续清理。
- [x] 给任务保存启动时的模型配置版本引用，在宿主机保管独立加密密钥。终态可重试的任务重启后使用原配置。验证已撤销版本会提示重新提交。没有可靠归属的旧报告留在本机归档。
- [x] 以用户 ID 和 `Idempotency-Key` 作为 PostgreSQL 唯一约束，在同一事务内决定建任务或返回原 ID。只调度首次创建。前端明确重试沿用同一提交标识，新提交生成新标识。创建和重试默认共用每账号 1 个、全局 3 个任务的并发上限。用 PostgreSQL 和受控调度测试并发请求、响应丢失、重复请求、配额释放及重启时的未结束任务。

## 阶段 7 · 本机运维与浏览器会话

- [ ] 让 `/ops` 承接 A–E 模型配置、试用账号开设与停用、全局任务和本机删除。页面、运维接口和兼容保留的旧删除接口共用本机访问校验。保留现有配置切换和删除回归。
- [ ] 在 `features/session/` 接通登录、退出、当前用户与安全站内回跳。私有 Query 键从用户 ID 开始，详情再加任务 ID。退出、过期或换号时经 BroadcastChannel 取消请求、关闭 Worker、清除旧缓存和页面内容，恢复可见时复核会话。
- [ ] 浏览器测试覆盖私人直链登录回跳、外站地址拒绝、双标签页换号和在途报告响应迟到。后端测试验证运维请求只接受本机访问。

## 阶段 8 · 本机完整试用

- [ ] 用 Docker Compose 启动 PostgreSQL，确认数据库就绪后执行迁移，再在宿主机启动 FastAPI。从 `http://127.0.0.1:8100/react-preview/` 加载构建好的 `frontend/dist`。验证登录、历史、详情和报告直达及刷新，缺失资源和 `/api/*` 保留自身 HTTP 状态。用旧首页对照桌面和手机视口的布局、边框、卡片与滚动手感。
- [ ] 用两个本机账号验证从发起研究到报告、PDF 下载及历史回看。用 Pandoc 3 与 XeLaTeX 或 Tectonic 生成实际样例，确认账号 A 可打开自己的报告并下载可读的中文 PDF，账号 B 请求同一报告及下载接口时收到 `404`。校验旧入口使用的任务接口也执行相同的所有者校验。
- [ ] 重启 FastAPI，确认历史与已完成报告仍可访问，未完成任务显示中断并保留已有结果。保留命名卷并重建 PostgreSQL 容器，验证试用数据仍可读取。在独立的本机数据库和报告目录验证一次备份恢复，记录启动、迁移和恢复步骤。

## 后续功能 · 研报向量检索

在研报检索功能阶段启用 `pgvector`，按文档 ID 和内容版本对 Markdown 章节切片并生成向量。查询按用户授权过滤，并支持股票代码、报告日期和原文章节引用。用双账号验证检索结果与引用隔离，用报告更新和删除验证索引同步。根据带过滤条件的实测延迟和召回率选索引。[架构中的研报向量检索](frontend-architecture.md#研报向量检索)

## 完成记录

- 2026-11-22 · 阶段 6。后端回归通过 27 个测试文件，含 8 项任务持久化专项测试。用本机 Docker PostgreSQL 验证迁移、重启、重复提交、并发上限、原配置重试、稳定文档 ID、PDF 状态及失败后的事务与文件一致性。宿主机 FastAPI 的实际 HTTP 验证确认从第 5 阶段迁移后可登录，重启后可读历史并重放提交。前端类型检查、构建、15 项 Vitest、17 项离线 Chrome 和旧版 73 项 Node 回归通过。阶段 7 从 `/api/session` 和本机账号管理接通浏览器登录与运维入口。
- 2026-11-22 · 阶段 5。后端回归通过 26 个测试文件，含 Docker PostgreSQL 的 7 项账号与契约测试。宿主机 FastAPI 重启后仍可读取有效会话，退出后会话立即失效。前端检查通过，含 15 项 Vitest、15 项离线 Chrome 和旧版 73 项 Node 回归。`python -m scripts.export_openapi .runtime/openapi.json` 与 `npm run api:generate --prefix frontend` 可重复生成相同类型。阶段 6 从 `backend/migrations/0001_accounts.sql` 和 `backend/server.py` 中带所有者的内存任务记录接续。
- 2026-11-21 · 阶段 4。生产构建、15 项前端单测、15 项离线 Chrome、73 项旧版 Node 回归和 31 项 FastAPI 测试通过。阶段 5 从后端响应模型、账号与会话及任务所有者校验开始。
- 2026-11-21 · 阶段 3。前端检查和生产构建通过，13 项 Vitest、10 项离线 Chrome 和旧版 73 项 Node 回归通过。阶段 4 可在 `frontend/src/features/analysis/useAnalysisProgress.ts` 接入报告跳转与重试后订阅，在 `frontend/src/features/analysis/partialQuery.ts` 按任务失效局部结果缓存。
- 2026-11-21 · 阶段 2 视觉复核。已按旧版恢复首页行情区和图表卡、研究卡片及个股行情区的背景、边框、圆角、阴影。Chrome 在 1280px 和 390px 的同状态对照通过，后续页面按本文的视觉验收要求继续迁移。
- 2026-11-21 · 阶段 2。锁文件安装和 `npm run check --prefix frontend` 通过，覆盖 9 项 Vitest 测试。旧 Node 回归 73 项通过。离线 Chrome 3 项通过，覆盖指数图表交互、工作台状态与个股周期缓存，以及指数和个股的上游错误提示。用本机 FastAPI 验证构建后的字体和独立图表脚本均可加载。阶段 3 从 `frontend/src/features/analysis/statusQuery.ts` 和 `frontend/src/shared/api/getJson.ts` 开始，接入提交、进度订阅和局部结果。
- 2026-11-21 · 阶段 1。`npm ci --prefix frontend` 和 `npm run check --prefix frontend` 通过，包含 2 项 Vitest 路由测试。旧 Node 回归 73 项通过。`python scripts/run_ci_tests.py app` 通过 25 个测试文件，覆盖新增的 5 项 FastAPI 预览测试。用本机 Uvicorn 和 Chrome 验证生产预览、详情直达、旧首页及缺失资源的 `404`，并验证 Vite 开发预览和 `/api` 代理。工作台目前显示 URL 中的任务编号。阶段 2 从 `frontend/workbench.js`、`frontend/workbench.css` 和 `docs/workbench-ui-reference.md` 开始，按既有行为迁移视觉、阶段推导与行情。
- 2026-11-21 · 确认目标分支与旧前端基线。Windows 若将 `node` 解析成系统目录下不可执行的条目，使用 `node.exe` 或其绝对路径。后端测试使用仓库的 `unittest` 流程。
