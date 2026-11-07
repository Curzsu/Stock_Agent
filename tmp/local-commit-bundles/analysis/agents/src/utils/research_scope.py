"""Request-local successful data reuse and singleflight, before the RPC lock."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import os
from langchain_core.tools import ToolException

_scope = ContextVar('research_data', default=None)
_role = ContextVar('research_role', default='standalone')


def successful(value):
    wrapped = isinstance(value, tuple) and len(value) == 2
    artifact = value[1] if wrapped else None
    if artifact is not None and (getattr(artifact, 'isError', False) or
                                 isinstance(artifact, dict) and artifact.get('isError')):
        return False
    content = value[0] if wrapped else value
    if isinstance(content, list):
        text = '\n'.join(b if isinstance(b, str) else b.get('text', '')
                         for b in content if isinstance(b, (str, dict)))
    else:
        text = str(content or '')
    return bool(text.strip()) and not any(marker in text for marker in
        ('Error:', '错误', '超时', '未找到', '出错', 'No data', 'not available',
         '安全验证', '无法获取', '没有找到', '未能获取', '未获取到', '未提供数据'))


@asynccontextmanager
async def research_scope():
    store = {'cache': {}, 'tasks': {}, 'calls': {}}
    token = _scope.set(store)
    try:
        yield store
    finally:
        pending = list(store['tasks'].values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        _scope.reset(token)


@contextmanager
def agent_role(role):
    token = _role.set(role)
    try:
        yield
    finally:
        _role.reset(token)


async def reuse_query(name, arguments, fetch):
    store = _scope.get()
    if store is None:
        return await fetch()
    from src.utils.observability import trace_scope
    key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(',', ':')))
    if key in store['cache']:
        with trace_scope('data.cache_hit', metadata={'tool': name}):
            return deepcopy(store['cache'][key])
    if key in store['tasks']:
        with trace_scope('data.shared_wait', metadata={'tool': name}):
            return deepcopy(await asyncio.shield(store['tasks'][key]))
    role = _role.get()
    used = store['calls'].get(role, 0)
    if used >= int(os.getenv('ANALYSIS_TOOL_CALL_LIMIT', '12')):
        raise ToolException('本角色取数预算已用完，请使用已取得的真实数据收尾并注明缺失项。')
    store['calls'][role] = used + 1

    async def worker():
        try:
            value = await fetch()
            if successful(value):
                store['cache'][key] = deepcopy(value)
            return value
        finally:
            store['tasks'].pop(key, None)
    store['tasks'][key] = asyncio.create_task(worker())
    store['tasks'][key].add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
    return deepcopy(await asyncio.shield(store['tasks'][key]))


PROFILES = {
    'technical': {'get_stock_basic_info', 'get_latest_trading_date', 'get_historical_k_data'},
    'news': {'crawl_news', 'get_stock_basic_info', 'get_latest_trading_date'},
    'fundamental': {'get_stock_basic_info', 'get_stock_industry', 'get_profit_data', 'get_growth_data',
                    'get_operation_data', 'get_balance_data', 'get_cash_flow_data', 'get_dupont_data', 'get_dividend_data'},
    'value': {'get_stock_basic_info', 'get_stock_industry', 'get_profit_data', 'get_growth_data',
              'get_balance_data', 'get_cash_flow_data', 'get_dividend_data', 'get_historical_k_data', 'get_latest_trading_date'},
}


def tools_for_role(tools, role):
    return [tool for tool in tools if tool.name in PROFILES[role.replace('_agent', '')]]
