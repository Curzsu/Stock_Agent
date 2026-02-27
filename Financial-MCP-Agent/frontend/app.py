"""
Financial-MCP-Agent Chainlit Frontend Application
"""
import os
import sys
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

import chainlit as cl
from chainlit.input_widget import TextInput, Select, Switch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_orchestrator import (
    AgentOrchestrator, 
    AgentProgress, 
    AgentType, 
    get_orchestrator,
    WorkflowResult
)
from ui_components import (
    ProgressTracker,
    MarkdownRenderer,
    ChatHistoryManager,
    ErrorMessageBuilder,
    WelcomeMessageBuilder,
    AnalysisStatusUI,
    AGENT_CONFIGS,
    format_time
)


chat_history = ChatHistoryManager()
progress_tracker: Optional[ProgressTracker] = None
status_ui: Optional[AnalysisStatusUI] = None


async def render_charts(charts: List[Dict[str, Any]]) -> None:
    """Render charts using Chainlit elements"""
    if not charts:
        return
    
    for i, chart in enumerate(charts):
        try:
            chart_type = chart.get("type", "bar")
            data = chart.get("data", {})
            options = chart.get("options", {})
            
            title = ""
            if "plugins" in options and "title" in options["plugins"]:
                title = options["plugins"]["title"].get("text", f"图表 {i+1}")
            
            elements = []
            
            if chart_type in ["bar", "line", "doughnut", "pie"]:
                chart_html = generate_chart_html(chart)
                
                await cl.Message(
                    content=f"### {title}",
                    elements=[cl.CustomElement(name="chart", payload={"html": chart_html})],
                    author="数据可视化"
                ).send()
                
        except Exception as e:
            print(f"Error rendering chart {i}: {e}")


def generate_chart_html(chart: Dict[str, Any]) -> str:
    """Generate HTML for Chart.js rendering"""
    chart_type = chart.get("type", "bar")
    data = chart.get("data", {})
    options = chart.get("options", {})
    
    import json
    data_json = json.dumps(data, ensure_ascii=False)
    options_json = json.dumps(options, ensure_ascii=False)
    
    html = f'''
    <div style="width: 100%; max-width: 600px; margin: 10px auto;">
        <canvas id="chart-{id(chart)}"></canvas>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        (function() {{
            const ctx = document.getElementById('chart-{id(chart)}').getContext('2d');
            new Chart(ctx, {{
                type: '{chart_type}',
                data: {data_json},
                options: {options_json}
            }});
        }})();
    </script>
    '''
    return html


async def render_summary_metrics(metrics: Dict[str, Any], company_name: str, stock_code: str) -> None:
    """Render summary metrics as a nice table"""
    if not metrics:
        return
    
    metric_display = {
        'roe': ('ROE', '%'),
        'pe_ratio': ('市盈率', '倍'),
        'pb_ratio': ('市净率', '倍'),
        'debt_ratio': ('负债率', '%'),
        'revenue_growth': ('营收增长', '%'),
        'profit_growth': ('利润增长', '%'),
        'rsi': ('RSI', ''),
        'risk_level': ('风险等级', '/5'),
        'sentiment_score': ('情感评分', ''),
    }
    
    table_rows = []
    for key, (name, unit) in metric_display.items():
        if key in metrics and metrics[key] is not None:
            value = metrics[key]
            if isinstance(value, float):
                value_str = f"{value:.2f}{unit}"
            else:
                value_str = f"{value}{unit}"
            table_rows.append(f"| {name} | {value_str} |")
    
    if not table_rows:
        return
    
    table_content = f"""
### 📋 关键指标汇总

| 指标 | 数值 |
|------|------|
{chr(10).join(table_rows)}

**股票**: {company_name or '未识别'} ({stock_code or '未识别'})
"""
    
    await cl.Message(
        content=table_content,
        author="系统"
    ).send()


@cl.on_chat_start
async def on_chat_start():
    global progress_tracker, status_ui
    
    progress_tracker = ProgressTracker()
    status_ui = AnalysisStatusUI()
    
    await WelcomeMessageBuilder.send()
    
    orchestrator = await get_orchestrator()
    
    cl.user_session.set("orchestrator", orchestrator)
    cl.user_session.set("chat_history", chat_history)
    cl.user_session.set("initialized_at", datetime.now().isoformat())


@cl.on_message
async def on_message(message: cl.Message):
    global progress_tracker, status_ui
    
    user_query = message.content.strip()
    
    if not user_query:
        await cl.ErrorMessage(
            content="请输入有效的分析请求，例如：'分析贵州茅台' 或 '600519怎么样'",
            author="系统"
        ).send()
        return
    
    chat_history.add_message("user", user_query)
    
    orchestrator: AgentOrchestrator = cl.user_session.get("orchestrator")
    if not orchestrator:
        orchestrator = await get_orchestrator()
        cl.user_session.set("orchestrator", orchestrator)
    
    if status_ui:
        await status_ui.cleanup()
    
    progress_tracker = ProgressTracker()
    status_ui = AnalysisStatusUI()
    
    await status_ui.initialize(user_query)
    
    thinking_message = await cl.Message(
        content="🔄 正在初始化分析引擎...",
        author="系统"
    ).send()
    
    async def progress_callback(progress: AgentProgress):
        try:
            if progress.agent_name == "system":
                thinking_message.content = f"🔄 {progress.message}"
                await thinking_message.update()
                return
            
            agent_type = None
            for at in AgentType:
                if at.value == progress.agent_name:
                    agent_type = at
                    break
            
            if not agent_type:
                return
            
            config = AGENT_CONFIGS.get(agent_type)
            if not config:
                return
            
            await status_ui.update_agent_status(agent_type, progress.status)
            
            if progress.status == "running":
                step = progress_tracker.get_agent_step(agent_type)
                if not step:
                    await progress_tracker.create_agent_step(agent_type)
                
                thinking_message.content = f"{config.icon} {config.name}: {progress.message}"
                await thinking_message.update()
            
            elif progress.status == "completed":
                step = progress_tracker.get_agent_step(agent_type)
                if step:
                    step.output = progress.message
                    await step.update()
                
            elif progress.status == "error":
                step = progress_tracker.get_agent_step(agent_type)
                if step:
                    step.output = f"❌ 错误: {progress.error}"
                    step.is_error = True
                    await step.update()
                
                thinking_message.content = f"❌ {config.name} 执行失败: {progress.error}"
                await thinking_message.update()
        
        except Exception as e:
            print(f"Progress callback error: {e}")
    
    try:
        result: WorkflowResult = await orchestrator.run_analysis(
            user_query,
            progress_callback=progress_callback
        )
        
        await thinking_message.remove()
        
        if result.success and result.final_report:
            await status_ui.complete(success=True)
            
            # 获取图表数据和摘要指标
            charts = getattr(result, 'charts', None) or (result.agent_results.get('charts') if result.agent_results else None)
            summary_metrics = getattr(result, 'summary_metrics', None) or (result.agent_results.get('summary_metrics') if result.agent_results else None)
            
            # 尝试从 agent_results 中获取
            if not charts and hasattr(result, '__dict__'):
                charts = result.__dict__.get('charts', [])
            if not summary_metrics and hasattr(result, '__dict__'):
                summary_metrics = result.__dict__.get('summary_metrics', {})
            
            formatted_report = MarkdownRenderer.format_final_report(
                result.final_report,
                result.company_name,
                result.stock_code
            )
            
            report_message = await cl.Message(
                content=formatted_report,
                author="综合研报"
            ).send()
            
            # 渲染图表
            if charts:
                await render_charts(charts)
            
            # 渲染摘要指标
            if summary_metrics:
                await render_summary_metrics(
                    summary_metrics, 
                    result.company_name or '未识别', 
                    result.stock_code or '未识别'
                )
            
            if result.report_path:
                await cl.Message(
                    content=f"📄 完整报告已保存至: `{result.report_path}`",
                    author="系统"
                ).send()
            
            total_time_str = format_time(result.execution_time)
            execution_info = f"""
### 📊 分析统计

| 项目 | 详情 |
|------|------|
| 总分析时长 | {total_time_str} |
| 股票代码 | {result.stock_code or '未识别'} |
| 公司名称 | {result.company_name or '未识别'} |
| 报告长度 | {len(result.final_report)} 字符 |
"""
            await cl.Message(
                content=execution_info,
                author="系统"
            ).send()
            
            chat_history.add_message("assistant", result.final_report[:500] + "...")
        
        else:
            await status_ui.complete(success=False)
            
            error_content = "## ❌ 分析失败\n\n"
            
            if result.errors:
                error_content += "**错误详情：**\n"
                for err in result.errors:
                    error_content += f"- {err}\n"
            
            error_type = ErrorMessageBuilder.classify_error(
                "; ".join(result.errors) if result.errors else "unknown"
            )
            error_msg = ErrorMessageBuilder.build(
                error_type,
                "; ".join(result.errors) if result.errors else None
            )
            await error_msg.send()
            
            chat_history.add_message("assistant", f"分析失败: {result.errors}")
    
    except asyncio.TimeoutError:
        await thinking_message.remove()
        if status_ui:
            await status_ui.complete(success=False)
        await ErrorMessageBuilder.build("timeout").send()
    
    except ConnectionError as e:
        await thinking_message.remove()
        if status_ui:
            await status_ui.complete(success=False)
        await ErrorMessageBuilder.build("mcp_connection", str(e)).send()
    
    except Exception as e:
        await thinking_message.remove()
        if status_ui:
            await status_ui.complete(success=False)
        
        error_type = ErrorMessageBuilder.classify_error(str(e))
        await ErrorMessageBuilder.build(error_type, str(e)).send()
        
        import traceback
        traceback.print_exc()


@cl.action_callback("analyze_another")
async def on_analyze_another(action: cl.Action):
    await cl.Message(
        content="请输入您想要分析的股票名称或代码",
        author="系统"
    ).send()


@cl.action_callback("view_history")
async def on_view_history(action: cl.Action):
    history = chat_history.get_history(limit=10)
    
    if not history:
        await cl.Message(
            content="暂无历史记录",
            author="系统"
        ).send()
        return
    
    history_content = "## 📜 对话历史\n\n"
    for msg in history:
        role = "👤 用户" if msg["role"] == "user" else "🤖 助手"
        timestamp = msg.get("timestamp", "")[:19]
        history_content += f"**{role}** ({timestamp}):\n{msg['content'][:200]}...\n\n"
    
    await cl.Message(
        content=history_content,
        author="系统"
    ).send()


@cl.on_chat_end
async def on_chat_end():
    global progress_tracker, status_ui
    
    if status_ui:
        await status_ui.cleanup()
    
    progress_tracker = None
    status_ui = None
    
    history = chat_history.get_history()
    if history:
        print(f"Session ended. Total messages: {len(history)}")


@cl.set_chat_profiles
async def chat_profile():
    return [
        cl.ChatProfile(
            name="financial_analysis",
            markdown_description="A股金融智能体分析系统 - 多维度深度分析",
            icon="📊",
        ),
    ]


@cl.on_settings_update
async def on_settings_update(settings):
    pass