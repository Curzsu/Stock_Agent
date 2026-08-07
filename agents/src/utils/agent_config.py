"""
分析 Agent 共享配置常量。

这些值原本硬编码在 4 个 agent 各自的实现里（recursion_limit=25、
timeout=480s、temperature=0.3、max_tokens=6000），重复 4 份且难以统一
调整。集中到此模块，便于：
- 统一调参（如 recursion_limit 从 25 提到 50，避免 ReAct 被截断）
- 后续抽 agent 基类时作为配置来源
- 运行时通过环境变量覆盖（可选扩展）
"""
import os

# ReAct agent 的递归上限（工具调用轮数）。
# 旧值 25 在基本面分析（需查 8 类数据）时不够，日志多次出现
# "Recursion limit of 25 reached without hitting a stop condition"，
# 导致分析被截断却标记成功（静默失败）。提到 50 给足余量。
REACT_RECURSION_LIMIT = int(os.getenv("REACT_RECURSION_LIMIT", "50"))

# ReAct agent 单次执行总超时（秒），防止 LLM API 挂起永久等待。
REACT_TIMEOUT_SECONDS = float(os.getenv("REACT_TIMEOUT_SECONDS", "480"))

# LLM 生成参数
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "6000"))
