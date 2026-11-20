import { useEffect, useRef } from 'react';

export function useScrollReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || !('IntersectionObserver' in window)
      || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    node.dataset.arrival = 'waiting';
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      node.dataset.arrival = 'shown';
      observer.disconnect();
    }, { rootMargin: `0px 0px -${Math.round(window.innerHeight * .12)}px 0px` });
    observer.observe(node);
    return () => {
      observer.disconnect();
      delete node.dataset.arrival;
    };
  }, []);
  return ref;
}
