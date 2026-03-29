import { useCallback, useEffect, useRef } from 'react';

interface UsePollingBackoffOptions {
  enabled: boolean;
  onPoll: () => Promise<void>;
  minInterval?: number;
  maxInterval?: number;
  factor?: number;
}

export function usePollingBackoff({
  enabled,
  onPoll,
  minInterval = 4000,
  maxInterval = 60000,
  factor = 2,
}: UsePollingBackoffOptions): void {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentInterval = useRef(minInterval);
  const onPollRef = useRef(onPoll);
  onPollRef.current = onPoll;

  const schedule = useCallback(() => {
    timerRef.current = setTimeout(async () => {
      if (document.visibilityState !== 'visible') {
        currentInterval.current = Math.min(currentInterval.current * factor, maxInterval);
        schedule();
        return;
      }
      const before = currentInterval.current;
      try {
        await onPollRef.current();
        currentInterval.current = minInterval;
      } catch {
        currentInterval.current = Math.min(before * factor, maxInterval);
      }
      schedule();
    }, currentInterval.current);
  }, [factor, maxInterval, minInterval]);

  useEffect(() => {
    if (!enabled) {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      currentInterval.current = minInterval;
      return;
    }
    currentInterval.current = minInterval;
    schedule();
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, [enabled, minInterval, schedule]);
}
