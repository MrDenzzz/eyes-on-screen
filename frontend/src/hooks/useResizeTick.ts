import { type RefObject, useEffect, useState } from "react";

/** A number that changes whenever the element is resized: a dependency for canvas redraws. */
export function useResizeTick(ref: RefObject<HTMLElement | null>): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setTick((value) => value + 1));
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return tick;
}
