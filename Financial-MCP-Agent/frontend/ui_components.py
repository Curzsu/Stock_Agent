"""
UI Components and Helpers for Chainlit Frontend
"""
import re
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field
import time

import chainlit as cl
from chainlit.element import Element

from agent_orchestrator import AgentProgress, AgentType


@dataclass
class AgentDisplayConfig:
    name: str
    icon: str
    color: str
    description: str


@dataclass
class AgentTimer:
    start_time: float = 0.0
    elapsed: float = 0.0
    is_running: bool = False
    final_time: Optional[float] = None

    def start(self):
        self.start_time = time.time()
        self.is_running = True
        self.final_time = None

    def stop(self):
        if self.is_running:
            self.elapsed = time.time() - self.start_time
            self.final_time = self.elapsed
            self.is_running = False

    def get_elapsed(self) -> float:
        if self.is_running:
            return time.time() - self.start_time
        return self.final_time if self.final_time is not None else self.elapsed


AGENT_CONFIGS: Dict[AgentType, AgentDisplayConfig] = {
    AgentType.FUNDAMENTAL: AgentDisplayConfig(
        name="基本面分析师",
        icon="📊",
        color="#4CAF50",
        description="财务报表、盈利能力、成长性分析"
    ),
    AgentType.TECHNICAL: AgentDisplayConfig(
        name="技术面分析师",
        icon="📈",
        color="#2196F3",
        description="K线形态、技术指标、趋势研判"
    ),
    AgentType.VALUE: AgentDisplayConfig(
        name="估值分析师",
        icon="💰",
        color="#FF9800",
        description="市盈率、市净率、内在价值评估"
    ),
    AgentType.NEWS: AgentDisplayConfig(
        name="新闻分析师",
        icon="📰",
        color="#9C27B0",
        description="新闻爬取、情感分析、风险评估"
    ),
    AgentType.SUMMARY: AgentDisplayConfig(
        name="综合研判师",
        icon="🎯",
        color="#F44336",
        description="多维度整合、研报生成"
    ),
}


def format_time(seconds: float) -> str:
    """格式化时间为 MM:SS 格式"""
    if seconds is None:
        return "00:00"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


class ProgressTracker:
    def __init__(self):
        self._steps: Dict[str, cl.Step] = {}
        self._agent_steps: Dict[str, cl.Step] = {}
        self._root_step: Optional[cl.Step] = None

    async def create_root_step(self, query: str) -> cl.Step:
        self._root_step = cl.Step(
            name="分析任务",
            type="run",
            show_input=False,
        )
        self._root_step.input = query
        await self._root_step.send()
        return self._root_step

    async def create_agent_step(self, agent_type: AgentType) -> cl.Step:
        config = AGENT_CONFIGS.get(agent_type)
        if not config:
            return None
        
        step = cl.Step(
            name=config.name,
            type="tool",
            show_input=False,
            parent_id=self._root_step.id if self._root_step else None,
        )
        step.input = config.description
        
        self._agent_steps[agent_type.value] = step
        await step.send()
        return step

    async def update_agent_step(
        self, 
        agent_type: AgentType, 
        message: str, 
        status: str = "running"
    ) -> None:
        step = self._agent_steps.get(agent_type.value)
        if step:
            step.output = message
            if status == "completed":
                step.is_error = False
            elif status == "error":
                step.is_error = True
            await step.update()

    async def add_tool_call(
        self, 
        agent_type: AgentType, 
        tool_name: str, 
        tool_input: str,
        tool_output: str = None
    ) -> None:
        agent_step = self._agent_steps.get(agent_type.value)
        if not agent_step:
            return
        
        tool_step = cl.Step(
            name=tool_name,
            type="tool",
            show_input=True,
            parent_id=agent_step.id,
        )
        tool_step.input = tool_input
        if tool_output:
            tool_step.output = tool_output
        await tool_step.send()

    async def complete_root_step(self, success: bool = True) -> None:
        if self._root_step:
            self._root_step.output = "分析完成" if success else "分析失败"
            self._root_step.is_error = not success
            await self._root_step.update()

    def get_agent_step(self, agent_type: AgentType) -> Optional[cl.Step]:
        return self._agent_steps.get(agent_type.value)


class MarkdownRenderer:
    @staticmethod
    def render_table(data: List[Dict[str, Any]], headers: List[str]) -> str:
        if not data:
            return ""
        
        header_row = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"
        
        rows = []
        for item in data:
            row_values = [str(item.get(h, "")) for h in headers]
            rows.append("| " + " | ".join(row_values) + " |")
        
        return "\n".join([header_row, separator] + rows)

    @staticmethod
    def render_report_section(title: str, content: str, level: int = 2) -> str:
        prefix = "#" * level
        return f"\n{prefix} {title}\n\n{content}\n"

    @staticmethod
    def highlight_key_metrics(text: str) -> str:
        metric_patterns = [
            (r'(\d+\.?\d*%)', r'**\1**'),
            (r'(市盈率[：:]\s*\d+\.?\d*)', r'**\1**'),
            (r'(市净率[：:]\s*\d+\.?\d*)', r'**\1**'),
            (r'(ROE[：:]\s*\d+\.?\d*%?)', r'**\1**'),
        ]
        
        result = text
        for pattern, replacement in metric_patterns:
            result = re.sub(pattern, replacement, result)
        
        return result

    @staticmethod
    def format_final_report(report: str, company_name: str = None, stock_code: str = None) -> str:
        if not report:
            return "无法生成报告"
        
        lines = report.split('\n')
        formatted_lines = []
        
        for line in lines:
            if line.strip().startswith('#'):
                formatted_lines.append(f"\n{line}")
            elif '风险提示' in line or '注意' in line or '警告' in line:
                formatted_lines.append(f"> ⚠️ {line}")
            elif '建议' in line or '推荐' in line:
                formatted_lines.append(f"✅ {line}")
            else:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)


class ChatHistoryManager:
    def __init__(self):
        self._history: List[Dict[str, Any]] = []

    def add_message(self, role: str, content: str, metadata: Dict[str, Any] = None) -> None:
        self._history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        })

    def get_history(self, limit: int = None) -> List[Dict[str, Any]]:
        if limit:
            return self._history[-limit:]
        return self._history.copy()

    def clear_history(self) -> None:
        self._history.clear()

    def get_context_for_query(self) -> str:
        context_parts = []
        for msg in self._history[-5:]:
            role = "用户" if msg["role"] == "user" else "助手"
            context_parts.append(f"{role}: {msg['content'][:200]}")
        
        return "\n".join(context_parts) if context_parts else ""


class ErrorMessageBuilder:
    ERROR_MESSAGES = {
        "mcp_connection": {
            "title": "MCP服务连接失败",
            "detail": "无法连接到数据源服务，请检查MCP服务器是否正常运行。",
            "suggestion": "建议检查：\n1. MCP服务器进程是否启动\n2. 网络连接是否正常\n3. 配置文件中的服务地址是否正确"
        },
        "data_fetch": {
            "title": "数据获取失败",
            "detail": "从数据源获取股票数据时发生错误。",
            "suggestion": "可能原因：\n1. 股票代码不存在\n2. 数据源暂时不可用\n3. 请求频率过高"
        },
        "llm_error": {
            "title": "AI模型调用失败",
            "detail": "在调用语言模型进行分析时发生错误。",
            "suggestion": "建议检查：\n1. API密钥是否有效\n2. API配额是否充足\n3. 模型服务是否正常"
        },
        "timeout": {
            "title": "分析超时",
            "detail": "分析任务执行时间过长，已自动终止。",
            "suggestion": "建议：\n1. 简化查询内容\n2. 稍后重试\n3. 检查网络连接"
        },
        "unknown": {
            "title": "未知错误",
            "detail": "发生了一个预期之外的错误。",
            "suggestion": "请联系技术支持并提供错误详情。"
        }
    }

    @classmethod
    def build(cls, error_type: str, original_error: str = None) -> cl.ErrorMessage:
        error_info = cls.ERROR_MESSAGES.get(error_type, cls.ERROR_MESSAGES["unknown"])
        
        content = f"### ❌ {error_info['title']}\n\n{error_info['detail']}"
        
        if original_error:
            content += f"\n\n**错误详情：**\n```\n{original_error}\n```"
        
        content += f"\n\n{error_info['suggestion']}"
        
        return cl.ErrorMessage(
            content=content,
            author="系统"
        )

    @classmethod
    def classify_error(cls, error_message: str) -> str:
        error_lower = error_message.lower()
        
        if any(kw in error_lower for kw in ["mcp", "server", "connection", "connect"]):
            return "mcp_connection"
        elif any(kw in error_lower for kw in ["timeout", "timed out", "超时"]):
            return "timeout"
        elif any(kw in error_lower for kw in ["api", "llm", "model", "openai"]):
            return "llm_error"
        elif any(kw in error_lower for kw in ["data", "fetch", "get", "stock"]):
            return "data_fetch"
        else:
            return "unknown"


class WelcomeMessageBuilder:
    @staticmethod
    async def send() -> None:
        welcome_content = """
## 🏦 A股金融智能体分析系统

欢迎使用多智能体协同的A股深度分析平台。系统将为您执行全方位的金融分析：

| 分析维度 | 说明 |
|---------|------|
| 📊 基本面分析 | 财务报表、盈利能力、成长性、偿债能力 |
| 📈 技术面分析 | K线形态、技术指标、支撑阻力位、趋势研判 |
| 💰 估值分析 | 市盈率、市净率、内在价值、行业对比 |
| 📰 新闻分析 | 实时新闻、情感评分、风险评估 |

### 📝 查询示例

- `分析贵州茅台`
- `600519这只股票怎么样`
- `帮我分析一下比亚迪的投资价值`
- `宁德时代的财务状况如何`

### ⏱️ 分析时长

完整分析约需 **2-5分钟**，过程中将实时展示各智能体的执行状态和计时。
"""
        await cl.Message(
            content=welcome_content,
            author="系统"
        ).send()


class AnalysisStatusUI:
    def __init__(self):
        self._status_message: Optional[cl.Message] = None
        self._current_agents: Dict[str, str] = {}
        self._agent_timers: Dict[str, AgentTimer] = {}
        self._query: str = ""
        self._update_task: Optional[asyncio.Task] = None
        self._is_updating: bool = False
        self._start_time: float = 0.0  # 记录整体开始时间

    async def initialize(self, query: str) -> None:
        self._query = query
        self._current_agents = {}
        self._agent_timers = {}
        self._start_time = time.time()  # 记录开始时间
        
        for agent_type in [AgentType.FUNDAMENTAL, AgentType.TECHNICAL, AgentType.VALUE, AgentType.NEWS, AgentType.SUMMARY]:
            self._agent_timers[agent_type.value] = AgentTimer()
        
        self._status_message = cl.Message(
            content=self._build_status_content("初始化中..."),
            author="系统"
        )
        await self._status_message.send()
        
        self._is_updating = True
        self._update_task = asyncio.create_task(self._timer_update_loop())

    def _build_status_content(self, status: str) -> str:
        agent_status_lines = []
        
        for agent_type in [AgentType.FUNDAMENTAL, AgentType.TECHNICAL, AgentType.VALUE, AgentType.NEWS]:
            config = AGENT_CONFIGS[agent_type]
            agent_status = self._current_agents.get(agent_type.value, "⏳ 等待中")
            timer = self._agent_timers.get(agent_type.value)
            
            time_str = ""
            if timer and (timer.is_running or timer.final_time is not None):
                elapsed = timer.get_elapsed()
                time_str = f" `[{format_time(elapsed)}]`"
            
            agent_status_lines.append(f"- {config.icon} {config.name}: {agent_status}{time_str}")
        
        summary_status = self._current_agents.get(AgentType.SUMMARY.value, "⏳ 等待中")
        summary_timer = self._agent_timers.get(AgentType.SUMMARY.value)
        
        summary_time_str = ""
        if summary_timer and (summary_timer.is_running or summary_timer.final_time is not None):
            elapsed = summary_timer.get_elapsed()
            summary_time_str = f" `[{format_time(elapsed)}]`"
        
        total_elapsed = self._get_total_elapsed_time()
        
        return f"""
### 🔍 分析进度

**查询：** {self._query}

**各维度分析状态：**
{chr(10).join(agent_status_lines)}

- 🎯 综合研判: {summary_status}{summary_time_str}

**总耗时：** `{format_time(total_elapsed)}` | **当前状态：** {status}
"""

    def _get_total_elapsed_time(self) -> float:
        """计算总耗时（从开始到现在）"""
        if self._start_time == 0.0:
            return 0.0
        return time.time() - self._start_time

    async def _timer_update_loop(self) -> None:
        """后台任务：每秒更新计时器显示"""
        while self._is_updating:
            try:
                any_running = any(t.is_running for t in self._agent_timers.values())
                
                if self._status_message:
                    self._status_message.content = self._build_status_content(
                        self._get_current_status_text()
                    )
                    await self._status_message.update()
                
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Timer update error: {e}")
                break

    def _get_current_status_text(self) -> str:
        """获取当前状态文本，显示当前运行Agent的计时"""
        running_agents = []
        running_timer = None
        
        for agent_type in [AgentType.FUNDAMENTAL, AgentType.TECHNICAL, AgentType.VALUE, AgentType.NEWS, AgentType.SUMMARY]:
            timer = self._agent_timers.get(agent_type.value)
            if timer and timer.is_running:
                config = AGENT_CONFIGS.get(agent_type)
                if config:
                    running_agents.append(config.name)
                    if running_timer is None:
                        running_timer = timer
        
        if not running_agents:
            total_time = self._get_total_elapsed_time()
            return f"执行中 (已用时 {format_time(total_time)})"
        
        agent_text = ', '.join(running_agents[:2])
        if len(running_agents) > 2:
            agent_text += "..."
        
        # 显示当前运行Agent的计时
        if running_timer:
            agent_time = format_time(running_timer.get_elapsed())
            return f"执行中: {agent_text} (已用时 {agent_time})"
        
        return f"执行中: {agent_text}"

    async def update_agent_status(self, agent_type: AgentType, status: str) -> None:
        status_map = {
            "running": "🔄 执行中...",
            "completed": "✅ 完成",
            "error": "❌ 失败"
        }
        
        self._current_agents[agent_type.value] = status_map.get(status, status)
        
        timer = self._agent_timers.get(agent_type.value)
        if timer:
            if status == "running":
                timer.start()
            elif status in ["completed", "error"]:
                timer.stop()
        
        if self._status_message:
            status_text = f"{AGENT_CONFIGS[agent_type].name} {status_map.get(status, status)}"
            self._status_message.content = self._build_status_content(status_text)
            await self._status_message.update()

    async def complete(self, success: bool = True) -> None:
        self._is_updating = False
        
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        
        for timer in self._agent_timers.values():
            if timer.is_running:
                timer.stop()
        
        if self._status_message:
            final_status = "✅ 分析完成" if success else "❌ 分析失败"
            self._status_message.content = self._build_status_content(final_status)
            await self._status_message.update()
    
    async def cleanup(self) -> None:
        """清理资源"""
        self._is_updating = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass