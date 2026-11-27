import { startStatusPolling, type PollCommand } from './polling';

let polling: ReturnType<typeof startStatusPolling> | undefined;

self.addEventListener('message', ({ data }: MessageEvent<PollCommand>) => {
  if (data.type === 'start') {
    polling?.stop();
    polling = startStatusPolling(data.id, data.deadline, (event) => self.postMessage(event));
  } else {
    polling?.refresh();
  }
});
