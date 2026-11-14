# FINEX 本地启动与排障

## Windows 启动流程

1. 在项目根目录确认 `venv\Scripts\python.exe`、项目依赖和 `agents\.env` 已就绪。模型配置按 README 设置，排障时避免输出密钥。FastAPI 同时提供前端页面，无需另起前端服务。
2. 在 Windows 宿主机检查 `8100` 端口和 `/api/health`。如果已有 FINEX 在监听且首页可访问，直接复用。若是其他进程占用端口，先确认其归属。
3. 在项目根目录用现有虚拟环境启动。把虚拟环境的 `Scripts` 加到当前进程的 `PATH`，让后端启动 MCP 时也能找到其中的 `uv`。

   ```powershell
   $env:Path = (Join-Path (Get-Location).Path 'venv\Scripts') + ';' + $env:Path
   .\venv\Scripts\python.exe -m uvicorn backend.server:app --host 127.0.0.1 --port 8100
   ```

4. 后台启动时，将本次的 stdout 和 stderr 分别保存到 `.runtime`，便于跟踪。启动后从宿主机确认首页返回 HTTP 200、健康接口返回 `healthy`。如果需要确认本次新进程启动成功，还要查看本次日志中的 `Uvicorn running on`，并核对端口监听 PID 与 Uvicorn 日志中的服务 PID。

   ```powershell
   Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue
   curl.exe -sS --fail --noproxy '*' --max-time 5 http://127.0.0.1:8100/api/health
   curl.exe -sS --fail --noproxy '*' --max-time 5 -o NUL -w '%{http_code}\n' http://127.0.0.1:8100/
   ```

## 启动时遇到的坑

- **依赖导入会延迟首条日志。** 后端导入 LangChain 时会加载 Transformers 和 PyTorch。这次单独导入后端超过了 15 秒，最终完成。若日志仍为空，可用 `faulthandler` 查看 Python 调用栈，确认进程是在导入依赖还是卡在其他地方。
- **沙箱内的回环访问有局限。** 这次沙箱内的 Uvicorn 卡在 Windows `asyncio` 创建内部回环套接字的 `accept()`，同一沙箱内的 `curl` 也无法连接宿主机上已经运行的 FINEX。遇到同样的调用栈或连接失败时，先在宿主机上核查监听端口与健康接口；宿主机无服务时再从宿主机启动。
- **健康检查可能命中旧进程。** 这次新进程报 `WinError 10048`，同时首页和健康接口都正常，因为已有 FINEX 占用 `8100`。判断新进程是否启动成功时，以本次启动日志和实际监听 PID 为准。
