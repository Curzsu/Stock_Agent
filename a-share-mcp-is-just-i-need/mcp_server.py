# Main MCP server file
import logging
import sys
from datetime import datetime

from mcp.server.fastmcp import FastMCP

# Import the interface and the concrete implementation
from src.data_source_interface import FinancialDataSource
from src.baostock_data_source import BaostockDataSource
from src.utils import setup_logging

# 导入各模块工具的注册函数
from src.tools.stock_market import register_stock_market_tools
from src.tools.financial_reports import register_financial_report_tools
from src.tools.indices import register_index_tools
from src.tools.market_overview import register_market_overview_tools
from src.tools.macroeconomic import register_macroeconomic_tools
from src.tools.date_utils import register_date_utils_tools
from src.tools.analysis import register_analysis_tools
from src.tools.news_crawler import register_news_crawler_tools

# --- Logging Setup ---
# Call the setup function from utils
# You can control the default level here (e.g., logging.DEBUG for more verbose logs)
setup_logging(level=logging.DEBUG)  # Changed to DEBUG to capture more info
logger = logging.getLogger(__name__)

# --- Dependency Injection ---
# Instantiate the data source - easy to swap later if needed
try:
    logger.debug("Initializing BaostockDataSource...")
    active_data_source: FinancialDataSource = BaostockDataSource()
    logger.info("BaostockDataSource successfully created")
except Exception as e:
    logger.error(f"Failed to initialize BaostockDataSource: {e}")
    # 确保错误在控制台也能显示
    print(f"ERROR: Failed to initialize BaostockDataSource: {e}")
    # 阻止应用启动以防止问题被掩盖
    raise e

# --- Get current date for system prompt ---
current_date = datetime.now().strftime("%Y-%m-%d")

# --- FastMCP App Initialization ---
# FastMCP constructor doesn't accept any arguments, so just initialize without params
app = FastMCP()

# --- 注册各模块的工具 ---
try:
    register_stock_market_tools(app, active_data_source)
    register_financial_report_tools(app, active_data_source)
    register_index_tools(app, active_data_source)
    register_market_overview_tools(app, active_data_source)
    register_macroeconomic_tools(app, active_data_source)
    register_date_utils_tools(app, active_data_source)
    register_analysis_tools(app, active_data_source)
    register_news_crawler_tools(app, active_data_source)
    logger.info("All tools registered successfully")
except Exception as e:
    logger.error(f"Error registering tools: {e}")
    print(f"ERROR: Error registering tools: {e}")
    raise

# --- Main Execution Block ---
if __name__ == "__main__":
    logger.info(
        f"Starting A-Share MCP Server via stdio... Today is {current_date}")
    try:
        # Run the server using stdio transport, suitable for MCP Hosts like Claude Desktop
        app.run(transport='stdio')
    except KeyboardInterrupt:
        logger.info("MCP Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error running MCP server: {e}")
        print(f"ERROR: Error running MCP server: {e}")
        raise
