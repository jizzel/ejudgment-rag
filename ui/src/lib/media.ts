import { useSyncExternalStore } from "react";

/** Below Tailwind's `lg` breakpoint, where the evidence opens as a full-screen sheet. */
export const NARROW_QUERY = "(max-width: 1023.98px)";

function subscribe(onChange: () => void): () => void {
  const list = typeof window !== "undefined" ? window.matchMedia?.(NARROW_QUERY) : undefined;
  list?.addEventListener?.("change", onChange);
  return () => list?.removeEventListener?.("change", onChange);
}

function narrowNow(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.(NARROW_QUERY).matches === true;
}

/** Whether the screen is narrow (false on the server and before hydration). */
export function useNarrow(): boolean {
  return useSyncExternalStore(subscribe, narrowNow, () => false);
}
