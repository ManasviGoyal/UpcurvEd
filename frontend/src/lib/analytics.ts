type EventProps = Record<string, string | number | boolean | null | undefined>;

export function trackEvent(eventName: string, props: EventProps = {}) {
  try {
    const w = window as any;

    if (typeof w.gtag === "function") {
      w.gtag("event", eventName, props);
    }

    if (typeof w.plausible === "function") {
      w.plausible(eventName, { props });
    }

    const endpoint = String(import.meta.env.VITE_ANALYTICS_ENDPOINT || "").trim();
    if (endpoint) {
      void fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event: eventName,
          props,
          ts: Date.now(),
          path: window.location.pathname,
        }),
      }).catch(() => {});
    }
  } catch {
    // no-op
  }
}
