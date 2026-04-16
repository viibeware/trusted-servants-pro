(function(){
  const rand = (a, b) => a + Math.random() * (b - a);

  function hexToRgb(h){
    h = (h || '').replace('#','');
    if (h.length === 3) h = h.split('').map(c => c+c).join('');
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgbToCss(r){ return 'rgb(' + r[0] + ',' + r[1] + ',' + r[2] + ')'; }
  function randomHex(){
    const h = Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0');
    return '#' + h;
  }
  function randomPalette(n){
    // cohesive random palette in HSL space
    const base = Math.random();
    const sat = 0.5 + Math.random() * 0.35;
    const light = 0.35 + Math.random() * 0.25;
    const out = [];
    for (let i = 0; i < n; i++){
      const h = (base + i / n * (0.15 + Math.random() * 0.35)) % 1;
      out.push(hslToHex(h, sat, light + (i - n/2) * 0.04));
    }
    return out;
  }
  function hslToHex(h, s, l){
    l = Math.max(0.1, Math.min(0.85, l));
    const a = s * Math.min(l, 1 - l);
    const f = n => {
      const k = (n + h * 12) % 12;
      const v = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
      return Math.round(v * 255).toString(16).padStart(2, '0');
    };
    return '#' + f(0) + f(8) + f(4);
  }

  function renderSineGradient(canvas, colors){
    if (!canvas || !colors || colors.length < 1) return;
    const W = canvas.width = 300;
    const H = canvas.height = 500;
    const gctx = canvas.getContext('2d');
    if (colors.length === 1){
      gctx.fillStyle = colors[0]; gctx.fillRect(0, 0, W, H); return;
    }
    const rgb = colors.map(hexToRgb);
    const n = rgb.length;
    const img = gctx.createImageData(W, H);
    const d = img.data;
    const f1 = 2 * Math.PI / W * 1;
    const f2 = 2 * Math.PI / W * 2.3;
    const amp1 = 0.18, amp2 = 0.09;
    for (let y = 0; y < H; y++){
      for (let x = 0; x < W; x++){
        const phase = Math.sin(x * f1) * amp1 + Math.sin(x * f2 + 1.2) * amp2;
        let t = y / (H - 1) + phase;
        if (t < 0) t = 0; else if (t > 1) t = 1;
        const p = t * (n - 1);
        const i = Math.floor(p);
        const f = p - i;
        const a = rgb[i], b = rgb[Math.min(n - 1, i + 1)];
        // smoothstep for buttery blending
        const u = f * f * (3 - 2 * f);
        const idx = (y * W + x) * 4;
        d[idx]   = a[0] + (b[0] - a[0]) * u;
        d[idx+1] = a[1] + (b[1] - a[1]) * u;
        d[idx+2] = a[2] + (b[2] - a[2]) * u;
        d[idx+3] = 255;
      }
    }
    gctx.putImageData(img, 0, 0);
  }

  function applyBackground(el, colors){
    if (!el) return;
    if (!colors || !colors.length){ el.style.background = ''; el.style.backgroundImage = ''; return; }
    if (colors.length === 1){ el.style.background = colors[0]; return; }
    const c = document.createElement('canvas');
    renderSineGradient(c, colors);
    el.style.backgroundImage = 'url(' + c.toDataURL('image/jpeg', 0.92) + ')';
    el.style.backgroundSize = '100% 100%';
    el.style.backgroundRepeat = 'no-repeat';
    el.style.backgroundColor = colors[0];
  }

  window.loginFxUtils = { hexToRgb, rgbToCss, randomHex, randomPalette, renderSineGradient, applyBackground };


  const factories = {
    network: (w, h) => ({x: Math.random()*w, y: Math.random()*h, vx: rand(-0.7, 0.7), vy: rand(-0.7, 0.7), r: rand(1, 2.8), a: rand(0.35, 0.85)}),
    stars: (w, h) => ({x: Math.random()*w, y: Math.random()*h, vx: rand(-0.08, 0.08), vy: rand(-0.05, 0.05), r: rand(0.6, 2.2), a: rand(0.4, 1), tw: rand(0, Math.PI*2), ts: rand(0.02, 0.06)}),
    fireflies: (w, h) => ({x: Math.random()*w, y: Math.random()*h, vx: rand(-0.3, 0.3), vy: rand(-0.3, 0.3), r: rand(1.5, 3.5), a: rand(0.3, 0.9), tw: rand(0, Math.PI*2), ts: rand(0.01, 0.04), ax: rand(-0.02, 0.02), ay: rand(-0.02, 0.02)}),
    bubbles: (w, h) => ({x: Math.random()*w, y: Math.random()*h + h, vy: rand(-1.6, -0.5), r: rand(3, 14), a: rand(0.15, 0.5), phase: rand(0, Math.PI*2), drift: rand(0.3, 1.2)}),
    snow: (w, h) => ({x: Math.random()*w, y: Math.random()*h, vy: rand(0.4, 1.4), r: rand(1, 3), a: rand(0.4, 0.95), phase: rand(0, Math.PI*2), drift: rand(0.4, 1.4)}),
    waves: null,
    orbits: (w, h) => ({cx: Math.random()*w, cy: Math.random()*h, rad: rand(20, 180), ang: rand(0, Math.PI*2), speed: rand(-0.012, 0.012), r: rand(1, 2.6), a: rand(0.4, 0.9), drift: rand(-0.05, 0.05)}),
    rain: (w, h) => ({x: Math.random()*w, y: Math.random()*h, vy: rand(6, 14), len: rand(10, 24), a: rand(0.25, 0.6)}),
  };

  const densities = { network: 14000, stars: 5000, fireflies: 20000, bubbles: 22000, snow: 9000, waves: 0, orbits: 16000, rain: 7000 };

  function init(canvas, opts){
    opts = opts || {};
    let effect = opts.effect || 'network';
    let speed = (opts.speed == null ? 100 : opts.speed) / 100;
    let sizeMul = (opts.size == null ? 100 : opts.size) / 100;
    const parent = canvas.parentElement;
    const ctx = canvas.getContext('2d');
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let w = 0, h = 0, particles = [], t = 0, raf = 0, alive = true;
    const mouse = {x: -9999, y: -9999, px: -9999, py: -9999, vx: 0, vy: 0, active: false};
    const onMove = e => {
      const r = canvas.getBoundingClientRect();
      const nx = e.clientX - r.left, ny = e.clientY - r.top;
      if (mouse.active){ mouse.vx = nx - mouse.x; mouse.vy = ny - mouse.y; }
      else { mouse.vx = 0; mouse.vy = 0; }
      mouse.px = mouse.x; mouse.py = mouse.y;
      mouse.x = nx; mouse.y = ny; mouse.active = true;
    };
    const onLeave = () => { mouse.x = -9999; mouse.y = -9999; mouse.vx = mouse.vy = 0; mouse.active = false; };
    parent.addEventListener('mousemove', onMove);
    parent.addEventListener('mouseleave', onLeave);

    function applyMouse(p, opts){
      if (!mouse.active) return;
      opts = opts || {};
      const radius = opts.radius || 120;
      const repel = opts.repel == null ? 0.55 : opts.repel;
      const drag = opts.drag == null ? 0.18 : opts.drag;
      const dx = p.x - mouse.x, dy = p.y - mouse.y;
      const d2 = dx*dx + dy*dy;
      if (d2 < radius * radius){
        const d = Math.sqrt(d2) || 1;
        const falloff = (1 - d / radius);
        const f = falloff * falloff * radius * repel;
        p.x += (dx / d) * (f / radius);
        p.y += (dy / d) * (f / radius);
        if (p.vx !== undefined){
          p.vx += (dx / d) * falloff * repel * 0.6;
          p.vy += (dy / d) * falloff * repel * 0.6;
          // drag toward cursor motion — particles get swept along
          p.vx += mouse.vx * falloff * drag * 0.1;
          p.vy += mouse.vy * falloff * drag * 0.1;
        }
      }
    }

    function populate(){
      const f = factories[effect];
      if (!f) { particles = []; return; }
      const density = densities[effect] || 14000;
      const target = effect === 'waves' ? 0 : Math.min(220, Math.max(20, Math.round(w * h / density)));
      particles.length = 0;
      for (let i = 0; i < target; i++) particles.push(f(w, h));
    }
    function resize(){
      const r = parent.getBoundingClientRect();
      w = Math.max(1, r.width); h = Math.max(1, r.height);
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      populate();
    }

    function drawNetwork(s){
      for (let i = 0; i < 3; i++){
        const gx = w * (0.5 + 0.35 * Math.cos(t*(0.6+i*0.3) + i));
        const gy = h * (0.5 + 0.35 * Math.sin(t*(0.5+i*0.25) + i*1.7));
        const g = ctx.createRadialGradient(gx, gy, 0, gx, gy, Math.max(w,h)*0.45);
        g.addColorStop(0, 'rgba(255,255,255,0.10)'); g.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      }
      for (const p of particles){
        applyMouse(p, {radius: 140, repel: 0.5, drag: 0.3});
        p.vx *= Math.pow(0.995, s); p.vy *= Math.pow(0.995, s);
        p.x += p.vx * s; p.y += p.vy * s;
        if (p.x < -10) p.x = w+10; else if (p.x > w+10) p.x = -10;
        if (p.y < -10) p.y = h+10; else if (p.y > h+10) p.y = -10;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r * sizeMul, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(255,255,255,'+p.a.toFixed(2)+')'; ctx.fill();
      }
      const L = 140;
      for (let i = 0; i < particles.length; i++){
        for (let j = i+1; j < particles.length; j++){
          const a = particles[i], b = particles[j];
          const dx = a.x-b.x, dy = a.y-b.y, d2 = dx*dx+dy*dy;
          if (d2 < L*L){
            const alpha = (1 - Math.sqrt(d2)/L) * 0.25;
            ctx.strokeStyle = 'rgba(255,255,255,'+alpha.toFixed(3)+')'; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
      }
    }
    function drawStars(s){
      for (const p of particles){
        applyMouse(p, {radius: 100, repel: 0.35, drag: 0.5});
        p.vx *= Math.pow(0.9, s); p.vy *= Math.pow(0.9, s);
        p.x += p.vx * s; p.y += p.vy * s; p.tw += p.ts * s;
        if (p.x < -5) p.x = w+5; else if (p.x > w+5) p.x = -5;
        if (p.y < -5) p.y = h+5; else if (p.y > h+5) p.y = -5;
        const tw = 0.5 + 0.5 * Math.sin(p.tw);
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r * sizeMul, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(255,255,255,'+(p.a*tw).toFixed(3)+')'; ctx.fill();
      }
    }
    function drawFireflies(s){
      for (const p of particles){
        applyMouse(p, {radius: 150, repel: 0.45, drag: 0.5});
        p.vx += (p.ax + rand(-0.02, 0.02)) * s;
        p.vy += (p.ay + rand(-0.02, 0.02)) * s;
        p.vx *= Math.pow(0.96, s); p.vy *= Math.pow(0.96, s);
        p.x += p.vx * s; p.y += p.vy * s; p.tw += p.ts * s;
        if (p.x < -10) p.x = w+10; else if (p.x > w+10) p.x = -10;
        if (p.y < -10) p.y = h+10; else if (p.y > h+10) p.y = -10;
        const pulse = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(p.tw));
        const pr = p.r * sizeMul;
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, pr*5);
        g.addColorStop(0, 'rgba(255,255,220,'+(0.9*pulse).toFixed(3)+')');
        g.addColorStop(0.4, 'rgba(255,240,160,'+(0.35*pulse).toFixed(3)+')');
        g.addColorStop(1, 'rgba(255,240,160,0)');
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(p.x, p.y, pr*5, 0, Math.PI*2); ctx.fill();
        ctx.beginPath(); ctx.arc(p.x, p.y, pr*0.6, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(255,255,220,'+pulse.toFixed(3)+')'; ctx.fill();
      }
    }
    function drawBubbles(s){
      for (const p of particles){
        applyMouse(p, {radius: 130, repel: 0.6, drag: 0.25});
        p.y += p.vy * s;
        p.x += Math.sin((p.y + p.phase*40) * 0.02) * p.drift * 0.4 * s;
        if (p.y + p.r * sizeMul < 0){ p.y = h + p.r * sizeMul; p.x = Math.random()*w; }
        const pr = p.r * sizeMul;
        ctx.beginPath(); ctx.arc(p.x, p.y, pr, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba(255,255,255,'+p.a.toFixed(2)+')';
        ctx.lineWidth = 1.2; ctx.stroke();
        ctx.beginPath(); ctx.arc(p.x - pr*0.35, p.y - pr*0.35, pr*0.18, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(255,255,255,'+(p.a*0.9).toFixed(2)+')'; ctx.fill();
      }
    }
    function drawSnow(s){
      for (const p of particles){
        applyMouse(p, {radius: 120, repel: 0.45, drag: 0.35});
        p.y += p.vy * s;
        p.x += Math.sin((p.y + p.phase*50) * 0.015) * p.drift * 0.6 * s;
        if (p.y - p.r * sizeMul > h){ p.y = -p.r * sizeMul; p.x = Math.random()*w; }
        if (p.x < -10) p.x = w+10; else if (p.x > w+10) p.x = -10;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r * sizeMul, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(255,255,255,'+p.a.toFixed(2)+')'; ctx.fill();
      }
    }
    function drawWaves(s){
      const layers = 5;
      for (let i = 0; i < layers; i++){
        const amp = 18 + i*10;
        const freq = 0.004 + i*0.0016;
        const sp = 0.6 + i*0.25;
        const yBase = h * (0.2 + i * 0.15);
        const alpha = 0.10 + i * 0.05;
        ctx.beginPath();
        for (let x = 0; x <= w + 4; x += 4){
          const y = yBase + Math.sin(x * freq + t * sp + i) * amp
                          + Math.cos(x * freq * 0.5 + t * sp * 0.7) * amp * 0.3;
          if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
        ctx.fillStyle = 'rgba(255,255,255,'+alpha.toFixed(3)+')';
        ctx.fill();
      }
    }
    function drawOrbits(s){
      for (const p of particles){
        p.ang += p.speed * s; p.cx += p.drift * s;
        if (mouse.active){
          const dx = p.cx - mouse.x, dy = p.cy - mouse.y, d2 = dx*dx+dy*dy;
          if (d2 < 180*180){ const d = Math.sqrt(d2)||1, f=(180-d)/180*0.6;
            p.cx += dx/d*f; p.cy += dy/d*f; }
        }
        if (p.cx < -p.rad) p.cx = w + p.rad; else if (p.cx > w + p.rad) p.cx = -p.rad;
        for (let k = 0; k < 10; k++){
          const ang = p.ang - k * 0.05;
          const tx = p.cx + Math.cos(ang) * p.rad;
          const ty = p.cy + Math.sin(ang) * p.rad;
          ctx.beginPath(); ctx.arc(tx, ty, p.r * sizeMul * (1 - k/10), 0, Math.PI*2);
          ctx.fillStyle = 'rgba(255,255,255,'+(p.a*(1-k/10)*0.4).toFixed(3)+')'; ctx.fill();
        }
        const x = p.cx + Math.cos(p.ang) * p.rad;
        const y = p.cy + Math.sin(p.ang) * p.rad;
        ctx.beginPath(); ctx.arc(x, y, p.r * sizeMul, 0, Math.PI*2);
        ctx.fillStyle = 'rgba(255,255,255,'+p.a.toFixed(2)+')'; ctx.fill();
      }
    }
    function drawRain(s){
      ctx.lineCap = 'round';
      for (const p of particles){
        p.y += p.vy * s;
        // mouse pushes drops to the side
        if (mouse.active){
          const dx = p.x - mouse.x, dy = p.y - mouse.y, d2 = dx*dx+dy*dy;
          if (d2 < 120*120){ const d = Math.sqrt(d2)||1, f=(120-d)/120*0.8; p.x += dx/d*f; }
        }
        if (p.y > h + p.len){ p.y = -p.len; p.x = Math.random()*w; }
        ctx.strokeStyle = 'rgba(255,255,255,'+p.a.toFixed(2)+')';
        ctx.lineWidth = 1.1 * sizeMul;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x, p.y + p.len * sizeMul); ctx.stroke();
      }
    }
    const drawers = { network: drawNetwork, stars: drawStars, fireflies: drawFireflies,
      bubbles: drawBubbles, snow: drawSnow, waves: drawWaves, orbits: drawOrbits, rain: drawRain };

    function frame(){
      if (!alive) return;
      t += 0.01 * speed;
      ctx.clearRect(0, 0, w, h);
      const draw = drawers[effect] || drawNetwork;
      draw(speed);
      mouse.vx *= 0.8; mouse.vy *= 0.8;
      raf = requestAnimationFrame(frame);
    }

    resize();
    const onResize = () => resize();
    window.addEventListener('resize', onResize);
    raf = requestAnimationFrame(frame);

    return {
      setEffect(e){ if (factories[e] !== undefined || e === 'waves') { effect = e; populate(); } },
      setSpeed(sp){ speed = Math.max(0.05, sp / 100); },
      setSize(sz){ sizeMul = Math.max(0.1, sz / 100); },
      setColor(c){ parent.style.background = c || ''; },
      destroy(){
        alive = false; cancelAnimationFrame(raf);
        parent.removeEventListener('mousemove', onMove);
        parent.removeEventListener('mouseleave', onLeave);
        window.removeEventListener('resize', onResize);
      }
    };
  }

  window.initLoginFX = init;
})();
