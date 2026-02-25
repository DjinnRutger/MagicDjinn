/**
 * flying_cards.js — Atmospheric background card animation for MagicDjinn.
 *
 * Fetches up to 20 card images from /api/spotlight-cards and animates them
 * drifting across the screen. Cards are very low opacity so they don't
 * interfere with content.
 *
 * Only activates when #flying-cards-stage exists in the DOM.
 * Controlled by the enable_flying_cards admin setting (server-side).
 */
(function () {
  'use strict';

  const stage = document.getElementById('flying-cards-stage');
  if (!stage) return;

  /* ── Inject CSS once ─────────────────────────────────────────────────────── */
  const css = document.createElement('style');
  css.textContent = `
    #flying-cards-stage {
      position: fixed;
      inset: 0;
      overflow: hidden;
      pointer-events: none;
      z-index: 0;
    }
    .fcard {
      position: absolute;
      width: 58px;
      border-radius: 6px;
      opacity: 0;
      will-change: transform, opacity;
      animation: fcFly linear forwards;
    }
    .fcard img {
      width: 100%;
      display: block;
      border-radius: 6px;
      box-shadow: 0 3px 12px rgba(0,0,0,.35);
    }
    @keyframes fcFly {
      0%   { opacity: 0;                transform: translate(0,0) rotate(var(--r0)); }
      8%   { opacity: var(--op); }
      92%  { opacity: var(--op); }
      100% { opacity: 0; transform: translate(var(--dx), var(--dy)) rotate(var(--r1)); }
    }
  `;
  document.head.appendChild(css);

  let pool = [];

  /* ── Spawn one card ───────────────────────────────────────────────────────── */
  function spawn() {
    if (!pool.length) return;

    const data = pool[Math.floor(Math.random() * pool.length)];
    const el   = document.createElement('div');
    el.className = 'fcard';

    const img = document.createElement('img');
    img.src   = data.image;
    img.alt   = '';
    img.loading = 'lazy';
    el.appendChild(img);

    const W = window.innerWidth;
    const H = window.innerHeight;
    const side = Math.floor(Math.random() * 4);
    let sx, sy, ex, ey;

    if (side === 0) {        // top → bottom
      sx = Math.random() * W;  sy = -110;
      ex = Math.random() * W;  ey = H + 110;
    } else if (side === 1) { // right → left
      sx = W + 70;  sy = Math.random() * H;
      ex = -70;     ey = Math.random() * H;
    } else if (side === 2) { // bottom → top
      sx = Math.random() * W;  sy = H + 110;
      ex = Math.random() * W;  ey = -110;
    } else {                 // left → right
      sx = -70;   sy = Math.random() * H;
      ex = W + 70; ey = Math.random() * H;
    }

    const duration = 12000 + Math.random() * 10000;   // 12–22 s
    const r0  = (Math.random() - 0.5) * 28;
    const r1  = r0 + (Math.random() - 0.5) * 36;
    const op  = (0.07 + Math.random() * 0.07).toFixed(3); // 0.07–0.14

    el.style.left = sx + 'px';
    el.style.top  = sy + 'px';
    el.style.setProperty('--dx', (ex - sx) + 'px');
    el.style.setProperty('--dy', (ey - sy) + 'px');
    el.style.setProperty('--r0', r0 + 'deg');
    el.style.setProperty('--r1', r1 + 'deg');
    el.style.setProperty('--op', op);
    el.style.animationDuration = duration + 'ms';

    stage.appendChild(el);
    setTimeout(() => el.remove(), duration + 400);
  }

  /* ── Fetch card images then start animating ───────────────────────────────── */
  fetch('/api/spotlight-cards')
    .then(r => r.ok ? r.json() : [])
    .then(cards => {
      if (!cards.length) return;
      pool = cards;

      // Staggered initial burst (4 cards over 6 s)
      for (let i = 0; i < 4; i++) {
        setTimeout(spawn, i * 1500);
      }
      // Continuous spawn every 3 s
      setInterval(spawn, 3000);
    })
    .catch(() => {}); // fail silently — animation is cosmetic
})();
