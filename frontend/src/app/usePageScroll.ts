import Lenis from 'lenis';
import { useEffect, useRef } from 'react';
import 'lenis/dist/lenis.css';

export const INTRO_LOCK_MS = 2500;

export function usePageScroll(pathname: string, opening: boolean) {
  const scroller = useRef<Lenis | null>(null);
  const openUntil = useRef<number | undefined>(undefined);

  useEffect(() => {
    const preferReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (opening && openUntil.current === undefined) openUntil.current = Date.now() + INTRO_LOCK_MS;
    let frame = 0;
    let unlock: number | undefined;
    function reset() {
      cancelAnimationFrame(frame);
      window.clearTimeout(unlock);
      scroller.current?.destroy();
      scroller.current = null;
    }
    function setup() {
      reset();
      if (preferReducedMotion.matches) return;
      const lenis = new Lenis({
        smoothWheel: true,
        virtualScroll: ({ event }) => !event.defaultPrevented,
        prevent: (node) => node.hasAttribute('data-scroll-region') && node.scrollHeight > node.clientHeight,
      });
      scroller.current = lenis;
      const remaining = (openUntil.current ?? 0) - Date.now();
      if (remaining > 0) {
        lenis.stop();
        unlock = window.setTimeout(() => lenis.start(), remaining);
      }
      function advance(time: number) {
        lenis.raf(time);
        frame = requestAnimationFrame(advance);
      }
      frame = requestAnimationFrame(advance);
    }
    preferReducedMotion.addEventListener('change', setup);
    setup();
    return () => {
      preferReducedMotion.removeEventListener('change', setup);
      reset();
    };
  }, [opening]);

  useEffect(() => {
    const lenis = scroller.current;
    if (lenis) {
      lenis.resize();
      lenis.scrollTo(0, { immediate: true, force: true });
    } else {
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
  }, [pathname]);
}
