# 实现计划:首页"配置 API Key"按钮 + 弹窗

## 总体方案

在首页右上角 header 加一个齿轮图标按钮(复用 `.github-link` 样式),点击弹出 Glassmorphism 风格配置弹窗。弹窗含 3 个字段(API Key / Base URL / Model),打开时从后端 GET 当前值(API key 脱敏),保存时 POST 到后端,后端同时更新 `os.environ`(立即生效)和写入 `agents/.env`(持久化)。用 TDD:先写后端 TestClient 测试,再实现,最后做前端。

## 后端改动 (backend/server.py)

### 1. 新增 Pydantic 模型 `ApiConfigRequest`
紧跟 `AnalysisStatus` 之后(server.py:133 后):
```python
class ApiConfigRequest(BaseModel):
    """Request model for API config endpoint"""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
```
字段都 Optional —— 用户可能只改其中一个,未传的字段保留原值。

### 2. 新增配置读写工具函数
在 server.py 模块级(env_path 已在 L36 定义,直接复用):
- `mask_api_key(key: str) -> str`:脱敏。`sk-xxxx1234` -> `sk-***1234`(保留前3后4,短于7位全掩码)
- `update_env_file(env_path, updates: dict)`:读现有 .env 行,替换匹配的 key,缺则追加,写回。保留注释和空行。只处理 OPENAI_COMPATIBLE_API_KEY / OPENAI_COMPATIBLE_BASE_URL / OPENAI_COMPATIBLE_MODEL 三个 key。

### 3. 新增两个端点(放在 `/api/health` 之前)

**GET `/api/config`** —— 返回当前配置(API key 脱敏):
```python
return {
    "api_key": mask_api_key(os.getenv("OPENAI_COMPATIBLE_API_KEY", "")),
    "base_url": os.getenv("OPENAI_COMPATIBLE_BASE_URL", ""),
    "model": os.getenv("OPENAI_COMPATIBLE_MODEL", ""),
}
```

**POST `/api/config`** —— 接收 `ApiConfigRequest`,更新 os.environ + 写 .env:
- 只处理非 None 的字段(用户没改的保留)
- `os.environ[key] = value`(立即生效,agents 下次 os.getenv 就能读到)
- `update_env_file(env_path, {key: value})`(持久化)
- 返回 `{"status": "ok", "message": "配置已更新"}` 和更新后的脱敏配置

## 前端改动 (frontend/index.html)

### 4. CSS(在 `<style>` 内,`.github-link` 规则附近新增)
- `.config-btn`:复用 `.github-link` 的 36px 圆形玻璃样式(直接复制选择器规则或共享 class)
- `.config-modal-overlay`:全屏遮罩,`position:fixed; inset:0; z-index:10000; background:rgba(10,10,10,0.4); backdrop-filter:blur(4px)`,用 `.hidden` class 控制显隐(复用现有 `.intro-overlay` 的 hidden 模式)
- `.config-modal`:居中玻璃面板,`rgba(255,255,255,0.7) + blur(20px) + border-radius:var(--radius-xl)`,宽度 ~440px
- `.config-field`:标签 + 输入框,输入框样式参照 `.search-input`(透明背景无边框)外包 `.search-wrapper` 玻璃容器 + 金色 focus 环
- `.config-save-btn` / `.config-cancel-btn`:参照 `.report-btn-primary` / `.report-btn-secondary`

### 5. HTML
- 在 `.header-right`(L1547)内,`.github-link` 之后加一个 `<button class="config-btn" id="configBtn">` + 齿轮 SVG 图标
- 在 `</body>` 前加配置弹窗结构:overlay > modal > 标题 + 3 个字段 + 保存/取消按钮

### 6. JS(在 `<script>` 内)
- `configBtn.addEventListener('click', openConfigModal)`:发 `GET /api/config`,填入表单,移除 `.hidden` 显示弹窗
- 保存按钮:`POST /api/config` 发送表单值,成功后显示提示并关闭弹窗
- 取消按钮 / 点遮罩:加 `.hidden` 隐藏
- 复用现有 fetch 模式(`${API_BASE}/config`),沿用 try/catch + console.error

## TDD 执行顺序

### RED 1:后端 GET /api/config
`tests/test_api_config.py`(新建):
- `test_get_config_returns_masked_values`:设 os.environ 为已知值,GET /api/config,断言返回 3 个字段且 api_key 被脱敏(含 ***)
- `test_get_config_when_unset`:清空 os.environ,GET,断言 base_url/model 为空串、api_key 为空串(不报错)

### GREEN 1:实现 GET 端点 + mask_api_key,跑通

### RED 2:后端 POST /api/config
- `test_post_config_updates_os_environ`:POST 新值,断言 os.environ 被更新
- `test_post_config_persists_to_env_file`:POST 后读 .env 文件,断言新值写入(用临时 .env 路径,不污染真实 .env)
- `test_post_config_partial_update`:只传 base_url,断言 api_key/model 不变
- `test_post_config_masks_in_response`:POST 后返回的 api_key 是脱敏的

### GREEN 2:实现 POST 端点 + update_env_file,跑通
测试用临时目录的 .env,不碰真实 agents/.env。用 FastAPI TestClient。

### 前端:手动验证(无框架,无法自动化)
启动服务器,浏览器打开,点齿轮 -> 弹窗显示当前值 -> 改值保存 -> 重新打开确认值已更新 -> 跑一次分析确认新 key 生效。

### REFACTOR:提取重复样式,确认全绿

## 安全考量
- GET 返回脱敏 key,不泄露完整密钥到前端
- CORS 是 `allow_origins=["*"]` + `allow_credentials=False`,POST /api/config 是普通请求,无需额外 CORS 配置
- 写 .env 是本地开发场景(单用户),不做并发锁(.env 写入是毫秒级,且配置修改是低频操作)
- 测试用临时 .env 路径,绝不污染真实 agents/.env

## 文件清单
- 改:backend/server.py(加 2 端点 + 2 工具函数 + 1 模型)
- 改:frontend/index.html(加按钮 + 弹窗 + CSS + JS)
- 新建:tests/test_api_config.py(后端测试,预计 6 个测试)