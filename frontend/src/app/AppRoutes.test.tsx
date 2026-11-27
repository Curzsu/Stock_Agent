import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { AppRoutes } from './AppRoutes';

function renderPath(path: string) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter basename="/react-preview/" initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('React preview routes', () => {
  it('opens the existing FINEX workbench from the preview home', () => {
    const html = renderPath('/react-preview/');
    expect(html).toContain('<h1><span>智能</span><span>金融分析</span></h1>');
    expect(html).toContain('<a href="http://127.0.0.1:8100/">打开 FINEX 工作台</a>');
  });

  it('renders a workbench directly for the task ID in the URL', () => {
    const html = renderPath('/react-preview/app/analysis/abc123');
    expect(html).toContain('<h1>研究工作台</h1>');
    expect(html).toContain('任务编号 abc123');
    expect(html).toMatch(/<a [^>]*aria-label="返回首页"[^>]*href="\/react-preview\/"[^>]*>/);
  });
});
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
