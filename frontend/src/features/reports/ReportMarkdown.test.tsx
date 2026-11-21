import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { ReportMarkdown } from './ReportMarkdown';

it('keeps financial tables, quotes and code while removing source TOC markers', () => {
  const html = renderToStaticMarkup(<ReportMarkdown source={[
    '[TOC]', '# 原标题', '', '## 摘要', '', '> **结论**', '',
    '| 指标 | 值 |', '| --- | ---: |', '| ROE | 15.99% |', '',
    '```text', '[TOC]', '<script>', '```',
  ].join('\n')} />);
  expect(html).not.toContain('原标题');
  expect(html).toContain('<h3>摘要</h3>');
  expect(html).toContain('<blockquote>');
  expect(html).toContain('<th scope="col"');
  expect(html).toContain('15.99%');
  expect(html.match(/\[TOC\]/g)).toHaveLength(1);
  expect(html).toContain('&lt;script&gt;');
});

it('allows references and keeps raw HTML, unsafe links and images inert', () => {
  const html = renderToStaticMarkup(<ReportMarkdown source={[
    '[财报](https://example.com/report?a=1&b=2) [危险](javascript:alert(1))',
    '', '<img src=x onerror=alert(1)>', '', '![远程图片](https://example.com/image.jpg)',
  ].join('\n')} />);
  expect(html).toContain('href="https://example.com/report?a=1&amp;b=2"');
  expect(html).toContain('危险');
  expect(html).not.toMatch(/href="javascript:|<img|<script/);
});
