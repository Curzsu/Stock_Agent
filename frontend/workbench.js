(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FinexWorkbench = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const AGENTS = ['fundamental', 'technical', 'value', 'news', 'summary'];
  const WAITING_SUMMARIES = {
    fundamental: '等待研究任务进入队列。',
    technical: '等待研究任务进入队列。',
    value: '等待研究任务进入队列。',
    news: '等待研究任务进入队列。',
    summary: '四路研究完成后，将在此生成综合结论。',
  };
  const RUNNING_SUMMARIES = {
    fundamental: '正在核对财务质量、盈利能力与经营韧性。',
    technical: '正在核对价格趋势、成交动能与关键压力区。',
    value: '正在计算历史估值分位，并与行业水平进行比较。',
    news: '正在检索公开信息、重要事件与潜在风险信号。',
    summary: '正在交叉验证四路研究，并生成综合研判。',
  };

  function normalizeAgentDetails(input = {}) {
    return Object.fromEntries(AGENTS.map((key) => [key, {
      status: 'waiting',
      summary: '',
      error: null,
      result_available: false,
      execution_time_ms: null,
      ...(input[key] || {}),
    }]));
  }

  function hasRunningAgents(payload = {}) {
    const progress = payload.progress || {};
    const details = payload.agent_details || {};
    return AGENTS.some(
      (key) => progress[key] === 'running' || (details[key] || {}).status === 'running',
    );
  }

  function derivePhase(payload = {}) {
    const running = hasRunningAgents(payload);
    if (payload.status === 'completed' && !running) return 'completed';
    if (payload.status === 'degraded' && !running) return 'degraded';
    if (payload.status === 'error') return 'error';
    const values = payload.progress || {};
    if (values.summary === 'running') return 'summarizing';
    if (running && ['completed', 'degraded'].includes(payload.status)) return 'running';
    if (AGENTS.some((key) => values[key] === 'completed')) return 'partial';
    return payload.status === 'running' || running ? 'running' : 'starting';
  }

  function agentSummaryForStatus(agentKey, detail = {}) {
    if (detail.summary) return detail.summary;
    if (detail.status === 'failed' && detail.error) return detail.error;
    if (detail.status === 'running') return RUNNING_SUMMARIES[agentKey] || '正在进行研究。';
    return WAITING_SUMMARIES[agentKey] || '等待研究任务进入队列。';
  }

  function buildMarketSeries(payload = {}) {
    const candles = Array.isArray(payload.candles) ? payload.candles : [];
    return {
      candles: candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
      volume: candles.map(({ time, volume, close, open }) => ({
        time,
        value: Number(volume || 0),
        color: close >= open ? '#557a66' : '#a0473e',
      })),
      ma5: candles
        .filter((row) => row.ma5 != null)
        .map(({ time, ma5 }) => ({ time, value: ma5 })),
      ma20: candles
        .filter((row) => row.ma20 != null)
        .map(({ time, ma20 }) => ({ time, value: ma20 })),
    };
  }

  function completedResultKeys(progress = {}, seen = new Set()) {
    return AGENTS.filter(
      (key) => key !== 'summary' && progress[key] === 'completed' && !seen.has(key),
    );
  }

  function nextRequests(previousProgress = {}, payload = {}) {
    const terminal = (payload.status === 'completed' || payload.status === 'degraded')
      && !hasRunningAgents(payload);
    if (terminal) return { partial: false, result: true };
    const progress = payload.progress || {};
    const partial = AGENTS.some(
      (key) => key !== 'summary'
        && progress[key] === 'completed'
        && previousProgress[key] !== 'completed',
    );
    return { partial, result: false };
  }

  function canRetryAgent(payload = {}, agentStatus = 'waiting', agentKey = '') {
    const terminal = payload.status === 'completed' || payload.status === 'degraded'
      || (payload.status === 'error' && agentKey === 'summary');
    return terminal && !hasRunningAgents(payload) && agentStatus === 'failed';
  }

  function resolveChartSize(width, height) {
    return {
      width: Number(width) > 0 ? Number(width) : 640,
      height: Number(height) > 0 ? Number(height) : 430,
    };
  }

  function formatAnalysisMarkdown(value) {
    const escape = (text) => String(text)
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
    // Parse literals before emphasis so code and link destinations stay intact.
    const inline = (text) => {
      const token = /(`+)([\s\S]*?)\1|\[([^\]\n]+)\]\(([^\s()]*(?:\([^\s()]*\)[^\s()]*)*)\)/g;
      const emphasis = (part) => escape(part).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      let html = '', offset = 0;
      for (const match of text.matchAll(token)) {
        html += emphasis(text.slice(offset, match.index));
        if (match[1]) html += `<code>${escape(match[2])}</code>`;
        else if (/^(?:https?:\/\/|mailto:|#)/i.test(match[4])) {
          html += `<a href="${escape(match[4])}" target="_blank" rel="noopener noreferrer">${emphasis(match[3])}</a>`;
        } else html += emphasis(match[3]);
        offset = match.index + match[0].length;
      }
      return html + emphasis(text.slice(offset));
    };
    const cells = (line) => {
      const parts = [];
      let cell = '', code = '';
      for (let i = 0; i < line.length; i++) {
        if (line[i] === '\\' && line[i + 1] === '|') { cell += '|'; i++; }
        else if (line[i] === '`') {
          const ticks = line.slice(i).match(/^`+/)[0];
          code = code === ticks ? '' : (code || ticks);
          cell += ticks;
          i += ticks.length - 1;
        } else if (line[i] === '|' && !code) { parts.push(cell.trim()); cell = ''; }
        else cell += line[i];
      }
      parts.push(cell.trim());
      if (!parts[0]) parts.shift();
      if (!parts[parts.length - 1]) parts.pop();
      return parts;
    };
    const lines = String(value || '').replace(/\r\n?/g, '\n').split('\n');
    const listItem = (line) => line.match(/^(\s*)([-+*]|\d+[.)])\s+(.*)$/);
    const isRule = (line) => /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);
    const isTable = (index) => {
      if (!lines[index]?.includes('|') || !lines[index + 1]?.includes('|')) return false;
      const header = cells(lines[index]), separators = cells(lines[index + 1]);
      return header.length > 0 && header.length === separators.length
        && separators.every((cell) => /^:?-{3,}:?$/.test(cell));
    };
    const isBlock = (index) => /^(?: {0,3}#{1,6}\s|\s*>| {0,3}(?:`{3,}|~{3,})| {0,3}\[TOC\]\s*$)/i.test(lines[index])
      || isRule(lines[index]) || listItem(lines[index]) || isTable(index);
    let index = 0;
    const renderList = (indent) => {
      const first = listItem(lines[index]);
      const ordered = /^\d/.test(first[2]);
      const tag = ordered ? 'ol' : 'ul';
      const start = ordered && parseInt(first[2], 10) !== 1 ? ` start="${parseInt(first[2], 10)}"` : '';
      let html = `<${tag}${start}>`;
      while (index < lines.length) {
        const item = listItem(lines[index]);
        if (!item || item[1].length !== indent || /^\d/.test(item[2]) !== ordered) break;
        html += `<li>${inline(item[3])}`;
        index++;
        while (index < lines.length && lines[index].trim()) {
          const next = listItem(lines[index]);
          if (next && next[1].length > indent) html += renderList(next[1].length);
          else if (!next && /^\s+/.test(lines[index]) && !isBlock(index)) {
            html += `<br>${inline(lines[index++].trim())}`;
          } else break;
        }
        html += '</li>';
        if (!lines[index]?.trim() && listItem(lines[index + 1] || '')?.[1].length === indent) index++;
      }
      return `${html}</${tag}>`;
    };
    let html = '';
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim() || /^ {0,3}\[TOC\]\s*$/i.test(line)) { index++; continue; }
      const fence = line.match(/^ {0,3}(`{3,}|~{3,})/);
      if (fence) {
        const code = [];
        index++;
        while (index < lines.length) {
          const close = lines[index].match(/^ {0,3}(`{3,}|~{3,})\s*$/);
          if (close && close[1][0] === fence[1][0] && close[1].length >= fence[1].length) { index++; break; }
          code.push(lines[index++]);
        }
        html += `<pre><code>${escape(code.join('\n'))}</code></pre>`;
      } else if (/^ {0,3}#{1,6}\s+\S/.test(line)) {
        const [, marks, text] = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
        const level = Math.min(4, marks.length + 1);
        html += `<h${level}>${inline(text === '一页摘要' ? '摘要' : text)}</h${level}>`;
        index++;
      } else if (isTable(index)) {
        const header = cells(line);
        const alignment = cells(lines[index + 1]).map((cell) => cell.endsWith(':') ? (cell.startsWith(':') ? 'center' : 'right') : '');
        const attr = (column) => alignment[column] ? ` class="align-${alignment[column]}"` : '';
        html += '<div class="report-table-scroll" role="region" aria-label="报告数据表，可横向滚动" tabindex="0"><table><thead><tr>';
        html += header.map((cell, column) => `<th scope="col"${attr(column)}>${inline(cell)}</th>`).join('');
        html += '</tr></thead><tbody>';
        index += 2;
        while (index < lines.length && lines[index].trim() && lines[index].includes('|') && !isRule(lines[index])) {
          const row = cells(lines[index++]);
          html += '<tr>' + header.map((_, column) => `<td${attr(column)}>${inline(row[column] || '')}</td>`).join('') + '</tr>';
        }
        html += '</tbody></table></div>';
      } else if (isRule(line)) {
        html += '<hr>';
        index++;
      } else if (/^\s*>/.test(line)) {
        const quote = [];
        while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, ''));
        html += `<blockquote>${formatAnalysisMarkdown(quote.join('\n'))}</blockquote>`;
      } else if (listItem(line)) {
        html += renderList(listItem(line)[1].length);
      } else {
        const paragraph = [inline(line.trim())];
        index++;
        while (index < lines.length && lines[index].trim() && !isBlock(index)) paragraph.push(inline(lines[index++].trim()));
        html += `<p>${paragraph.join('<br>')}</p>`;
      }
    }
    return html;
  }

  function stripLeadingMarkdownHeading(value) {
    return String(value == null ? '' : value)
      .replace(/^\s*#{1,6}\s+[^\r\n]+(?:\r?\n\s*)?/, '')
      .trim();
  }

  function createController(root, options = {}) {
    if (!root || typeof root.querySelector !== 'function') {
      throw new TypeError('A workbench root element is required');
    }

    const agentCards = Object.fromEntries(AGENTS.map((key) => [
      key,
      root.querySelector(`[data-agent="${key}"]`),
    ]));
    const runningState = root.querySelector('#workbenchRunningState');
    const report = root.querySelector('#workbenchReport');
    const statusText = root.querySelector('#statusText');
    const stockTitle = root.querySelector('#analyzingStock');
    const completedCount = root.querySelector('#completedCount');
    const marketChartElement = root.querySelector('#workbenchMarketChart');
    const marketMetrics = root.querySelector('#marketMetrics');
    const marketTradeDate = root.querySelector('#marketTradeDate');
    const marketQuote = root.querySelector('#marketQuote');
    const reportContent = root.querySelector('#reportContent');
    const reportNavigation = root.querySelector('#reportNavigation');
    const cleanup = [];
    let chart = null;
    let chartSeries = null;
    let partialResults = {};
    let chartResizeObserver = null;

    const ResizeObserverCtor = root.ownerDocument.defaultView
      && root.ownerDocument.defaultView.ResizeObserver;
    if (marketChartElement && ResizeObserverCtor) {
      chartResizeObserver = new ResizeObserverCtor(() => {
        if (!chart) return;
        const size = resolveChartSize(
          marketChartElement.clientWidth,
          marketChartElement.clientHeight,
        );
        chart.applyOptions(size);
      });
      chartResizeObserver.observe(marketChartElement);
    }

    const phaseLabels = {
      starting: '正在识别股票标的',
      running: '五位分析师已进入研究流程',
      partial: '阶段研究结果正在陆续返回',
      summarizing: '正在生成综合研判',
      completed: '研究报告已完成',
      degraded: '报告已完成，部分维度待重试',
      error: '分析未完成',
    };
    const agentStatusLabels = {
      waiting: '等待',
      running: '分析中',
      completed: '已完成',
      failed: '需要重试',
    };
    function setText(element, value) {
      if (element) element.textContent = value == null ? '' : String(value);
    }

    function reset(stockLabel) {
      partialResults = {};
      setText(stockTitle, stockLabel || '股票标的');
      setText(statusText, phaseLabels.starting);
      setText(completedCount, '0 / 5 已完成');
      if (runningState) runningState.hidden = false;
      if (report) report.hidden = true;
      AGENTS.forEach((key) => {
        const card = agentCards[key];
        if (!card) return;
        card.dataset.status = 'waiting';
        card.classList.remove('active', 'complete');
        setText(card.querySelector('.status-text'), key === 'summary' ? '等待前置研究' : '等待');
        setText(card.querySelector('.agent-summary'), WAITING_SUMMARIES[key]);
        const retry = card.querySelector('.agent-retry');
        if (retry) retry.hidden = true;
      });
      renderMarket({ ok: false, loading: true });
    }

    function updateStatus(payload = {}) {
      const phase = derivePhase(payload);
      root.dataset.phase = phase;
      setText(statusText, payload.current_task || phaseLabels[phase] || phaseLabels.running);
      const details = normalizeAgentDetails(payload.agent_details);
      let completed = 0;
      AGENTS.forEach((key) => {
        const card = agentCards[key];
        if (!card) return;
        const detail = details[key];
        const fallbackStatus = (payload.progress || {})[key];
        const status = detail.status === 'waiting' && fallbackStatus ? fallbackStatus : detail.status;
        card.dataset.status = status;
        card.classList.toggle('active', status === 'running');
        card.classList.toggle('complete', status === 'completed');
        if (status === 'completed') completed += 1;
        const elapsed = detail.execution_time_ms == null
          ? ''
          : ` · ${Math.max(1, Math.round(detail.execution_time_ms / 1000))} 秒`;
        const label = key === 'summary' && status === 'waiting'
          ? '等待前置研究'
          : (agentStatusLabels[status] || status);
        setText(card.querySelector('.status-text'), `${label}${elapsed}`);
        const summary = agentSummaryForStatus(key, { ...detail, status });
        setText(card.querySelector('.agent-summary'), summary);
        const retry = card.querySelector('.agent-retry');
        if (retry) retry.hidden = !canRetryAgent(payload, status, key);
      });
      setText(completedCount, `${completed} / 5 已完成`);
    }

    function updatePartialResults(results = {}) {
      partialResults = { ...partialResults, ...results };
      Object.entries({
        fundamental: 'fundamental_analysis',
        technical: 'technical_analysis',
        value: 'value_analysis',
        news: 'news_analysis',
        summary: 'final_report',
      }).forEach(([agent, key]) => {
        const card = agentCards[agent];
        if (card && partialResults[key]) card.dataset.resultAvailable = 'true';
      });
      return { ...partialResults };
    }

    function renderMarket(payload = {}) {
      if (!marketChartElement) return;
      if (payload.loading) {
        marketChartElement.replaceChildren();
        const loading = root.ownerDocument.createElement('div');
        loading.className = 'market-loading';
        const spinner = root.ownerDocument.createElement('i');
        const label = root.ownerDocument.createElement('span');
        label.textContent = '识别股票后载入真实 K 线';
        loading.append(spinner, label);
        marketChartElement.append(loading);
        setText(marketTradeDate, '等待标的识别');
        return;
      }
      if (!payload.ok) {
        if (chart && typeof chart.remove === 'function') chart.remove();
        chart = null;
        chartSeries = null;
        marketChartElement.replaceChildren();
        const unavailable = root.ownerDocument.createElement('div');
        unavailable.className = 'market-loading market-unavailable';
        const label = root.ownerDocument.createElement('span');
        label.textContent = '行情数据暂不可用';
        unavailable.append(label);
        marketChartElement.append(unavailable);
        setText(marketTradeDate, '最近交易日数据');
        return;
      }

      const series = buildMarketSeries(payload);
      const chartLibrary = options.LightweightCharts
        || (root.ownerDocument.defaultView && root.ownerDocument.defaultView.LightweightCharts);
      if (chartLibrary && typeof chartLibrary.createChart === 'function') {
        if (chart && typeof chart.remove === 'function') chart.remove();
        marketChartElement.replaceChildren();
        const chartSize = resolveChartSize(
          marketChartElement.clientWidth,
          marketChartElement.clientHeight,
        );
        chart = chartLibrary.createChart(marketChartElement, {
          ...chartSize,
          layout: { background: { color: 'transparent' }, textColor: '#74695b', fontFamily: '"DM Sans", "FINEX Round", sans-serif' },
          grid: { vertLines: { color: 'rgba(83,64,41,.06)' }, horzLines: { color: 'rgba(83,64,41,.06)' } },
          rightPriceScale: { borderColor: 'rgba(83,64,41,.16)' },
          timeScale: { borderColor: 'rgba(83,64,41,.16)' },
        });
        const candles = chart.addCandlestickSeries({
          upColor: '#496f5c', downColor: '#9b4d43', borderVisible: false,
          wickUpColor: '#496f5c', wickDownColor: '#9b4d43',
        });
        const volume = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' });
        volume.priceScale().applyOptions({ scaleMargins: { top: .82, bottom: 0 } });
        const ma5 = chart.addLineSeries({ color: '#806127', lineWidth: 2, priceLineVisible: false });
        const ma20 = chart.addLineSeries({ color: '#687a82', lineWidth: 2, priceLineVisible: false });
        candles.setData(series.candles);
        volume.setData(series.volume);
        ma5.setData(series.ma5);
        ma20.setData(series.ma20);
        chart.timeScale().fitContent();
        chartSeries = { candles, volume, ma5, ma20 };
      }

      const quote = payload.quote || {};
      setText(marketTradeDate, payload.latest_trade_date ? `最新交易日 ${payload.latest_trade_date}` : '最近交易日数据');
      marketChartElement.setAttribute(
        'aria-label',
        `${payload.code || '个股'} 历史行情，截至 ${payload.latest_trade_date || '最近交易日'}`,
      );
      if (marketQuote) {
        setText(marketQuote.querySelector('strong'), quote.close == null ? '—' : Number(quote.close).toFixed(2));
        const change = quote.pct_change == null ? '最近交易日收盘' : `${quote.pct_change >= 0 ? '+' : ''}${Number(quote.pct_change).toFixed(2)}%`;
        setText(marketQuote.querySelector('span'), change);
      }
      const metrics = [
        ['市盈率 TTM', quote.pe_ttm == null ? '—' : Number(quote.pe_ttm).toFixed(2)],
        ['市净率 MRQ', quote.pb_mrq == null ? '—' : Number(quote.pb_mrq).toFixed(2)],
        ['换手率', quote.turnover == null ? '—' : `${Number(quote.turnover).toFixed(2)}%`],
        ['成交量', quote.volume == null ? '—' : Number(quote.volume).toLocaleString('zh-CN')],
      ];
      if (marketMetrics) {
        marketMetrics.replaceChildren(...metrics.map(([term, value]) => {
          const wrapper = root.ownerDocument.createElement('div');
          const dt = root.ownerDocument.createElement('dt');
          const dd = root.ownerDocument.createElement('dd');
          dt.textContent = term;
          dd.textContent = value;
          wrapper.append(dt, dd);
          return wrapper;
        }));
      }
      return chartSeries;
    }

    function renderReport(result = {}) {
      if (result.company_name || result.stock_code) {
        setText(stockTitle, result.company_name || result.stock_code);
      }
      const hasMissingDimensions = Array.isArray(result.missing_dimensions)
        && result.missing_dimensions.length > 0;
      if (runningState) runningState.hidden = !hasMissingDimensions;
      if (report) report.hidden = false;
      setText(root.querySelector('#reportTitle'), `${result.company_name || '股票'}分析报告`);
      setText(root.querySelector('#reportCode'), result.stock_code || '—');
      setText(root.querySelector('#reportDate'), result.analysis_date || '—');
      if (typeof options.renderReportContent === 'function') {
        options.renderReportContent(result, reportContent, reportNavigation);
      } else if (reportContent) {
        reportContent.textContent = result.final_report || '报告内容暂不可用。';
      }
    }

    function renderError(message) {
      setText(statusText, message || '分析未完成，请稍后重试。');
      root.dataset.phase = 'error';
    }

    root.querySelectorAll('[data-frequency]').forEach((button) => {
      const handler = () => {
        root.querySelectorAll('[data-frequency]').forEach((item) => {
          item.setAttribute('aria-pressed', String(item === button));
        });
        if (typeof options.onFrequencyChange === 'function') {
          options.onFrequencyChange(button.dataset.frequency);
        }
      };
      button.addEventListener('click', handler);
      cleanup.push(() => button.removeEventListener('click', handler));
    });

    AGENTS.forEach((key) => {
      const retry = agentCards[key] && agentCards[key].querySelector('.agent-retry');
      if (!retry) return;
      const handler = () => {
        if (typeof options.onRetry === 'function') options.onRetry(key);
      };
      retry.addEventListener('click', handler);
      cleanup.push(() => retry.removeEventListener('click', handler));
    });

    function destroy() {
      cleanup.splice(0).forEach((dispose) => dispose());
      if (chart && typeof chart.remove === 'function') chart.remove();
      if (chartResizeObserver) chartResizeObserver.disconnect();
      chart = null;
      chartSeries = null;
    }

    return {
      reset,
      updateStatus,
      updatePartialResults,
      renderMarket,
      renderReport,
      renderError,
      destroy,
    };
  }

  return {
    AGENTS,
    normalizeAgentDetails,
    hasRunningAgents,
    derivePhase,
    agentSummaryForStatus,
    buildMarketSeries,
    completedResultKeys,
    nextRequests,
    canRetryAgent,
    resolveChartSize,
    stripLeadingMarkdownHeading,
    formatAnalysisMarkdown,
    createController,
  };
});
