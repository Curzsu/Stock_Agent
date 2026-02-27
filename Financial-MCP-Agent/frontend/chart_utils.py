"""
Chart data extraction and generation utilities for financial analysis reports
"""
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ChartData:
    chart_type: str
    title: str
    data: Dict[str, Any]
    config: Dict[str, Any]


class FinancialDataExtractor:
    """Extract structured data from analysis text for chart generation"""
    
    @staticmethod
    def extract_financial_metrics(text: str) -> Dict[str, Any]:
        """Extract key financial metrics from fundamental analysis"""
        metrics = {}
        
        roe_pattern = r'(?:ROE|净资产收益率)[：:]\s*([\d.]+)%?'
        roe_match = re.search(roe_pattern, text, re.IGNORECASE)
        if roe_match:
            metrics['roe'] = float(roe_match.group(1))
        
        pe_pattern = r'(?:市盈率|PE)[：:]\s*([\d.]+)'
        pe_match = re.search(pe_pattern, text, re.IGNORECASE)
        if pe_match:
            metrics['pe_ratio'] = float(pe_match.group(1))
        
        pb_pattern = r'(?:市净率|PB)[：:]\s*([\d.]+)'
        pb_match = re.search(pb_pattern, text, re.IGNORECASE)
        if pb_match:
            metrics['pb_ratio'] = float(pb_match.group(1))
        
        gross_margin_pattern = r'(?:毛利率)[：:]\s*([\d.]+)%?'
        gross_match = re.search(gross_margin_pattern, text, re.IGNORECASE)
        if gross_match:
            metrics['gross_margin'] = float(gross_match.group(1))
        
        net_margin_pattern = r'(?:净利率|净利润率)[：:]\s*([\d.]+)%?'
        net_match = re.search(net_margin_pattern, text, re.IGNORECASE)
        if net_match:
            metrics['net_margin'] = float(net_match.group(1))
        
        debt_ratio_pattern = r'(?:资产负债率|负债率)[：:]\s*([\d.]+)%?'
        debt_match = re.search(debt_ratio_pattern, text, re.IGNORECASE)
        if debt_match:
            metrics['debt_ratio'] = float(debt_match.group(1))
        
        revenue_growth_pattern = r'(?:营收增长率|收入增长)[：:]\s*(-?[\d.]+)%?'
        rev_match = re.search(revenue_growth_pattern, text, re.IGNORECASE)
        if rev_match:
            metrics['revenue_growth'] = float(rev_match.group(1))
        
        profit_growth_pattern = r'(?:净利润增长率|利润增长)[：:]\s*(-?[\d.]+)%?'
        profit_match = re.search(profit_growth_pattern, text, re.IGNORECASE)
        if profit_match:
            metrics['profit_growth'] = float(profit_match.group(1))
        
        return metrics
    
    @staticmethod
    def extract_technical_indicators(text: str) -> Dict[str, Any]:
        """Extract technical indicators from analysis"""
        indicators = {}
        
        rsi_pattern = r'(?:RSI|相对强弱指数)[：:]\s*([\d.]+)'
        rsi_match = re.search(rsi_pattern, text, re.IGNORECASE)
        if rsi_match:
            indicators['rsi'] = float(rsi_match.group(1))
        
        macd_pattern = r'(?:MACD)[：:]\s*(-?[\d.]+)'
        macd_match = re.search(macd_pattern, text, re.IGNORECASE)
        if macd_match:
            indicators['macd'] = float(macd_match.group(1))
        
        ma_patterns = [
            (r'(?:MA5|5日均线)[：:]\s*([\d.]+)', 'ma5'),
            (r'(?:MA10|10日均线)[：:]\s*([\d.]+)', 'ma10'),
            (r'(?:MA20|20日均线)[：:]\s*([\d.]+)', 'ma20'),
            (r'(?:MA60|60日均线)[：:]\s*([\d.]+)', 'ma60'),
        ]
        for pattern, key in ma_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                indicators[key] = float(match.group(1))
        
        return indicators
    
    @staticmethod
    def extract_news_sentiment(text: str) -> Dict[str, Any]:
        """Extract sentiment analysis from news"""
        sentiment = {}
        
        positive_pattern = r'(?:正面|积极|利好)[：:]\s*(\d+)'
        positive_match = re.search(positive_pattern, text, re.IGNORECASE)
        if positive_match:
            sentiment['positive_count'] = int(positive_match.group(1))
        
        negative_pattern = r'(?:负面|消极|利空)[：:]\s*(\d+)'
        negative_match = re.search(negative_pattern, text, re.IGNORECASE)
        if negative_match:
            sentiment['negative_count'] = int(negative_match.group(1))
        
        neutral_pattern = r'(?:中性|持平)[：:]\s*(\d+)'
        neutral_match = re.search(neutral_pattern, text, re.IGNORECASE)
        if neutral_match:
            sentiment['neutral_count'] = int(neutral_match.group(1))
        
        sentiment_score_pattern = r'(?:情感评分|情绪评分)[：:]\s*([\d.]+)'
        score_match = re.search(sentiment_score_pattern, text, re.IGNORECASE)
        if score_match:
            sentiment['sentiment_score'] = float(score_match.group(1))
        
        risk_level_pattern = r'(?:风险等级|风险评估)[：:]\s*(\d+)'
        risk_match = re.search(risk_level_pattern, text, re.IGNORECASE)
        if risk_match:
            sentiment['risk_level'] = int(risk_match.group(1))
        
        return sentiment
    
    @staticmethod
    def extract_valuation_comparison(text: str) -> Dict[str, Any]:
        """Extract valuation comparison data"""
        comparison = {}
        
        industry_pe_pattern = r'(?:行业.*?市盈率|行业PE)[：:]\s*([\d.]+)'
        industry_pe_match = re.search(industry_pe_pattern, text, re.IGNORECASE)
        if industry_pe_match:
            comparison['industry_pe'] = float(industry_pe_match.group(1))
        
        company_pe_pattern = r'(?:公司.*?市盈率|当前PE|PE\(TTM\))[：:]\s*([\d.]+)'
        company_pe_match = re.search(company_pe_pattern, text, re.IGNORECASE)
        if company_pe_match:
            comparison['company_pe'] = float(company_pe_match.group(1))
        
        industry_pb_pattern = r'(?:行业.*?市净率|行业PB)[：:]\s*([\d.]+)'
        industry_pb_match = re.search(industry_pb_pattern, text, re.IGNORECASE)
        if industry_pb_match:
            comparison['industry_pb'] = float(industry_pb_match.group(1))
        
        company_pb_pattern = r'(?:公司.*?市净率|当前PB)[：:]\s*([\d.]+)'
        company_pb_match = re.search(company_pb_pattern, text, re.IGNORECASE)
        if company_pb_match:
            comparison['company_pb'] = float(company_pb_match.group(1))
        
        return comparison


class ChartGenerator:
    """Generate chart configurations for Chainlit Plotly charts"""
    
    @staticmethod
    def create_financial_metrics_chart(metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Create a bar chart for financial metrics"""
        labels = []
        values = []
        colors = []
        
        metric_config = {
            'roe': ('ROE (%)', '#4CAF50'),
            'gross_margin': ('毛利率 (%)', '#2196F3'),
            'net_margin': ('净利率 (%)', '#9C27B0'),
            'debt_ratio': ('资产负债率 (%)', '#FF9800'),
            'revenue_growth': ('营收增长 (%)', '#00BCD4'),
            'profit_growth': ('利润增长 (%)', '#E91E63'),
        }
        
        for key, (label, color) in metric_config.items():
            if key in metrics and metrics[key] is not None:
                labels.append(label)
                values.append(metrics[key])
                colors.append(color)
        
        if not labels:
            return None
        
        return {
            "data": [{
                "type": "bar",
                "x": labels,
                "y": values,
                "marker": {"color": colors},
                "text": [f"{v:.2f}%" for v in values],
                "textposition": "outside",
            }],
            "layout": {
                "title": "📊 关键财务指标",
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
                "font": {"color": "#333"},
                "margin": {"l": 50, "r": 50, "t": 50, "b": 80},
                "yaxis": {"title": "百分比 (%)"},
                "showlegend": False,
            }
        }
    
    @staticmethod
    def create_valuation_comparison_chart(comparison: Dict[str, Any]) -> Dict[str, Any]:
        """Create a comparison chart for valuation metrics"""
        if not comparison:
            return None
        
        categories = []
        company_values = []
        industry_values = []
        
        if 'company_pe' in comparison and 'industry_pe' in comparison:
            categories.append('市盈率 (PE)')
            company_values.append(comparison['company_pe'])
            industry_values.append(comparison['industry_pe'])
        
        if 'company_pb' in comparison and 'industry_pb' in comparison:
            categories.append('市净率 (PB)')
            company_values.append(comparison['company_pb'])
            industry_values.append(comparison['industry_pb'])
        
        if not categories:
            return None
        
        return {
            "data": [
                {
                    "type": "bar",
                    "name": "公司",
                    "x": categories,
                    "y": company_values,
                    "marker": {"color": "#2196F3"},
                },
                {
                    "type": "bar",
                    "name": "行业平均",
                    "x": categories,
                    "y": industry_values,
                    "marker": {"color": "#FF9800"},
                }
            ],
            "layout": {
                "title": "💰 估值对比分析",
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
                "font": {"color": "#333"},
                "margin": {"l": 50, "r": 50, "t": 50, "b": 80},
                "yaxis": {"title": "倍数"},
                "barmode": "group",
                "showlegend": True,
                "legend": {"orientation": "h", "y": 1.1},
            }
        }
    
    @staticmethod
    def create_sentiment_pie_chart(sentiment: Dict[str, Any]) -> Dict[str, Any]:
        """Create a pie chart for news sentiment distribution"""
        labels = []
        values = []
        colors = []
        
        if 'positive_count' in sentiment:
            labels.append('正面')
            values.append(sentiment['positive_count'])
            colors.append('#4CAF50')
        
        if 'neutral_count' in sentiment:
            labels.append('中性')
            values.append(sentiment['neutral_count'])
            colors.append('#9E9E9E')
        
        if 'negative_count' in sentiment:
            labels.append('负面')
            values.append(sentiment['negative_count'])
            colors.append('#F44336')
        
        if not labels:
            return None
        
        return {
            "data": [{
                "type": "pie",
                "labels": labels,
                "values": values,
                "marker": {"colors": colors},
                "hole": 0.4,
                "textinfo": "label+percent",
                "textposition": "outside",
            }],
            "layout": {
                "title": "📰 新闻情感分布",
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
                "font": {"color": "#333"},
                "margin": {"l": 50, "r": 50, "t": 50, "b": 50},
                "showlegend": False,
            }
        }
    
    @staticmethod
    def create_risk_gauge(risk_level: int) -> Dict[str, Any]:
        """Create a gauge chart for risk level"""
        if risk_level is None:
            return None
        
        risk_labels = ['极低风险', '低风险', '中等风险', '高风险', '极高风险']
        risk_colors = ['#4CAF50', '#8BC34A', '#FFEB3B', '#FF9800', '#F44336']
        
        return {
            "data": [{
                "type": "indicator",
                "mode": "gauge+number",
                "value": risk_level,
                "gauge": {
                    "axis": {"range": [1, 5], "tickmode": "array", "tickvals": [1, 2, 3, 4, 5]},
                    "bar": {"color": risk_colors[min(risk_level - 1, 4)]},
                    "steps": [
                        {"range": [1, 2], "color": "#E8F5E9"},
                        {"range": [2, 3], "color": "#F1F8E9"},
                        {"range": [3, 4], "color": "#FFFDE7"},
                        {"range": [4, 5], "color": "#FFF3E0"},
                    ],
                },
                "title": {"text": f"风险等级: {risk_labels[min(risk_level - 1, 4)]}"},
            }],
            "layout": {
                "title": "⚠️ 投资风险评估",
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
                "font": {"color": "#333"},
                "margin": {"l": 50, "r": 50, "t": 80, "b": 50},
            }
        }
    
    @staticmethod
    def create_technical_radar(indicators: Dict[str, Any]) -> Dict[str, Any]:
        """Create a radar chart for technical indicators"""
        if not indicators:
            return None
        
        categories = []
        values = []
        
        if 'rsi' in indicators:
            categories.append('RSI')
            rsi_normalized = min(indicators['rsi'] / 100 * 10, 10)
            values.append(rsi_normalized)
        
        if 'macd' in indicators:
            categories.append('MACD')
            macd_score = min(abs(indicators['macd']) / 10, 10) if indicators['macd'] else 5
            values.append(macd_score)
        
        if 'ma5' in indicators and 'ma20' in indicators:
            categories.append('均线趋势')
            ma_diff = (indicators['ma5'] - indicators['ma20']) / indicators['ma20'] * 100
            ma_score = min(abs(ma_diff) + 5, 10)
            values.append(ma_score)
        
        if not categories:
            return None
        
        values.append(values[0])
        categories.append(categories[0])
        
        return {
            "data": [{
                "type": "scatterpolar",
                "r": values,
                "theta": categories,
                "fill": "toself",
                "fillcolor": "rgba(33, 150, 243, 0.3)",
                "line": {"color": "#2196F3"},
            }],
            "layout": {
                "title": "📈 技术指标雷达",
                "paper_bgcolor": "rgba(0,0,0,0)",
                "plot_bgcolor": "rgba(0,0,0,0)",
                "font": {"color": "#333"},
                "margin": {"l": 50, "r": 50, "t": 50, "b": 50},
                "polar": {
                    "radialaxis": {"visible": True, "range": [0, 10]},
                },
                "showlegend": False,
            }
        }


def generate_charts_from_analysis(
    fundamental_analysis: str,
    technical_analysis: str,
    value_analysis: str,
    news_analysis: str
) -> List[Dict[str, Any]]:
    """Generate all charts from analysis results"""
    charts = []
    
    financial_metrics = FinancialDataExtractor.extract_financial_metrics(
        fundamental_analysis + " " + value_analysis
    )
    if financial_metrics:
        chart = ChartGenerator.create_financial_metrics_chart(financial_metrics)
        if chart:
            charts.append(chart)
    
    valuation_comparison = FinancialDataExtractor.extract_valuation_comparison(value_analysis)
    if valuation_comparison:
        chart = ChartGenerator.create_valuation_comparison_chart(valuation_comparison)
        if chart:
            charts.append(chart)
    
    sentiment = FinancialDataExtractor.extract_news_sentiment(news_analysis)
    if sentiment:
        chart = ChartGenerator.create_sentiment_pie_chart(sentiment)
        if chart:
            charts.append(chart)
        
        if 'risk_level' in sentiment:
            chart = ChartGenerator.create_risk_gauge(sentiment['risk_level'])
            if chart:
                charts.append(chart)
    
    technical_indicators = FinancialDataExtractor.extract_technical_indicators(technical_analysis)
    if technical_indicators:
        chart = ChartGenerator.create_technical_radar(technical_indicators)
        if chart:
            charts.append(chart)
    
    return charts


def extract_summary_metrics(
    fundamental_analysis: str,
    technical_analysis: str,
    value_analysis: str,
    news_analysis: str
) -> Dict[str, Any]:
    """Extract summary metrics for display"""
    metrics = {}
    
    financial = FinancialDataExtractor.extract_financial_metrics(
        fundamental_analysis + " " + value_analysis
    )
    if financial:
        metrics.update(financial)
    
    technical = FinancialDataExtractor.extract_technical_indicators(technical_analysis)
    if technical:
        metrics.update(technical)
    
    sentiment = FinancialDataExtractor.extract_news_sentiment(news_analysis)
    if sentiment:
        metrics.update(sentiment)
    
    valuation = FinancialDataExtractor.extract_valuation_comparison(value_analysis)
    if valuation:
        metrics.update(valuation)
    
    return metrics