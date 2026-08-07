"""
金融分析智能体系统主程序 (Financial Analysis AI Agent System Main Program)

本文件是金融分析智能体系统的核心入口点，实现了以下主要功能：

1. 多智能体工作流管理：使用LangGraph构建并行执行的智能体工作流
2. 命令行界面：提供用户友好的交互式命令行界面
3. 自然语言处理：自动识别和提取股票代码、公司名称
4. 日志系统：完整的执行日志记录和错误处理
5. 报告生成：生成综合性的金融分析报告

工作流程：
start_node → [fundamental_analyst, technical_analyst, value_analyst] → summarizer → END
"""

# ============================================================================
# 导入必要的模块和依赖
# ============================================================================

# 在导入其他模块之前设置环境变量，抑制无用输出
import os
import sys

# 设置环境变量来抑制transformers和其他库的冗余输出
os.environ["TRANSFORMERS_VERBOSITY"] = "error"  # 只显示错误信息
os.environ["TOKENIZERS_PARALLELISM"] = "false"  # 禁用tokenizer并行化警告
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"  # 减少CUDA相关输出
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"  # 减少内存分配信息

# 设置日志级别，抑制第三方库的INFO级别输出
import logging
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("accelerate").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# 日志和状态管理相关导入
from src.utils.logging_config import setup_logger, SUCCESS_ICON, ERROR_ICON, WAIT_ICON
from src.utils.state_definition import AgentState
from src.utils.execution_logger import initialize_execution_logger, finalize_execution_logger, get_execution_logger

# 股票信息提取共享模块（P2-3: 合并 main.py 与 server.py 两套 extract_stock_info）
from src.utils.stock_extractor import extract_stock_info

# 智能体模块导入 - 五个核心分析智能体
from src.agents.summary_agent import summary_agent      # 总结智能体：整合所有分析结果
from src.agents.value_agent import value_agent          # 估值智能体：分析股票估值水平
from src.agents.technical_agent import technical_agent  # 技术分析智能体：分析价格趋势和技术指标
from src.agents.fundamental_agent import fundamental_agent  # 基本面智能体：分析财务状况和盈利能力
from src.agents.news_agent import news_agent            # 新闻分析智能体：分析新闻情感和风险

# LangGraph工作流框架导入（构图逻辑在 workflow_builder 工厂内）
from src.utils.workflow_builder import build_workflow

# 环境变量和系统相关导入
from dotenv import load_dotenv
import argparse
import asyncio
import re
from datetime import datetime

# ============================================================================
# 初始化和配置
# ============================================================================

# 设置日志记录器
logger = setup_logger(__name__)

# 添加项目根目录到Python路径，确保模块导入正常工作
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# 加载环境变量（从.env文件）
load_dotenv(override=True)

# 调试：打印关键环境变量以验证配置
logger.info(f"Environment Variables Loaded:")
logger.info(
    f"  OPENAI_COMPATIBLE_MODEL: {os.getenv('OPENAI_COMPATIBLE_MODEL', 'Not Set')}")
logger.info(
    f"  OPENAI_COMPATIBLE_BASE_URL: {os.getenv('OPENAI_COMPATIBLE_BASE_URL', 'Not Set')}")
logger.info(
    f"  OPENAI_COMPATIBLE_API_KEY: {'*' * 20 if os.getenv('OPENAI_COMPATIBLE_API_KEY') else 'Not Set'}")

# 重新设置日志记录器（确保正确配置）
logger = setup_logger(__name__)


async def main():
    """
    主函数：金融分析智能体系统的核心执行逻辑
    
    功能包括：
    1. 初始化执行日志系统
    2. 构建LangGraph工作流
    3. 处理命令行参数和用户输入
    4. 提取股票信息（代码、公司名称）
    5. 执行多智能体分析工作流
    6. 生成和保存分析报告
    7. 错误处理和日志记录
    """
    
    # 初始化执行日志系统
    execution_logger = initialize_execution_logger()
    logger.info(
        f"{SUCCESS_ICON} 执行日志系统已初始化，日志目录: {execution_logger.execution_dir}")

    try:
        # ============================================================================
        # 1. 构建LangGraph工作流（共享工厂，与 server.py 共用同一拓扑）
        # ============================================================================
        app = build_workflow(
            fundamental_agent=fundamental_agent,
            technical_agent=technical_agent,
            value_agent=value_agent,
            news_agent=news_agent,
            summary_agent=summary_agent,
        )

        # ============================================================================
        # 2. 实现命令行界面 
        # ============================================================================
        
        # 创建命令行参数解析器
        parser = argparse.ArgumentParser(description="Financial Agent CLI")
        parser.add_argument(
            "--command",
            type=str,
            required=False,  # 改为非必需，支持交互式输入
            help="The user query for financial analysis (e.g., '分析嘉友国际')"
        )
        args = parser.parse_args()

        # 处理用户查询输入
        if args.command:
            # 如果通过命令行参数提供查询
            user_query = args.command
        else:
            # 显示ASCII艺术开屏图像和交互式界面
            print("\n")
            print(
                "╔══════════════════════════════════════════════════════════════════════════════╗")
            print(
                "║                                                                              ║")
            print(
                "║      ███████╗██╗███╗   ██╗ █████╗ ███╗   ██╗ ██████╗██╗ █████╗ ██╗          ║")
            print(
                "║      ██╔════╝██║████╗  ██║██╔══██╗████╗  ██║██╔════╝██║██╔══██╗██║          ║")
            print(
                "║      █████╗  ██║██╔██╗ ██║███████║██╔██╗ ██║██║     ██║███████║██║          ║")
            print(
                "║      ██╔══╝  ██║██║╚██╗██║██╔══██║██║╚██╗██║██║     ██║██╔══██║██║          ║")
            print(
                "║      ██║     ██║██║ ╚████║██║  ██║██║ ╚████║╚██████╗██║██║  ██║███████╗      ║")
            print(
                "║      ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝╚═╝╚═╝  ╚═╝╚══════╝      ║")
            print(
                "║                                                                              ║")
            print(
                "║                █████╗  ██████╗ ███████╗███╗   ██╗████████╗                  ║")
            print(
                "║               ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝                  ║")
            print(
                "║               ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║                     ║")
            print(
                "║               ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║                     ║")
            print(
                "║               ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║                     ║")
            print(
                "║               ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝                     ║")
            print(
                "║                                                                              ║")
            print("║                          🏦 金融分析智能体系统                              ║")
            print(
                "║                     Financial Analysis AI Agent System                      ║")
            print(
                "║                                                                              ║")
            print(
                "║    ┌─────────────────────────────────────────────────────────────────┐     ║")
            print("║    │  📊 基本面分析  │  📈 技术分析  │  💰 估值分析  │  📰 新闻分析  │  🤖 智能总结  │    ║")
            print(
                "║    └─────────────────────────────────────────────────────────────────┘     ║")
            print(
                "║                                                                              ║")
            print(
                "╚══════════════════════════════════════════════════════════════════════════════╝")
            print("\n🔹 本系统可以对A股公司进行全面分析，包括：")
            print("  • 基本面分析 - 财务状况、盈利能力和行业地位")
            print("  • 技术面分析 - 价格趋势、交易量和技术指标")
            print("  • 估值分析 - 市盈率、市净率等估值水平")
            print("  • 新闻分析 - 新闻情感分析和风险评估")
            print("\n🔹 支持多种自然语言查询方式：")
            print("  • 分析嘉友国际")
            print("  • 帮我看看比亚迪这只股票怎么样")
            print("  • 我想了解一下腾讯的投资价值")
            print("  • 603871 这个股票值得买吗？")
            print("  • 给我分析一下宁德时代的财务状况")
            print("\n🔹 您可以用任何自然语言描述您的分析需求")
            print("🔹 系统会自动识别股票名称和代码，并进行全面分析")
            print("\n💡 提示：建议使用股票代码（如 000001、600036）以获得更准确的分析结果")
            print("\n" + "─" * 78 + "\n")

            # 获取用户输入
            user_query = input("💬 请输入您的分析需求: ")

            # 确保输入不为空
            while not user_query.strip():
                print(f"{ERROR_ICON} 输入不能为空，请重新输入！")
                user_query = input("请输入您的分析需求: ")

        # 记录用户查询到执行日志
        execution_logger.log_agent_start("main", {"user_query": user_query})

        # ============================================================================
        # 3. 自然语言处理和股票信息提取
        # ============================================================================
        
        # 从查询中提取股票代码和公司名称
        stock_code = None
        company_name = None

        # 使用共享模块的 extract_stock_info（P2-3: 合并 main.py 与 server.py 两套实现）

        # 执行提取
        company_name, stock_code = extract_stock_info(user_query)

        # 记录提取结果
        logger.info(f"从查询中提取 - 公司名称: {company_name}, 股票代码: {stock_code}")

        # ============================================================================
        # 4. 时间信息处理
        # ============================================================================
        
        # 获取当前时间信息
        current_datetime = datetime.now()
        current_date_cn = current_datetime.strftime("%Y年%m月%d日")
        current_date_en = current_datetime.strftime("%Y-%m-%d")
        current_weekday_cn = ["星期一", "星期二", "星期三", "星期四",
                              "星期五", "星期六", "星期日"][current_datetime.weekday()]
        current_time = current_datetime.strftime("%H:%M:%S")

        # 格式化完整的时间信息
        current_time_info = f"{current_date_cn} ({current_date_en}) {current_weekday_cn} {current_time}"

        logger.info(f"当前时间: {current_time_info}")

        # ============================================================================
        # 5. 准备初始状态数据
        # ============================================================================
        
        # 准备初始状态
        initial_data = {
            "query": user_query,
            "current_date": current_date_en,
            "current_date_cn": current_date_cn,
            "current_time": current_time,
            "current_weekday_cn": current_weekday_cn,
            "current_time_info": current_time_info,
            "analysis_timestamp": current_datetime.isoformat()
        }
        
        # 添加公司名称（如果提取到）
        if company_name:
            initial_data["company_name"] = company_name
            
        # 添加股票代码（如果提取到），并添加交易所前缀
        if stock_code:
            # 根据股票代码规则添加交易所前缀
            if stock_code.startswith('6'):
                initial_data["stock_code"] = f"sh.{stock_code}"  # 上海证券交易所
            elif stock_code.startswith('0') or stock_code.startswith('3'):
                initial_data["stock_code"] = f"sz.{stock_code}"  # 深圳证券交易所
            else:
                initial_data["stock_code"] = stock_code

        # 创建LangGraph工作流的初始状态
        initial_state = AgentState(
            messages=[],  # Langchain约定：消息列表
            data=initial_data,  # 应用特定数据，包含提取的信息
            metadata={}  # 其他运行时特定信息
        )

        # ============================================================================
        # 6. 执行工作流
        # ============================================================================
        
        # 显示分析开始信息
        print(f"\n{WAIT_ICON} 正在开始对 '{user_query}' 进行金融分析...")
        if company_name:
            print(f"{WAIT_ICON} 分析公司: {company_name}")
        if stock_code:
            print(f"{WAIT_ICON} 股票代码: {stock_code}")
        logger.info(
            f"Starting financial analysis workflow for query: '{user_query}'")

        # 显示分析阶段提示
        print(f"\n{WAIT_ICON} 正在执行基本面分析...")
        print(f"{WAIT_ICON} 正在执行技术面分析...")
        print(f"{WAIT_ICON} 正在执行估值分析...")
        print(f"{WAIT_ICON} 正在执行新闻分析...")
        print(f"{WAIT_ICON} 这可能需要几分钟时间，请耐心等待...\n")

        # 调用工作流 - 这是阻塞调用，会等待所有智能体完成
        final_state = await app.ainvoke(initial_state)
        print(f"{SUCCESS_ICON} 分析完成！")
        logger.info("Workflow execution completed successfully")

        # ============================================================================
        # 7. 结果处理和报告生成
        # ============================================================================
        
        # 提取并打印最终报告
        if final_state and final_state.get("data") and "final_report" in final_state["data"]:
            print("\n--- 最终分析报告 (Final Analysis Report) ---\n")
            # print(final_state["data"]["final_report"])

            # 显示报告文件路径（如果可用）
            if "report_path" in final_state["data"]:
                print(
                    f"\n{SUCCESS_ICON} 报告已保存到: {final_state['data']['report_path']}")
                logger.info(
                    f"Report saved to: {final_state['data']['report_path']}")

                # 记录最终报告到执行日志
                execution_logger.log_final_report(
                    final_state["data"]["final_report"],
                    final_state["data"]["report_path"]
                )
        else:
            print(f"\n{ERROR_ICON} 错误: 无法从工作流中检索最终报告。")
            logger.error(
                "Could not retrieve the final report from the workflow")
            print("调试信息 - 最终状态内容:", final_state)

        # 完成执行日志记录
        finalize_execution_logger(success=True)
        print(f"{SUCCESS_ICON} 执行日志已保存到: {execution_logger.execution_dir}")

    except Exception as e:
        # ============================================================================
        # 8. 错误处理
        # ============================================================================
        
        print(f"\n{ERROR_ICON} 工作流执行期间发生错误: {e}")
        logger.error(f"Error during workflow execution: {e}", exc_info=True)

        # 记录错误并完成执行日志
        finalize_execution_logger(success=False, error=str(e))
        print(f"{ERROR_ICON} 错误日志已保存到: {get_execution_logger().execution_dir}")


# ============================================================================
# 程序入口点
# ============================================================================

if __name__ == "__main__":
    # 使用asyncio运行主函数
    asyncio.run(main())
