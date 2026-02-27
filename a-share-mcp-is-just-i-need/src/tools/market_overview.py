"""
市场概览工具，用于MCP服务器
包含获取交易日和所有股票数据的工具
"""
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from src.data_source_interface import FinancialDataSource, NoDataFoundError, LoginError, DataSourceError
from src.formatting.markdown_formatter import format_df_to_markdown
import pandas as pd

logger = logging.getLogger(__name__)

# 全局缓存
_cached_all_stock_df: Optional[pd.DataFrame] = None
_cached_all_stock_date: Optional[str] = None

def get_cached_all_stock(active_data_source, date: Optional[str] = None) -> pd.DataFrame:
    """获取缓存的全市场股票列表，如果缓存不存在则请求"""
    global _cached_all_stock_df, _cached_all_stock_date
    
    # 如果有缓存且日期匹配（或者请求的是最新数据且缓存存在），则返回缓存
    if _cached_all_stock_df is not None and not _cached_all_stock_df.empty:
        # 如果请求特定日期，且缓存的日期与请求不符，则需要重新获取（这里简单处理，如果date为None则复用）
        if date is None or date == _cached_all_stock_date:
            logger.info("Using cached stock list.")
            return _cached_all_stock_df
            
    logger.info("Fetching fresh stock list for cache.")
    df = active_data_source.get_all_stock(date=date)
    
    if not df.empty:
        _cached_all_stock_df = df
        _cached_all_stock_date = date
        
    return df

def safe_market_data_fetch(
    func_name: str,
    data_source_func,
    data_type: str,
    **kwargs
) -> str:
    """
    安全的市场数据获取函数，统一处理所有异常和错误情况
    
    参数:
        func_name: 函数名称，用于日志记录
        data_source_func: 数据源函数
        data_type: 数据类型描述
        **kwargs: 传递给数据源函数的关键字参数
        
    返回:
        Markdown格式的数据表格或错误消息
    """
    try:
        # 调用数据源函数
        df = data_source_func(**kwargs)
        logger.info(f"Successfully retrieved {data_type} data.")
        return format_df_to_markdown(df)
        
    except NoDataFoundError as e:
        logger.warning(f"NoDataFoundError: {e}")
        return f"Error: {e}"
    except LoginError as e:
        logger.error(f"LoginError: {e}")
        return f"Error: Could not connect to data source. {e}"
    except DataSourceError as e:
        logger.error(f"DataSourceError: {e}")
        return f"Error: An error occurred while fetching data. {e}"
    except ValueError as e:
        logger.warning(f"ValueError: {e}")
        return f"Error: Invalid input parameter. {e}"
    except Exception as e:
        logger.exception(f"Unexpected Exception processing {func_name}: {e}")
        return f"Error: An unexpected error occurred: {e}"


def register_market_overview_tools(app: FastMCP, active_data_source: FinancialDataSource):
    """
    向MCP应用注册市场概览工具

    参数:
        app: FastMCP应用实例
        active_data_source: 活跃的金融数据源
    """

    @app.tool()
    def get_trade_dates(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
        """
        获取指定范围内的交易日信息

        参数:
            start_date: 可选的开始日期，格式为'YYYY-MM-DD'。如果为None，默认为2015-01-01
            end_date: 可选的结束日期，格式为'YYYY-MM-DD'。如果为None，默认为当前日期

        返回:
            指示范围内每个日期是否为交易日（1）或非交易日（0）的Markdown表格
        """
        logger.info(
            f"Tool 'get_trade_dates' called for range {start_date or 'default'} to {end_date or 'default'}")
        
        return safe_market_data_fetch(
            "get_trade_dates",
            active_data_source.get_trade_dates,
            "交易日",
            start_date=start_date,
            end_date=end_date
        )

    @app.tool()
    def get_all_stock(date: Optional[str] = None) -> str:
        """
        获取指定日期的所有股票（A股和指数）列表及其交易状态

        参数:
            date: 可选的日期，格式为'YYYY-MM-DD'。如果为None，则使用当前日期

        返回:
            列出股票代码、名称及其交易状态（1=交易中，0=停牌）的Markdown表格
        """
        logger.info(
            f"Tool 'get_all_stock' called for date={date or 'default'}")
        
        return safe_market_data_fetch(
            "get_all_stock",
            active_data_source.get_all_stock,
            "所有股票",
            date=date
        )

    @app.tool()
    def search_stock_by_name(name: str) -> str:
        """
        根据股票名称或代码模糊搜索股票信息

        参数:
            name: 股票名称关键词（如"平安银行"）或代码（如"000001"）

        返回:
            包含匹配股票的代码、名称和交易状态的Markdown表格
        """
        logger.info(f"Tool 'search_stock_by_name' called for name={name}")
        
        try:
            # 使用缓存获取全市场股票列表
            df = get_cached_all_stock(active_data_source)
            
            if df.empty:
                # 如果缓存为空，尝试强制刷新
                df = active_data_source.get_all_stock()
                if df.empty:
                    return "Error: Failed to retrieve stock list from data source."
            
            # 进行模糊匹配
            # 确保name不为空
            if not name or not name.strip():
                return "Error: Search name cannot be empty."
                
            name = name.strip()
            
            # 在code和code_name列中搜索
            # Baostock返回的列通常是: code, tradeStatus, code_name
            # 有时候可能是 code, tradeStatus, code_name
            
            # 检查列名是否存在
            if 'code_name' not in df.columns and 'code' not in df.columns:
                 return f"Error: Unexpected data format. Columns: {df.columns.tolist()}"

            # 过滤
            mask = df['code_name'].astype(str).str.contains(name, case=False, na=False) | \
                   df['code'].astype(str).str.contains(name, case=False, na=False)
            
            result_df = df[mask]
            
            if result_df.empty:
                return f"No stocks found matching '{name}'."
                
            # 限制返回数量，避免过多
            if len(result_df) > 20:
                result_df = result_df.head(20)
                logger.info(f"Found {len(df[mask])} matches, returning top 20.")
            
            return format_df_to_markdown(result_df)
            
        except Exception as e:
            logger.error(f"Error searching stock: {e}", exc_info=True)
            return f"Error searching stock: {e}"

