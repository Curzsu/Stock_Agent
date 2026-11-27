import Markdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import styles from './ReportPage.module.css';

function normalizeMarkdown(source: string) {
  let fence: string | undefined;
  const lines = source.split(/\r?\n/).filter((line) => {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (fence) {
      if (marker?.[1][0] === fence[0] && marker[1].length >= fence.length
        && !line.slice(marker[0].length).trim()) fence = undefined;
      return true;
    }
    if (marker) fence = marker[1];
    return !/^ {0,3}(?:\[TOC\]|<!--\s*TOC\s*-->)\s*$/i.test(line);
  });
  return lines.join('\n').replace(/^(?:[ \t]*\n)*#{1,6}[ \t]+[^\n]+\n?/, '');
}

function reportUrl(url: string) {
  return /^(?:https?:\/\/|mailto:|#)/i.test(url) ? defaultUrlTransform(url) : '';
}

export function ReportMarkdown({ source }: { source: string }) {
  return (
    <div className={styles.markdown}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        urlTransform={reportUrl}
        disallowedElements={['img']}
        components={{
          h1: ({ children }) => <h3>{children}</h3>,
          h2: ({ children }) => <h3>{children}</h3>,
          h3: ({ children }) => <h4>{children}</h4>,
          a: ({ children, href }) => href ? <a href={href} target={href.startsWith('#') ? undefined : '_blank'} rel="noopener noreferrer">{children}</a> : <>{children}</>,
          th: ({ children, style }) => <th scope="col" style={style}>{children}</th>,
          table: ({ children }) => <div className={styles.tableScroll} role="region" aria-label="报告数据表" tabIndex={0} data-scroll-region><table>{children}</table></div>,
        }}
      >
        {normalizeMarkdown(source)}
      </Markdown>
    </div>
  );
}
