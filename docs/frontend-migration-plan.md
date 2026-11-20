# FINEX React 前端重构实施计划

本计划落实 [React 前端架构](frontend-architecture.md)，在 `codex/react-frontend-architecture` 上按阶段推进。每阶段交付一个能独立验证的结果。正式上线前，FastAPI 继续用 `/` 提供旧首页，React 在本机 `/react-preview/` 下逐段接通。客户版使用同源会话、SQLite 和私有报告目录。

## 视觉验收

以旧版 `frontend/index.html` 和 `frontend/workbench.css` 渲染出的页面为基准，已有页面和状态尽量按 1:1 迁移。每阶段用相同数据和状态对照至少 1280px 桌面和 390px 手机视口，核对布局、留白、字体、背景、边框、圆角、阴影及控件状态。首页动效在默认和减少动态效果两种设置下对照。新增的登录等页面沿用同一套视觉样式。

阶段 3 对照首屏、搜索框、示例标签和研究进度。阶段 4 对照历史、报告目录、正文和下载状态。阶段 8 在切换正式入口前做整页对照，记录因产品要求产生的可见差异。

## 进度与接续

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| 1 | React 工程、独立入口和详情刷新 | 已完成 |
| 2 | 视觉基础、研究阶段规则与行情 | 已完成 |
| 3 | 发起研究、URL 恢复、进度轮询与局部结果 | 已完成 |
| 4 | 失败重试、报告、PDF、历史与离线主流程 | 待实现 |
| 5 | 后端响应契约、个人会话与任务归属 | 待实现 |
| 6 | SQLite 持久化、提交幂等和并发上限 | 待实现 |
| 7 | 本机运维、登录界面与跨标签页缓存隔离 | 待实现 |
| 8 | 入口切换、回退验证和目标主机冒烟 | 待实现 |

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

- [ ] 在 `features/reports/` 读取 `completed` 和 `degraded` 的 `/api/result/{id}`。接入按报告路由加载的 react-markdown 和 remark-gfm，验证目录、财务表格、安全链接、原始 HTML 禁用和缺失维度提示。
- [ ] 在 `features/analysis/` 增加失败维度和综合研判重试。`202` 后刷新该任务状态并使旧报告及 PDF 缓存失效，`409` 补查状态。`error` 时继续展示已有研究片段。
- [ ] 在报告页单独呈现 PDF 状态。`404` 且 `detail.status=pending` 时继续检查，失败、不可用和无权访问时停止。验证下载链接与实际文件响应。接通 `features/history/`，支持从历史打开原任务。
- [ ] CI 增加离线浏览器主流程，从发起研究走到报告。另测部分成功、失败重试、PDF 准备中和历史直达。逐项替换已被行为覆盖的旧 HTML 源码匹配用例。

## 阶段 5 · 后端契约与数据归属

- [ ] 为创建、状态、局部结果、重试、报告、历史和行情声明 FastAPI 响应模型，生成 `frontend/src/shared/api/` 下的 OpenAPI 类型。CI 重新生成并检测差异，兼容阶段 3、4 使用的公开字段。私有文件位置和模型凭据留在服务端。
- [ ] 建立 `POST/GET/DELETE /api/session`、预开账号和同源会话，采用成熟认证组件。生产 HTTPS 使用 `HttpOnly`、`Secure`、`SameSite=Lax` Cookie，写接口校验来源和 CSRF 令牌。为所有任务与 PDF 路径集中挂接会话和所有者校验。私有响应使用 `Cache-Control: no-store`。
- [ ] 用双账号行为测试覆盖创建、历史先按用户过滤再取最近记录、状态、局部结果、报告、重试、PDF 与匿名拒绝。匿名用 `401`，他人任务及不存在任务用 `404`。该阶段先落后端能力，由阶段 7 接通登录与本机回退，客户开放由阶段 8 验收。

## 阶段 6 · 持久化与任务恢复

- [ ] 用 SQLite 保存用户、会话、任务所有者、状态快照、初始输入、分维度结果、PDF 状态及私有文件位置。用测试临时数据库验证运行更新、事务失败和重启恢复。已完成任务重启后仍可读，未结束任务标为中断并保留已有片段。
- [ ] 给任务保存启动时的模型配置版本引用，凭据由后端版本化配置保护。终态可重试的任务重启后使用原配置。验证已撤销版本会提示重新提交。没有可靠归属的旧报告列入本机归档。
- [ ] 以用户 ID 和 `Idempotency-Key` 作为数据库唯一约束，在同一事务内决定建任务或返回原 ID。只调度首次创建。前端明确重试沿用同一提交标识，新提交生成新标识。对创建、重试应用每用户和全局并发上限。用受控调度测试并发请求、响应丢失、重复请求、配额释放及重启时的未结束任务。

## 阶段 7 · 本机运维与浏览器会话

- [ ] 让 `/ops` 承接 A–E 模型配置、账号开设与停用、全局任务和本机删除。页面和接口共用本机访问校验。保留现有配置切换和删除回归，在反向代理配置中屏蔽公网运维路径和旧删除方法。
- [ ] 在 `features/session/` 接通登录、退出、当前用户与安全站内回跳。私有 Query 键从用户 ID 开始，详情再加任务 ID。退出、过期或换号时经 BroadcastChannel 取消请求、关闭 Worker、清除旧缓存和页面内容，恢复可见时复核会话。
- [ ] 浏览器测试覆盖私人直链登录回跳、外站地址拒绝、双标签页换号和在途报告响应迟到。后端测试覆盖本机与公网入口的运维权限。

## 阶段 8 · 发布与回退

- [ ] FastAPI 为 `/`、`/login`、`/app/history`、`/app/analysis/:id` 和 `/app/analysis/:id/report` 提供 React 入口。带内容哈希资源长期缓存，HTML 每次重新验证。缺失资源和 `/api/*` 保留自身 HTTP 状态。CI 打包 `dist`，发布后启动 Python 应用即可。
- [ ] 验证旧前端回退继续通过相同的任务所有者校验。开通客户前在目标主机实测 A 可读自己的报告和中文 PDF，B 打开同一报告及下载链接得到 `404`，公网 `/ops` 不可用。使用 Pandoc 3 与 XeLaTeX 或 Tectonic 生成实际样例。记录切换和回退步骤、SQLite 与报告目录备份位置。

## 完成记录

- 2026-11-21 · 阶段 3。前端检查和生产构建通过，13 项 Vitest、10 项离线 Chrome 和旧版 73 项 Node 回归通过。阶段 4 可在 `frontend/src/features/analysis/useAnalysisProgress.ts` 接入报告跳转与重试后订阅，在 `frontend/src/features/analysis/partialQuery.ts` 按任务失效局部结果缓存。
- 2026-11-21 · 阶段 2 视觉复核。已按旧版恢复首页行情区和图表卡、研究卡片及个股行情区的背景、边框、圆角、阴影。Chrome 在 1280px 和 390px 的同状态对照通过，后续页面按本文的视觉验收要求继续迁移。
- 2026-11-21 · 阶段 2。锁文件安装和 `npm run check --prefix frontend` 通过，覆盖 9 项 Vitest 测试。旧 Node 回归 73 项通过。离线 Chrome 3 项通过，覆盖指数图表交互、工作台状态与个股周期缓存，以及指数和个股的上游错误提示。用本机 FastAPI 验证构建后的字体和独立图表脚本均可加载。阶段 3 从 `frontend/src/features/analysis/statusQuery.ts` 和 `frontend/src/shared/api/getJson.ts` 开始，接入提交、进度订阅和局部结果。
- 2026-11-21 · 阶段 1。`npm ci --prefix frontend` 和 `npm run check --prefix frontend` 通过，包含 2 项 Vitest 路由测试。旧 Node 回归 73 项通过。`python scripts/run_ci_tests.py app` 通过 25 个测试文件，覆盖新增的 5 项 FastAPI 预览测试。用本机 Uvicorn 和 Chrome 验证生产预览、详情直达、旧首页及缺失资源的 `404`，并验证 Vite 开发预览和 `/api` 代理。工作台目前显示 URL 中的任务编号。阶段 2 从 `frontend/workbench.js`、`frontend/workbench.css` 和 `docs/workbench-ui-reference.md` 开始，按既有行为迁移视觉、阶段推导与行情。
- 2026-11-21 · 确认目标分支与旧前端基线。Windows 若将 `node` 解析成系统目录下不可执行的条目，使用 `node.exe` 或其绝对路径。后端测试使用仓库的 `unittest` 流程。
