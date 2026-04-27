export interface PrepareWidgetHtmlOptions {
  assetBaseUrl?: string;
}

const BASE_STYLE = `
<style id="upcurved-widget-base-style">
  html, body {
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #e5e7eb;
    font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  body {
    box-sizing: border-box;
  }
  *, *::before, *::after {
    box-sizing: border-box;
  }
  button, input, select, textarea, canvas, label, a {
    pointer-events: auto;
  }
  img, svg { max-width: 100%; }
  #upcurved-widget-error {
    display: none;
    position: fixed;
    left: 12px;
    right: 12px;
    bottom: 12px;
    z-index: 2147483647;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid #fecaca;
    background: rgba(254, 242, 242, 0.98);
    color: #991b1b;
    font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
    white-space: pre-wrap;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12);
  }
</style>`;

const ERROR_BRIDGE = `
<script id="upcurved-widget-error-bridge">
(() => {
  const ensureErrorBox = () => {
    let el = document.getElementById('upcurved-widget-error');
    if (!el) {
      el = document.createElement('pre');
      el.id = 'upcurved-widget-error';
      document.body.appendChild(el);
    }
    return el;
  };

  const show = (label, message) => {
    const el = ensureErrorBox();
    el.style.display = 'block';
    el.textContent = label + ': ' + String(message || 'Unknown widget error');
  };

  window.addEventListener('error', (event) => {
    show('Widget error', event?.error?.stack || event?.message || 'Unknown widget error');
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event?.reason;
    show(
      'Widget promise rejection',
      reason?.stack || reason?.message || String(reason || 'Unknown rejection')
    );
  });
})();
</script>`;

const CANVAS_FIX = `
<script id="upcurved-canvas-fix">
window.addEventListener('load', () => {
  document.querySelectorAll('canvas').forEach((canvas) => {
    const c = canvas;
    const needsFix =
      c.width === 0 ||
      c.height === 0 ||
      (c.width === 300 && c.height === 150);
    if (!needsFix) return;
    const parent = c.parentElement;
    if (!parent || parent.clientWidth <= 0) return;
    c.width = parent.clientWidth;
    c.height = parent.clientHeight > 0 ? parent.clientHeight : Math.round(parent.clientWidth * 0.6);
    window.dispatchEvent(new Event('resize'));
  });
});
</script>`;

const hasFullHtmlDocument = (input: string) => /<!doctype html|<html[\s>]/i.test(input);

const wrapFragment = (input: string) => `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Interactive Widget</title>
</head>
<body>
${input}
</body>
</html>`;

const injectIntoHead = (html: string, injection: string) => {
  if (/<\/head>/i.test(html)) {
    return html.replace(/<\/head>/i, `${injection}\n</head>`);
  }
  if (/<body[\s>]/i.test(html)) {
    return html.replace(/<body([\s>])/i, `<head>${injection}</head>\n<body$1`);
  }
  return `<!DOCTYPE html><html><head>${injection}</head><body>${html}</body></html>`;
};

export const prepareWidgetHtmlForIframe = (
  rawHtml: string,
  _options: PrepareWidgetHtmlOptions = {}
): string => {
  const trimmed = String(rawHtml || "").trim();
  let html = hasFullHtmlDocument(trimmed) ? trimmed : wrapFragment(trimmed);
  html = injectIntoHead(html, `${BASE_STYLE}\n${ERROR_BRIDGE}\n${CANVAS_FIX}`);
  return html;
};
