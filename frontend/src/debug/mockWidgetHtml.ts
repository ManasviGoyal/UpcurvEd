export const USE_MOCK_WIDGET = true;

export const TEST_WIDGET_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Interactive Widget Test</title>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #ffffff;
      color: #111827;
    }

    * {
      box-sizing: border-box;
    }

    .wrap {
      min-height: 100vh;
      padding: 16px;
    }

    .row {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin: 12px 0;
    }

    button {
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid #d1d5db;
      background: #f9fafb;
      cursor: pointer;
      font: inherit;
    }

    button:hover {
      background: #f3f4f6;
    }

    #log {
      font-size: 14px;
    }

    canvas {
      width: 100%;
      max-width: 900px;
      height: 420px;
      border: 1px solid #d1d5db;
      border-radius: 12px;
      display: block;
      cursor: crosshair;
      background: #fafafa;
      pointer-events: auto;
    }

    .hint {
      color: #4b5563;
      font-size: 14px;
      margin-top: 0;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Interactive Widget Test</h1>
    <p class="hint">If the iframe is truly interactive, the button will increment and clicking the canvas will move the blue dot.</p>

    <div class="row">
      <button id="btn" type="button">Test button</button>
      <span id="log">booting…</span>
    </div>

    <canvas id="canvas" width="900" height="420"></canvas>
  </div>

  <script>
    const log = document.getElementById('log');
    const btn = document.getElementById('btn');
    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');

    let clickCount = 0;
    let point = { x: 140, y: 140 };

    function drawGrid() {
      ctx.strokeStyle = '#e5e7eb';
      ctx.lineWidth = 1;

      for (let x = 0; x <= canvas.width; x += 45) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
      }

      for (let y = 0; y <= canvas.height; y += 45) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
      }
    }

    function drawPoint() {
      ctx.fillStyle = '#2563eb';
      ctx.beginPath();
      ctx.arc(point.x, point.y, 12, 0, Math.PI * 2);
      ctx.fill();
    }

    function drawLabel() {
      ctx.fillStyle = '#111827';
      ctx.font = '16px sans-serif';
      ctx.fillText('Point: (' + Math.round(point.x) + ', ' + Math.round(point.y) + ')', 18, 28);
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#fafafa';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawGrid();
      drawPoint();
      drawLabel();
    }

    btn.addEventListener('click', () => {
      clickCount += 1;
      log.textContent = 'button clicked ' + clickCount + ' times';
    });

    canvas.addEventListener('click', (event) => {
      const rect = canvas.getBoundingClientRect();
      point = {
        x: (event.clientX - rect.left) * (canvas.width / rect.width),
        y: (event.clientY - rect.top) * (canvas.height / rect.height),
      };
      log.textContent = 'canvas click at (' + Math.round(point.x) + ', ' + Math.round(point.y) + ')';
      draw();
    });

    window.addEventListener('error', (event) => {
      log.textContent = 'error: ' + event.message;
    });

    draw();
    log.textContent = 'ready';
  </script>
</body>
</html>`;
