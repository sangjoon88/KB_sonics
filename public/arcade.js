/* KB SONICS — 픽셀 3점슛 콘테스트
 * 160×208 캔버스에 직접 그린다 (이미지 파일 없음). 결과(성공 여부)는 손을 뗀 순간 정해지고,
 * 화면 점수는 공이 림에 닿을 때 올라간다. 서버에는 판 시작/종료를 한 번씩만 보낸다.
 */
(() => {
  'use strict';
  const CFG = JSON.parse(document.getElementById('arcade-cfg').textContent);
  const SECONDS = CFG.seconds, RACKS = CFG.racks, BALLS = CFG.balls;
  const W = 160, H = 208;
  const cv = document.getElementById('court');
  const g = cv.getContext('2d');
  cv.width = W; cv.height = H;
  g.imageSmoothingEnabled = false;

  const C = {
    wall: '#1b1027', band: '#2a1441', gold: '#FDB927', purple: '#552583', purple2: '#46206c', paintLine: '#8f5cc4',
    wood: '#c98a4b', wood2: '#b97b3f', wood3: '#d69a5a', line: '#f4efe6',
    skin: '#d9a273', skin2: '#b98256', hair: '#2a1c14', shoe: '#f4f4f4',
    ball: '#e2702a', ballDark: '#8f3f12', money: '#FDB927', moneyDark: '#9a6a08',
    rim: '#ff6a1a', rimBack: '#b8460f', board: '#f2f2f2', boardEdge: '#8e98a3', net: '#ffffff',
    green: '#34d399', fire: '#fb923c', dark: '#0f0b16', slot: '#2b2240', slotLine: '#5a4f6d', miss: '#4a3a5e', white: '#ffffff',
  };
  const FONT = '"Press Start 2P", ui-monospace, monospace';

  // ---------------------------------------------------------------- 코트 기하
  const HOOP = { x: 80, y: 40 };
  const ARC = { cx: 80, cy: 46, rx: 68, ry: 112 };
  const SPOT_DEG = [170, 135, 90, 45, 10];          // 왼쪽 코너 → 오른쪽 코너
  const ZONE_C = [0.58, 0.65, 0.72, 0.65, 0.58];    // 지점별 '딱 맞는 힘' (탑이 가장 멀다)
  const spotXY = deg => {
    const t = deg * Math.PI / 180;
    return { x: ARC.cx + (ARC.rx + 6) * Math.cos(t), y: ARC.cy + (ARC.ry + 6) * Math.sin(t) };
  };
  const SPOTS = SPOT_DEG.map(spotXY);

  // ---------------------------------------------------------------- 픽셀 숫자 3×5 (유니폼 등번호)
  const DIGITS = {
    0: ['111', '101', '101', '101', '111'], 1: ['010', '110', '010', '010', '111'], 2: ['111', '001', '111', '100', '111'],
    3: ['111', '001', '111', '001', '111'], 4: ['101', '101', '111', '001', '001'], 5: ['111', '100', '111', '001', '111'],
    6: ['111', '100', '111', '101', '111'], 7: ['111', '001', '001', '001', '001'], 8: ['111', '101', '111', '101', '111'],
    9: ['111', '101', '111', '001', '111'],
  };
  const px = (x, y, w = 1, h = 1, c) => { if (c) g.fillStyle = c; g.fillRect(Math.round(x), Math.round(y), w, h); };
  function pixelNumber(str, cx, y, color) {
    const w = str.length * 4 - 1;
    let x = Math.round(cx - w / 2);
    g.fillStyle = color;
    for (const ch of str) {
      const rows = DIGITS[ch];
      if (rows) rows.forEach((r, ry) => [...r].forEach((b, rx) => { if (b === '1') g.fillRect(x + rx, y + ry, 1, 1); }));
      x += 4;
    }
  }
  function text(str, x, y, color, size = 8, align = 'left') {
    g.font = `${size}px ${FONT}`;
    g.textAlign = align; g.textBaseline = 'top';
    g.fillStyle = 'rgba(0,0,0,.55)'; g.fillText(str, x + 1, y + 1);
    g.fillStyle = color; g.fillText(str, x, y);
  }

  // ---------------------------------------------------------------- 배경 (한 번만 그려 둔다)
  let BG = null;
  function seeded(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
  function renderBG() {
    const off = document.createElement('canvas'); off.width = W; off.height = H;
    const o = off.getContext('2d');
    const r = seeded(7);
    o.fillStyle = C.wall; o.fillRect(0, 0, W, 34);
    const crowd = ['#3a2a52', '#4a3366', '#2e2340', '#5c4378', '#6b4f2a', '#3d2f25'];
    for (let y = 3; y < 26; y += 5) for (let x = (y % 2) * 2; x < W; x += 4) {
      if (r() < 0.8) { o.fillStyle = crowd[Math.floor(r() * crowd.length)]; o.fillRect(x, y + Math.floor(r() * 2), 2, 2); }
    }
    o.fillStyle = C.band; o.fillRect(0, 27, W, 6);
    o.fillStyle = C.gold; o.fillRect(0, 33, W, 1);
    o.font = `5px ${FONT}`; o.textBaseline = 'top'; o.textAlign = 'center'; o.fillStyle = C.gold;
    o.fillText('KB SONICS', 30, 28); o.fillText('KB SONICS', 130, 28);
    // 마루
    o.fillStyle = C.wood; o.fillRect(0, 34, W, H - 34);
    for (let y = 36; y < H; y += 5) {
      o.fillStyle = C.wood2; o.fillRect(0, y, W, 1);
      const off2 = (y * 7) % 23;
      for (let x = off2; x < W; x += 23) { o.fillRect(x, y - 4, 1, 4); }
    }
    for (let i = 0; i < 90; i++) { o.fillStyle = C.wood3; o.fillRect(Math.floor(r() * W), 34 + Math.floor(r() * (H - 34)), 2, 1); }
    // 페인트존 · 자유투 원
    o.fillStyle = C.purple; o.fillRect(62, 46, 36, 54);
    o.fillStyle = C.line;
    o.fillRect(62, 46, 1, 54); o.fillRect(97, 46, 1, 54); o.fillRect(62, 99, 36, 1);
    for (let a = 0; a <= 180; a += 2) {
      const t = a * Math.PI / 180;
      o.fillRect(Math.round(80 + 18 * Math.cos(t)), Math.round(100 + 10 * Math.sin(t)), 1, 1);
    }
    // 베이스라인 · 3점 라인
    o.fillRect(0, 46, W, 1);
    for (let a = 0; a <= 180; a += 0.5) {
      const t = a * Math.PI / 180;
      o.fillRect(Math.round(ARC.cx + ARC.rx * Math.cos(t)), Math.round(ARC.cy + ARC.ry * Math.sin(t)), 1, 1);
    }
    // 백보드 (기둥은 관중석 뒤)
    o.fillStyle = '#3b3f46'; o.fillRect(78, 30, 4, 4);
    o.fillStyle = C.boardEdge; o.fillRect(59, 5, 42, 26);
    o.fillStyle = C.board; o.fillRect(60, 6, 40, 24);
    o.fillStyle = C.rim; o.fillRect(72, 17, 16, 1); o.fillRect(72, 28, 16, 1); o.fillRect(72, 17, 1, 12); o.fillRect(87, 17, 1, 12);
    BG = off;
  }

  // ---------------------------------------------------------------- 상태
  const S = {
    phase: 'idle', t0: 0, countT: 0, score: 0, made: 0, money: 0,
    shots: new Array(RACKS * BALLS).fill('pending'),
    spot: 0, ballInSpot: 0, walking: null, holding: false, holdT: 0, lastRelease: -1e9, armsUp: 0,
    streak: 0, fire: false, fireFlash: 0, balls: [], floats: [], parts: [], net: 0, timeUp: false, endT: 0,
    runId: null, ending: false,
  };
  const zoneW = () => 0.16 * (S.fire ? 1.5 : 1);
  const period = () => 1.05 - 0.06 * S.spot;       // 뒤로 갈수록 게이지가 조금 빨라진다
  const tri = x => 1 - Math.abs((x % 2) - 1);
  const power = () => tri(S.holdT * 2 / period());
  const remaining = now => Math.max(0, SECONDS - (now - S.t0) / 1000);
  const allShot = () => S.spot === RACKS - 1 && S.ballInSpot >= BALLS;

  function playerPos() {
    if (!S.walking) return SPOTS[S.spot];
    const w = S.walking, u = Math.min(1, w.t / w.dur);
    const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
    return spotXY(SPOT_DEG[w.from] + (SPOT_DEG[w.to] - SPOT_DEG[w.from]) * e);
  }
  const canShoot = now => S.phase === 'play' && !S.timeUp && !S.walking && S.ballInSpot < BALLS && now - S.lastRelease > 300;

  // ---------------------------------------------------------------- 슛
  function press(now) { if (canShoot(now) && !S.holding) { S.holding = true; S.holdT = 0; } }
  function release(now) {
    if (!S.holding) return;
    S.holding = false;
    const p = power(), c = ZONE_C[S.spot], half = zoneW() / 2, d = p - c, ad = Math.abs(d);
    let res;
    if (ad <= 0.03) res = 'swish';
    else if (ad <= half) res = 'make';
    else if (ad <= half + 0.07) res = Math.random() < 0.25 ? 'rollin' : 'rimout';
    else res = d < 0 ? 'short' : 'long';
    const money = S.ballInSpot === BALLS - 1;
    const idx = S.spot * BALLS + S.ballInSpot;
    const made = res === 'swish' || res === 'make' || res === 'rollin';
    if (made) { S.made++; if (money) S.money++; S.streak++; if (S.streak === 3) S.fireFlash = 1.2; if (S.streak >= 3) S.fire = true; }
    else { S.streak = 0; S.fire = false; }
    S.ballInSpot++; S.lastRelease = now; S.armsUp = 0.28;
    spawnBall(res, money, idx, made);
  }
  function spawnBall(res, money, idx, made) {
    const p = playerPos(), h = bodyH();
    const x0 = p.x, y0 = p.y - h - 6;
    let x1 = HOOP.x, y1 = HOOP.y - 1;
    if (res === 'rollin') x1 += 2;
    if (res === 'rimout') x1 += x0 < 80 ? -4 : 4;
    if (res === 'short') { y1 = HOOP.y + 7; x1 += (x0 - 80) * 0.08; }
    if (res === 'long') { y1 = 22; x1 += (Math.random() - 0.5) * 10; }
    const dist = Math.hypot(x1 - x0, y1 - y0);
    S.balls.push({
      res, money, idx, made, x0, y0, x1, y1, x: x0, y: y0, u: 0, dur: 0.62 + dist / 520,
      peak: (res === 'short' ? 22 : 34) + dist * 0.18, state: 'fly', t: 0, vx: 0, vy: 0, fire: S.fire,
    });
  }
  function land(b) {
    if (b.made) {
      if (b.res === 'rollin') { b.state = 'roll'; b.t = 0; return; }
      score(b);
    } else {
      S.shots[b.idx] = 'miss';
      b.state = 'bounce'; b.t = 0;
      if (b.res === 'long') { b.vx = (Math.random() - 0.5) * 50; b.vy = 25; }
      else if (b.res === 'short') { b.vx = (Math.random() - 0.5) * 20; b.vy = -15; }
      else { b.vx = b.x < 80 ? -45 : 45; b.vy = -55; }
      float(b.res === 'long' || b.res === 'short' ? 'BRICK' : 'RIM', '#c9bedb');
    }
  }
  function score(b) {
    S.score += b.money ? 2 : 1;
    S.shots[b.idx] = 'made';
    b.state = 'drop'; b.x = HOOP.x; b.y = HOOP.y; b.t = 0;
    S.net = 0.45;
    float(b.res === 'swish' ? (b.money ? 'MONEY!' : 'SWISH!') : (b.money ? '+2' : '+1'), b.money ? C.gold : C.green);
    if (navigator.vibrate) { try { navigator.vibrate(b.money ? [20, 40, 20] : 15); } catch (e) { /* 무시 */ } }
  }
  function float(str, color) { S.floats.push({ str, color, x: HOOP.x, y: HOOP.y + 20, t: 0 }); }

  // ---------------------------------------------------------------- 업데이트
  function update(dt, now) {
    if (S.phase === 'count') {
      S.countT -= dt;
      if (S.countT <= 0) { S.phase = 'play'; S.t0 = now; }
    }
    if (S.phase === 'play') {
      if (!S.timeUp && remaining(now) <= 0) { S.timeUp = true; S.holding = false; }
      if (S.holding) S.holdT += dt;
      if (S.walking) {
        S.walking.t += dt;
        if (S.walking.t >= S.walking.dur) { S.spot = S.walking.to; S.walking = null; S.ballInSpot = 0; }
      } else if (S.ballInSpot >= BALLS && S.spot < RACKS - 1 && now - S.lastRelease > 380 && !S.timeUp) {
        S.walking = { from: S.spot, to: S.spot + 1, t: 0, dur: 0.55 };
      }
      if ((S.timeUp || allShot()) && S.balls.every(b => b.state === 'done') && !S.ending) {
        S.ending = true; S.endT = now; S.phase = 'end';
        finish();
      }
    }
    S.armsUp = Math.max(0, S.armsUp - dt);
    S.net = Math.max(0, S.net - dt);
    S.fireFlash = Math.max(0, S.fireFlash - dt);
    for (const b of S.balls) {
      if (b.state === 'fly') {
        b.u += dt / b.dur;
        const u = Math.min(1, b.u);
        b.x = b.x0 + (b.x1 - b.x0) * u;
        b.y = b.y0 + (b.y1 - b.y0) * u - b.peak * 4 * u * (1 - u);
        if (b.fire && Math.random() < 0.9) S.parts.push({ x: b.x + (Math.random() - 0.5) * 3, y: b.y + (Math.random() - 0.5) * 3, t: 0, c: Math.random() < 0.5 ? C.fire : C.gold });
        if (b.u >= 1) land(b);
      } else if (b.state === 'roll') {
        b.t += dt;
        const a = b.t * 14;
        b.x = HOOP.x + 5 * Math.cos(a); b.y = HOOP.y - 1 + 1.5 * Math.sin(a);
        if (b.t > 0.45) score(b);
      } else if (b.state === 'drop') {
        b.t += dt; b.y += 55 * dt;
        if (b.t > 0.55) b.state = 'done';
      } else if (b.state === 'bounce') {
        b.t += dt; b.vy += 170 * dt; b.x += b.vx * dt; b.y += b.vy * dt;
        if (b.y > 60 && b.vy > 0) { b.vy *= -0.45; b.vx *= 0.7; }
        if (b.t > 0.9) b.state = 'done';
      }
    }
    S.parts = S.parts.filter(p => (p.t += dt) < 0.3);
    S.floats = S.floats.filter(f => { f.t += dt; f.y -= 14 * dt; return f.t < 0.9; });
  }

  // ---------------------------------------------------------------- 그리기
  function bodyParts() {
    return CFG.pos === 'G' ? { jh: 8, lh: 3 } : CFG.pos === 'C' ? { jh: 10, lh: 5 } : { jh: 9, lh: 4 };
  }
  function bodyH() { const b = bodyParts(); return 5 + 1 + b.jh + 4 + b.lh + 2; }

  function drawBall(x, y, s, money) {
    const base = money ? C.money : C.ball, dk = money ? C.moneyDark : C.ballDark;
    const rows = s >= 5 ? [3, 5, 5, 5, 3] : s === 4 ? [2, 4, 4, 2] : [1, 3, 1];
    const top = Math.round(y - rows.length / 2), cx = Math.round(x);
    rows.forEach((w, i) => { px(cx - Math.floor(w / 2), top + i, w, 1, base); });
    if (s >= 4) { px(cx - Math.floor(rows[1] / 2), top + Math.floor(rows.length / 2), rows[1], 1, dk); px(cx, top, 1, rows.length, dk); }
  }

  function drawPlayer(p, now) {
    const { jh, lh } = bodyParts();
    const h = bodyH();
    const x = Math.round(p.x), feet = Math.round(p.y);
    let y = feet - h;
    const walking = !!S.walking;
    const up = S.holding || S.armsUp > 0;
    // 그림자
    g.fillStyle = 'rgba(0,0,0,.28)'; g.fillRect(x - 6, feet - 1, 12, 2); g.fillRect(x - 4, feet + 1, 8, 1);
    // 팔 (들었을 때는 머리 위)
    if (up) {
      px(x - 6, y - 5, 2, 12, C.skin); px(x + 4, y - 5, 2, 12, C.skin);
      drawBall(x, y - 7, 5, S.ballInSpot === BALLS - 1 && S.holding);
    }
    // 머리 (뒤통수)
    px(x - 3, y, 6, 5, C.hair); px(x - 4, y + 2, 1, 2, C.skin); px(x + 3, y + 2, 1, 2, C.skin);
    px(x - 1, y + 5, 2, 1, C.skin2);
    y += 6;
    // 유니폼 상의 (등)
    px(x - 5, y, 10, jh, C.purple);
    px(x - 5, y, 1, jh, C.gold); px(x + 4, y, 1, jh, C.gold); px(x - 2, y, 4, 1, C.gold);
    if (CFG.num) pixelNumber(String(CFG.num), x, y + 2, C.gold);
    if (!up) { px(x - 7, y + 1, 2, jh - 1, C.skin); px(x + 5, y + 1, 2, jh - 1, C.skin); }
    y += jh;
    // 반바지
    px(x - 5, y, 10, 4, C.purple2); px(x - 5, y, 1, 4, C.gold); px(x + 4, y, 1, 4, C.gold);
    y += 4;
    // 다리 · 신발 (걸을 때 번갈아)
    const step = walking ? (Math.floor(now / 120) % 2) : 0;
    px(x - 4, y - step, 3, lh, C.skin); px(x + 1, y - (1 - step) * (walking ? 1 : 0), 3, lh, C.skin);
    y += lh;
    px(x - 4, y - step, 3, 2, C.shoe); px(x + 1, y - (walking ? 1 - step : 0), 3, 2, C.shoe);
  }

  function drawRacks() {
    SPOTS.forEach((sp, i) => {
      const rx = Math.round(sp.x + (sp.x < 79 ? -14 : 9)), ry = Math.round(sp.y - 4);
      px(rx, ry + 4, 6, 1, '#6b6f78'); px(rx, ry + 5, 1, 2, '#6b6f78'); px(rx + 5, ry + 5, 1, 2, '#6b6f78');
      const left2 = i < S.spot ? 0 : i === S.spot ? BALLS - S.ballInSpot : BALLS;
      for (let k = 0; k < left2; k++) {
        const isMoney = (BALLS - left2 + k) === BALLS - 1;
        const bx = rx + 1 + (k % 3) * 2, by = ry + 2 - Math.floor(k / 3) * 2;
        px(bx, by, 2, 2, isMoney ? C.money : C.ball);
      }
    });
  }

  function drawHoopBack() { px(73, HOOP.y - 2, 14, 1, C.rimBack); }
  function drawHoopFront(now) {
    const sway = S.net > 0 ? Math.sin(now / 30) * S.net * 2 : 0;
    g.fillStyle = C.net;
    for (let i = 0; i <= 4; i++) {
      const xt = 73 + i * 3.5, xb = 76 + i * 2 + sway;
      for (let k = 0; k <= 9; k++) { const u = k / 9; g.fillRect(Math.round(xt + (xb - xt) * u), HOOP.y + 1 + k, 1, 1); }
    }
    for (let k = 3; k <= 9; k += 3) { const w = 14 - k * 0.6; g.fillRect(Math.round(80 - w / 2 + sway * k / 9), HOOP.y + 1 + k, Math.round(w), 1); }
    px(72, HOOP.y, 16, 2, C.rim);
  }

  function drawHUD(now) {
    g.fillStyle = 'rgba(15,11,22,.75)'; g.fillRect(2, 2, 46, 20); g.fillRect(112, 2, 46, 20);
    g.font = `5px ${FONT}`; g.textBaseline = 'top'; g.textAlign = 'left'; g.fillStyle = '#b5a9c7';
    g.fillText('SCORE', 5, 4); g.fillText('TIME', 115, 4);
    text(String(S.score), 5, 12, C.gold, 8);
    const rem = S.phase === 'play' ? remaining(now) : S.phase === 'idle' || S.phase === 'count' ? SECONDS : 0;
    const secs = Math.ceil(rem);
    const red = S.phase === 'play' && rem <= 10;
    if (!(red && rem <= 5 && Math.floor(now / 250) % 2)) text(String(secs).padStart(2, '0'), 115, 12, red ? '#f87171' : C.white, 8);
    // 랙 진행 (아래)
    const y0 = 178, gw = 5 * 4 + 3;
    const x0 = Math.round((W - (RACKS * gw - 3)) / 2);
    for (let r = 0; r < RACKS; r++) for (let k = 0; k < BALLS; k++) {
      const st = S.shots[r * BALLS + k], m = k === BALLS - 1;
      const x = x0 + r * gw + k * 4;
      const col = st === 'made' ? (m ? C.gold : C.green) : st === 'miss' ? C.miss : C.slot;
      px(x, y0, 3, 3, col);
      if (st === 'pending') { g.fillStyle = m ? C.moneyDark : C.slotLine; g.fillRect(x, y0, 3, 1); }
    }
  }

  function drawGauge(now) {
    const x = 20, y = 189, w = 120, h = 8;
    const active = S.phase === 'play' && !S.timeUp;
    g.globalAlpha = active ? 1 : 0.45;
    px(x - 1, y - 1, w + 2, h + 2, '#0f0b16');
    px(x, y, w, h, '#2b2240');
    const c = ZONE_C[S.spot], half = zoneW() / 2;
    px(x + Math.round((c - half) * w), y, Math.round(half * 2 * w), h, S.fire ? C.fire : C.green);
    px(x + Math.round((c - 0.03) * w), y, Math.max(1, Math.round(0.06 * w)), h, S.fire ? C.gold : '#a7f3d0');
    if (S.holding) {
      const ix = x + Math.round(power() * (w - 1));
      px(ix - 1, y - 3, 3, h + 6, C.white); px(ix, y - 4, 1, 1, C.white);
    }
    g.globalAlpha = 1;
    if (active && !S.holding && !S.walking && S.ballInSpot < BALLS && Math.floor(now / 500) % 2 === 0 && S.made + S.shots.filter(s => s === 'miss').length < 2) {
      text('HOLD', 80, 199, '#c9bedb', 5, 'center');
    }
  }

  function draw(now) {
    if (!BG) return;
    g.drawImage(BG, 0, 0);
    drawHoopBack();
    for (const b of S.balls) if (b.state === 'drop' || b.state === 'roll') drawBall(b.x, b.y, 3, b.money);
    drawHoopFront(now);
    drawRacks();
    const p = playerPos();
    // 공이 선수보다 뒤(위)에 있으면 먼저 그린다
    for (const b of S.balls) if ((b.state === 'fly' || b.state === 'bounce') && b.y < p.y - 30) drawBall(b.x, b.y, ballSize(b), b.money);
    drawPlayer(p, now);
    for (const b of S.balls) if ((b.state === 'fly' || b.state === 'bounce') && b.y >= p.y - 30) drawBall(b.x, b.y, ballSize(b), b.money);
    for (const q of S.parts) { g.globalAlpha = 1 - q.t / 0.3; px(q.x, q.y, 1, 1, q.c); }
    g.globalAlpha = 1;
    for (const f of S.floats) { g.globalAlpha = Math.min(1, 2 * (1 - f.t / 0.9)); text(f.str, f.x, f.y, f.color, 6, 'center'); }
    g.globalAlpha = 1;
    drawHUD(now);
    drawGauge(now);
    if (S.fire && S.phase === 'play' && (S.fireFlash > 0 ? Math.floor(now / 120) % 2 === 0 : true)) text('ON FIRE', 80, 108, C.fire, 6, 'center');
    if (S.phase === 'idle') {
      g.fillStyle = 'rgba(15,11,22,.55)'; g.fillRect(0, 34, W, 140);
      text('3PT', 80, 70, C.gold, 16, 'center');
      text('CONTEST', 80, 92, C.gold, 8, 'center');
      text('HOLD & RELEASE', 80, 120, C.white, 5, 'center');
    } else if (S.phase === 'count') {
      const n = Math.ceil(S.countT / 0.6);
      text(n > 3 ? '' : n >= 1 ? String(n) : '', 80, 92, C.white, 16, 'center');
    } else if (S.phase === 'play' && now - S.t0 < 600) {
      text('GO!', 80, 92, C.gold, 16, 'center');
    } else if (S.phase === 'end') {
      g.fillStyle = 'rgba(15,11,22,.55)'; g.fillRect(0, 60, W, 70);
      text(allShot() && !S.timeUp ? 'FINISH!' : 'TIME UP!', 80, 78, C.gold, 10, 'center');
      text(`${S.score} PTS`, 80, 100, C.white, 8, 'center');
    }
  }
  const ballSize = b => b.state === 'bounce' ? 3 : Math.max(3, Math.round(5 - 2 * Math.min(1, b.u)));

  function loop(ts) {
    const now = ts;
    const dt = Math.min(0.05, (now - (loop.last || now)) / 1000);
    loop.last = now;
    update(dt, now);
    draw(now);
    requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------- 입력
  const stage = document.getElementById('stage');
  stage.addEventListener('pointerdown', e => { e.preventDefault(); stage.setPointerCapture?.(e.pointerId); press(performance.now()); });
  const up = e => { e.preventDefault(); release(performance.now()); };
  stage.addEventListener('pointerup', up);
  stage.addEventListener('pointercancel', up);
  stage.addEventListener('contextmenu', e => e.preventDefault());
  window.addEventListener('keydown', e => { if (e.code === 'Space' && !e.repeat && S.phase === 'play') { e.preventDefault(); press(performance.now()); } });
  window.addEventListener('keyup', e => { if (e.code === 'Space') { e.preventDefault(); release(performance.now()); } });

  // ---------------------------------------------------------------- 서버 / 화면 버튼
  const $ = id => document.getElementById(id);
  const startBtn = $('start'), againBtn = $('again'), result = $('result'), hint = $('hint'), err = $('err');
  function showErr(msg) { err.textContent = msg; err.classList.toggle('hidden', !msg); }

  function reset() {
    Object.assign(S, {
      phase: 'idle', score: 0, made: 0, money: 0, shots: new Array(RACKS * BALLS).fill('pending'),
      spot: 0, ballInSpot: 0, walking: null, holding: false, holdT: 0, lastRelease: -1e9, armsUp: 0,
      streak: 0, fire: false, fireFlash: 0, balls: [], floats: [], parts: [], net: 0, timeUp: false, runId: null, ending: false,
    });
  }

  async function start() {
    showErr('');
    startBtn.disabled = true; againBtn.disabled = true;
    try {
      const r = await fetch('/arcade/runs', { method: 'POST', headers: { 'Accept': 'application/json' } });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || '게임을 시작하지 못했어요.');
      reset();
      S.runId = data.run_id;
      S.phase = 'count'; S.countT = 1.8;
      startBtn.classList.add('hidden'); result.classList.add('hidden'); hint.classList.remove('hidden');
      stage.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {
      showErr(e.message);
    } finally {
      startBtn.disabled = false; againBtn.disabled = false;
    }
  }

  async function finish() {
    $('r-score').textContent = S.score;
    $('r-made').textContent = `25개 중 ${S.made}개 성공` + (S.money ? ` · 머니볼 ${S.money}개` : '');
    $('r-title').textContent = allShot() && !S.timeUp ? '25개 다 던졌어요!' : '타임 업!';
    $('r-msg').textContent = '기록 저장 중…';
    hint.classList.add('hidden');
    setTimeout(() => result.classList.remove('hidden'), 700);
    try {
      const r = await fetch(`/arcade/runs/${S.runId}/finish`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ made: S.made, money: S.money }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || '기록을 저장하지 못했어요.');
      const msg = [];
      if (d.new_season_best && d.score > 0) msg.push('🎉 시즌 개인 신기록!');
      else if (d.new_week_best && d.score > 0) msg.push('🔥 이번 주 개인 최고!');
      msg.push(`이번 주 최고 ${d.week_best}점 · ${d.week_rank}위`);
      $('r-msg').textContent = msg.join(' ');
      $('my-week-score').textContent = d.week_best; $('my-week-rank').textContent = d.week_rank; $('my-week').classList.remove('hidden');
      if (window.htmx) htmx.ajax('GET', '/arcade/ranking?tab=week', { target: '#ranking', swap: 'innerHTML' });
    } catch (e) {
      $('r-msg').textContent = e.message;
    }
  }

  startBtn.addEventListener('click', start);
  againBtn.addEventListener('click', start);

  // 폰트가 준비되면 배경을 그리고 시작 (폰트를 못 받아도 1.5초 뒤 기본 글꼴로)
  let booted = false;
  const boot = () => { if (booted) return; booted = true; renderBG(); requestAnimationFrame(loop); };
  if (document.fonts && document.fonts.load) {
    Promise.race([document.fonts.load(`8px ${FONT}`), new Promise(r => setTimeout(r, 1500))]).then(boot, boot);
  } else boot();

  window.__arcade = S;   // 디버깅용
})();
