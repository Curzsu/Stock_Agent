"""
Summary Agent: Consolidates analyses from other agents into a final report.
汇总 Agent：将其他 Agent的分析结果整合成最终报告
"""
import os
import time
from typing import Dict, Any
from langchain_openai import ChatOpenAI
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from llama_cpp import Llama
import re

from src.utils.state_definition import AgentState
from src.utils.logging_config import setup_logger, ERROR_ICON, SUCCESS_ICON, WAIT_ICON
from src.utils.execution_logger import get_execution_logger
from dotenv import load_dotenv

load_dotenv(override=True)

logger = setup_logger(__name__)

_gguf_model_cache = None


def load_gguf_model():
    """加载 GGUF 模型，自动检测 GPU"""
    global _gguf_model_cache
    
    if _gguf_model_cache is not None:
        logger.info(f"{SUCCESS_ICON} Returning cached GGUF model")
        return _gguf_model_cache
    
    model_path = os.getenv("GGUF_MODEL_PATH")
    n_ctx = int(os.getenv("GGUF_N_CTX", "8192"))
    n_threads = int(os.getenv("GGUF_N_THREADS", "8"))
    
    n_gpu_layers = int(os.getenv("GGUF_N_GPU_LAYERS", "-1"))
    
    if n_gpu_layers == -1:
        try:
            import torch
            if torch.cuda.is_available():
                n_gpu_layers = -1
                logger.info(f"{SUCCESS_ICON} GPU detected: {torch.cuda.get_device_name(0)}")
            else:
                n_gpu_layers = 0
                logger.info(f"{WAIT_ICON} No GPU detected, using CPU")
        except ImportError:
            n_gpu_layers = 0
            logger.info(f"{WAIT_ICON} torch not available, using CPU")
    
    if not model_path or not os.path.exists(model_path):
        raise FileNotFoundError(f"GGUF model not found at: {model_path}")
    
    logger.info(f"{WAIT_ICON} Loading GGUF model from {model_path}...")
    logger.info(f"  - n_ctx: {n_ctx}")
    logger.info(f"  - n_gpu_layers: {n_gpu_layers} (-1 = all layers on GPU)")
    logger.info(f"  - n_threads: {n_threads}")
    
    llm = Llama(
        model_path=model_path,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        n_threads=n_threads,
        verbose=False
    )
    
    _gguf_model_cache = llm
    logger.info(f"{SUCCESS_ICON} GGUF model loaded successfully")
    return llm


def generate_report_with_gguf(llm, prompt, max_tokens=3000):
    """使用 GGUF 模型生成报告"""
    try:
        logger.info(f"{WAIT_ICON} Generating report with GGUF model (max_tokens={max_tokens})...")
        logger.info(f"Prompt length: {len(prompt)} characters")
        
        output = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.5,
            top_p=0.9,
            top_k=40,
            stop=["</s>", "<|im_end|>", "<|endoftext|>", "\n\n\n"],
            repeat_penalty=1.1
        )
        
        generated_text = output['choices'][0]['text'].strip()
        logger.info(f"{SUCCESS_ICON} GGUF generation completed, output length: {len(generated_text)}")
        
        if not generated_text:
            logger.warning("GGUF returned empty output, returning fallback message")
            return "报告生成完成，但模型未返回有效内容。请检查模型是否正确微调。"
        
        return generated_text
        
    except Exception as e:
        logger.error(f"{ERROR_ICON} Error generating report with GGUF: {e}", exc_info=True)
        raise e


def truncate_report_at_baseline_time(report_content: str, current_time_info: str) -> str:
    """
    使用正则表达式截断报告，在"分析基准时间"那一行之后停止
    
    Args:
        report_content: 完整的报告内容
        current_time_info: 当前时间信息
    
    Returns:
        截断后的报告内容
    """
    baseline_patterns = [
        rf'分析基准时间[：:]\s*{re.escape(current_time_info)}',
        rf'分析基准时间[：:]\s*{re.escape(current_time_info)}\s*$',
        rf'基准时间[：:]\s*{re.escape(current_time_info)}',
        rf'时间基准[：:]\s*{re.escape(current_time_info)}',
        rf'分析时间[：:]\s*{re.escape(current_time_info)}',
        rf'报告时间[：:]\s*{re.escape(current_time_info)}',
        rf'生成时间[：:]\s*{re.escape(current_time_info)}',
        rf'更新时间[：:]\s*{re.escape(current_time_info)}',
        rf'数据时间[：:]\s*{re.escape(current_time_info)}',
        rf'分析基准[：:]\s*{re.escape(current_time_info)}'
    ]
    
    for pattern in baseline_patterns:
        match = re.search(pattern, report_content, re.MULTILINE | re.IGNORECASE)
        if match:
            end_pos = match.end()
            line_end = report_content.find('\n', end_pos)
            if line_end == -1:
                truncated_content = report_content[:end_pos].strip()
            else:
                truncated_content = report_content[:line_end].strip()
            
            logger.info(f"截断报告在'分析基准时间'行之后，截断位置: {end_pos}")
            return truncated_content
    
    time_patterns = [
        rf'.*{re.escape(current_time_info)}.*',
        rf'.*{re.escape(current_time_info.split()[0])}.*',
        rf'.*{re.escape(current_time_info.split()[1])}.*'
    ]
    
    for pattern in time_patterns:
        match = re.search(pattern, report_content, re.MULTILINE | re.IGNORECASE)
        if match:
            end_pos = match.end()
            line_end = report_content.find('\n', end_pos)
            if line_end == -1:
                truncated_content = report_content[:end_pos].strip()
            else:
                truncated_content = report_content[:line_end].strip()
            
            logger.info(f"截断报告在时间信息行之后，截断位置: {end_pos}")
            return truncated_content
    
    logger.warning("未找到'分析基准时间'模式，返回原始报告内容")
    return report_content


def load_finr1_model(model_path="/root/code/Finance/FinR1"):
    """加载FinR1模型"""
    logger.info(f"{WAIT_ICON} Loading FinR1 model from {model_path}...")
    
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True
        )
        
        model.eval()
        logger.info(f"{SUCCESS_ICON} FinR1 model loaded successfully")
        return model, tokenizer
    
    except Exception as e:
        logger.error(f"{ERROR_ICON} Failed to load FinR1 model: {e}")
        raise e


def generate_report_with_finr1(model, tokenizer, prompt, max_new_tokens=5000):
    """使用FinR1模型生成报告"""
    
    try:
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=4096)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=0.5,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id
            )
        
        generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        if prompt in generated_text:
            report = generated_text[len(prompt):].strip()
        else:
            input_length = len(tokenizer.encode(prompt, return_tensors="pt")[0])
            output_length = len(outputs[0])
            
            if output_length > input_length:
                new_tokens = outputs[0][input_length:]
                report = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
            else:
                report = generated_text.strip()
        
        return report
    
    except Exception as e:
        logger.error(f"{ERROR_ICON} Error generating report with FinR1: {e}")
        raise e


def get_model_choice():
    """获取模型选择，默认选择API"""
    model_choice = os.getenv("USE_LOCAL_MODEL", "api").lower()
    return model_choice


def get_summary_model_type():
    """获取 summary agent 的模型类型，默认选择 API"""
    return os.getenv("SUMMARY_MODEL_TYPE", "api").lower()


def get_ollama_client():
    """获取 Ollama 客户端配置"""
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_model = os.getenv("OLLAMA_MODEL", "my_finetuned_qwen_q4")
    return ollama_base_url, ollama_model


async def summary_agent(state: AgentState) -> Dict[str, Any]:
    """
    整合基本面、技术面和估值分析的结果
    使用LLM生成最终的综合性报告
    """
    logger.info(f"{WAIT_ICON} SummaryAgent: Starting to consolidate analyses.")

    execution_logger = get_execution_logger()
    agent_name = "summary_agent"

    current_data = state.get("data", {})
    messages = state.get("messages", [])
    user_query = current_data.get("query", "")

    execution_logger.log_agent_start(agent_name, {
        "user_query": user_query,
        "available_analyses": {
            "fundamental": "fundamental_analysis" in current_data,
            "technical": "technical_analysis" in current_data,
            "value": "value_analysis" in current_data,
            "news": "news_analysis" in current_data
        },
        "input_data_keys": list(current_data.keys())
    })

    agent_start_time = time.time()

    fundamental_analysis = current_data.get(
        "fundamental_analysis", "Not available")
    technical_analysis = current_data.get(
        "technical_analysis", "Not available")
    value_analysis = current_data.get("value_analysis", "Not available")
    news_analysis = current_data.get("news_analysis", "Not available")

    errors = []
    if "fundamental_analysis_error" in current_data:
        errors.append(
            f"Fundamental Analysis Error: {current_data['fundamental_analysis_error']}")
    if "technical_analysis_error" in current_data:
        errors.append(
            f"Technical Analysis Error: {current_data['technical_analysis_error']}")
    if "value_analysis_error" in current_data:
        errors.append(
            f"Value Analysis Error: {current_data['value_analysis_error']}")
    if "news_analysis_error" in current_data:
        errors.append(
            f"News Analysis Error: {current_data['news_analysis_error']}")

    stock_code = current_data.get("stock_code")
    company_name = current_data.get("company_name")

    try:
        model_type = get_summary_model_type()
        logger.info(f"{WAIT_ICON} SummaryAgent: Using model type: {model_type}")

        current_time_info = current_data.get("current_time_info", "未知时间")
        current_date = current_data.get("current_date", "未知日期")

        system_prompt = f"""
        你是一位资深金融分析师，请撰写一份专业、精简的股票综合分析报告。
        
        **当前时间：{current_time_info}**
        **分析基准日期：{current_date}**
        
        你需要整合四种分析结果，生成一份结构清晰、内容精炼的报告：
        
        ---
        
        # [公司名称] (股票代码) 综合分析报告
        
        ## 执行摘要
        
        **分析基准日期：{current_date}**
        
        用2-3段话概括核心观点：公司基本面、估值水平、市场情绪、技术状态。
        明确给出：**总体评级**、**风险等级**、**预期回报**。
        
        ---
        
        ## 公司概况
        
        简洁介绍：核心业务、行业地位、战略方向。控制在100字以内。
        
        ---
        
        ## 基本面分析
        
        直接列出关键指标和分析，使用列表而非表格：
        
        ### 盈利能力
        - ROE、净利率、毛利率等核心指标
        - 业绩增长趋势
        
        ### 财务健康
        - 资产负债率变化
        - 现金流状况
        
        ---
        
        ## 技术分析
        
        **数据截止：{current_date}**
        
        ### 价格趋势
        - 长期趋势判断
        - 短期走势描述
        
        ### 技术指标
        - MACD、RSI、均线等关键指标
        - 支撑位与阻力位
        
        ---
        
        ## 估值分析
        
        直接呈现关键估值数据：
        - 市盈率、市净率水平
        - 与行业对比
        - 内在价值评估
        
        ---
        
        ## 新闻分析
        
        ### 市场情绪
        情感评分和舆情概况
        
        ### 关键事件
        近期重要新闻及其影响
        
        ---
        
        ## 综合评估
        
        用2-3段话总结：
        1. 各维度分析的一致性与分歧
        2. 核心投资逻辑
        3. 主要结论
        
        ---
        
        ## 风险因素
        
        用列表形式列出3-5条主要风险，每条一句话。
        
        ---
        
        ## 投资建议
        
        ### 总体策略
        一句话核心建议
        
        ### 操作建议
        - 目标价格区间
        - 建仓/止盈位置
        
        ### 适合投资者
        说明适合哪类投资者
        
        ---
        
        **输出要求：**
        1. 直接输出Markdown，不要代码块标记
        2. 精简表达，避免冗余
        3. 关键数据用**加粗**突出
        4. 每个章节控制在必要篇幅，不要为了填充而扩展
        5. 在报告末尾标注：分析基准时间：{current_time_info}
        """

        user_prompt = f"""
        Please create a comprehensive analysis report for {company_name} ({stock_code}) based on the following analyses.
        
        Original user query: {user_query}
        
        FUNDAMENTAL ANALYSIS:
        {fundamental_analysis}
        
        TECHNICAL ANALYSIS:
        {technical_analysis}
        
        VALUE ANALYSIS:
        {value_analysis}
        
        NEWS ANALYSIS:
        {news_analysis}
        
        {"ANALYSIS ISSUES:" if errors else ""}
        {". ".join(errors) if errors else ""}
        
        IMPORTANT: Your output MUST be in valid Markdown format with proper headings, bullet points, 
        and formatting. Include a clear recommendation section at the end.
        
        DO NOT include any code block markers like ```markdown or ``` in your output.
        Just write pure Markdown content directly.
        """

        if model_type == "gguf":
            logger.info(f"{WAIT_ICON} SummaryAgent: Using GGUF model...")
            
            model_config = {
                "model": "GGUF",
                "temperature": 0.5,
                "max_tokens": 2000,
                "model_path": os.getenv("GGUF_MODEL_PATH")
            }

            llm = load_gguf_model()
            
            gguf_prompt = f"""你是一位资深金融分析师，请根据以下分析结果撰写一份简洁的股票综合分析报告。

**公司**: {company_name or '未知'} ({stock_code or '未知'})
**日期**: {current_date}

**基本面分析**:
{fundamental_analysis[:800] if fundamental_analysis != "Not available" else "暂无数据"}

**技术面分析**:
{technical_analysis[:800] if technical_analysis != "Not available" else "暂无数据"}

**估值分析**:
{value_analysis[:800] if value_analysis != "Not available" else "暂无数据"}

**新闻分析**:
{news_analysis[:800] if news_analysis != "Not available" else "暂无数据"}

请输出一份包含以下章节的Markdown格式报告：
1. 执行摘要
2. 综合评估
3. 风险因素
4. 投资建议

直接输出报告内容，不要使用代码块标记。
"""

            llm_start_time = time.time()
            logger.info(f"{WAIT_ICON} Starting GGUF inference (this may take 1-3 minutes on CPU)...")

            final_report = generate_report_with_gguf(llm, gguf_prompt, max_tokens=2000)

            llm_execution_time = time.time() - llm_start_time
            logger.info(f"{SUCCESS_ICON} GGUF inference completed in {llm_execution_time:.1f} seconds")

        elif model_type == "ollama":
            logger.info(f"{WAIT_ICON} SummaryAgent: Using Ollama local model...")
            
            ollama_base_url, ollama_model = get_ollama_client()
            
            model_config = {
                "model": ollama_model,
                "temperature": 0.5,
                "max_tokens": 5000,
                "api_base": ollama_base_url
            }

            summary_prompt_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            llm = ChatOpenAI(
                model=ollama_model,
                api_key="ollama",
                base_url=ollama_base_url,
                temperature=0.5,
                max_tokens=5000
            )

            llm_start_time = time.time()

            llm_message = await llm.ainvoke(summary_prompt_messages)
            final_report = llm_message.content

            llm_execution_time = time.time() - llm_start_time

        elif model_type == "local":
            logger.info(f"{WAIT_ICON} SummaryAgent: Using local FinR1 model...")
            
            model_config = {
                "model": "FinR1",
                "temperature": 0.5,
                "max_tokens": 5000,
                "model_path": "/root/code/Finance/FinR1"
            }

            model, tokenizer = load_finr1_model()

            full_prompt = f"{system_prompt}\n\n{user_prompt}"

            llm_start_time = time.time()

            final_report = generate_report_with_finr1(model, tokenizer, full_prompt)

            llm_execution_time = time.time() - llm_start_time

        else:
            logger.info(f"{WAIT_ICON} SummaryAgent: Using OpenAI API...")
            
            api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY")
            base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
            model_name = os.getenv("OPENAI_COMPATIBLE_MODEL")

            if not all([api_key, base_url, model_name]):
                logger.error(
                    f"{ERROR_ICON} SummaryAgent: Missing OpenAI environment variables.")
                current_data["summary_error"] = "Missing OpenAI environment variables."

                execution_logger.log_agent_complete(agent_name, current_data, time.time(
                ) - agent_start_time, False, "Missing OpenAI environment variables")

                return {"data": current_data, "messages": messages}

            model_config = {
                "model": model_name,
                "temperature": 0.5,
                "max_tokens": 5000,
                "api_base": base_url
            }

            summary_prompt_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            logger.info(f"{WAIT_ICON} SummaryAgent: Creating ChatOpenAI with model {model_name}")
            llm = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.5,
                max_tokens=5000
            )

            llm_start_time = time.time()

            llm_message = await llm.ainvoke(summary_prompt_messages)
            final_report = llm_message.content

            llm_execution_time = time.time() - llm_start_time

        execution_logger.log_llm_interaction(
            agent_name=agent_name,
            interaction_type="summary_generation",
            input_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            output_content=final_report,
            model_config=model_config,
            execution_time=llm_execution_time
        )

        final_report = final_report.replace(
            "```markdown", "").replace("```", "").strip()
        
        final_report = truncate_report_at_baseline_time(final_report, current_time_info)

        logger.info(
            f"{SUCCESS_ICON} SummaryAgent: Final report generated for {company_name} ({stock_code}).")
        logger.debug(f"Final report preview: {final_report[:300]}...")

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        if not stock_code or stock_code == "Extracted from analysis":
            query_based_name = user_query.replace(
                " ", "_").replace("分析", "").strip()
            if not query_based_name:
                query_based_name = "financial_analysis"
            safe_file_prefix = f"report_{query_based_name}"
        else:
            safe_company_name = (company_name or "Unknown").replace(" ", "_").replace(".", "")
            if safe_company_name == "Unknown" or safe_company_name == "Unknown_Company" or safe_company_name == "Extracted_from_analysis":
                safe_company_name = user_query.replace(
                    " ", "_").replace("分析", "").strip()
                if not safe_company_name:
                    safe_company_name = "company"

            clean_stock_code = stock_code.replace("sh.", "").replace("sz.", "")
            safe_file_prefix = f"report_{safe_company_name}_{clean_stock_code}"

        report_filename = f"{safe_file_prefix}_{timestamp}.md"

        reports_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "reports")
        os.makedirs(reports_dir, exist_ok=True)

        report_path = os.path.join(reports_dir, report_filename)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(final_report)

        logger.info(
            f"{SUCCESS_ICON} SummaryAgent: Report saved to {report_path}")

        current_data["final_report"] = final_report
        current_data["report_path"] = report_path

        total_execution_time = time.time() - agent_start_time
        execution_logger.log_agent_complete(agent_name, {
            "final_report_length": len(final_report),
            "report_path": report_path,
            "report_preview": final_report,
            "llm_execution_time": llm_execution_time,
            "total_execution_time": total_execution_time
        }, total_execution_time, True)

        return {"data": current_data, "messages": messages}

    except Exception as e:
        logger.error(
            f"{ERROR_ICON} SummaryAgent: Error generating final report: {e}", exc_info=True)
        current_data["summary_error"] = f"Error generating final report: {e}"

        error_report = f"""
        # Analysis Report for {company_name} ({stock_code})
        
        **Error encountered during report generation**: {e}
        
        ## Available Analysis Fragments:
        
        - Fundamental Analysis: {"Available" if fundamental_analysis != "Not available" else "Not available"}
        - Technical Analysis: {"Available" if technical_analysis != "Not available" else "Not available"}
        - Value Analysis: {"Available" if value_analysis != "Not available" else "Not available"}
        - News Analysis: {"Available" if news_analysis != "Not available" else "Not available"}
        
        Please review the individual analyses directly for more information.
        """
        current_data["final_report"] = error_report

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        if not stock_code or stock_code == "Extracted from analysis":
            query_based_name = user_query.replace(
                " ", "_").replace("分析", "").strip()
            if not query_based_name:
                query_based_name = "financial_analysis"
            safe_file_prefix = f"error_report_{query_based_name}"
        else:
            safe_company_name = (company_name or "Unknown").replace(" ", "_").replace(".", "")
            if safe_company_name == "Unknown" or safe_company_name == "Unknown_Company" or safe_company_name == "Extracted_from_analysis":
                safe_company_name = user_query.replace(
                    " ", "_").replace("分析", "").strip()
                if not safe_company_name:
                    safe_company_name = "company"

            clean_stock_code = stock_code.replace("sh.", "").replace("sz.", "")
            safe_file_prefix = f"error_report_{safe_company_name}_{clean_stock_code}"

        report_filename = f"{safe_file_prefix}_{timestamp}.md"

        reports_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "reports")
        os.makedirs(reports_dir, exist_ok=True)

        report_path = os.path.join(reports_dir, report_filename)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(error_report)

        logger.info(
            f"{ERROR_ICON} SummaryAgent: Error report saved to {report_path}")
        current_data["report_path"] = report_path

        execution_logger.log_agent_complete(
            agent_name, current_data, time.time() - agent_start_time, False, str(e))

        return {"data": current_data, "messages": messages}


async def test_summary_agent():
    """汇总 Agent的测试函数"""
    from src.utils.state_definition import AgentState

    test_state = AgentState(
        messages=[],
        data={
            "query": "分析嘉友国际",
            "stock_code": "603871",
            "company_name": "嘉友国际",
            "fundamental_analysis": "嘉友国际基本面分析：公司主营业务为跨境物流、供应链贸易以及供应链增值服务。财务状况良好，负债率较低，现金流充裕。近年来业绩稳步增长，毛利率保持在行业较高水平。",
            "technical_analysis": "嘉友国际技术分析：短期内股价处于上升通道，突破了200日均线。RSI指标显示股票尚未达到超买区域。MACD指标呈现多头形态，成交量有所放大，支持价格继续上行。",
            "value_analysis": "嘉友国际估值分析：当前市盈率为15倍，低于行业平均水平。市净率为1.8倍，处于合理区间。与同行业公司相比，嘉友国际的估值较为合理，具有一定的投资价值。",
            "news_analysis": "嘉友国际新闻分析：近期公司发布了2023年业绩预告，预计净利润同比增长15-25%，超出市场预期。同时，公司宣布与多家国际物流巨头达成战略合作，市场反应积极。分析师普遍上调了目标价，市场情绪偏向乐观。"
        },
        metadata={}
    )

    result = await summary_agent(test_state)
    print("Summary Report:")
    print(result.get("data", {}).get("final_report", "No report generated"))
    print(
        f"Report saved to: {result.get('data', {}).get('report_path', 'Not saved')}")

    return result

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_summary_agent())