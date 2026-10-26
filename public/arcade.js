/* KB SONICS — 픽셀 3점슛 콘테스트
 * 160×208 캔버스에 직접 그린다 (이미지 파일 없음). 결과(성공 여부)는 손을 뗀 순간 정해지고,
 * 화면 점수는 공이 림에 닿을 때 올라간다. 서버에는 판 시작/종료를 한 번씩만 보낸다.
 * 종료 때 슛 기록(26칸 코드)과 점수 흐름을 보내고, 점수는 서버가 슛 기록으로 다시 계산한다.
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

  // 팀 테마 색 (base.html 의 kbApplyTeam 이 정한 CSS 변수). 못 읽으면 레이커스 색
  const cssRGB = (name, fb) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim().split(/\s+/).map(Number);
    return v.length === 3 && v.every(n => !isNaN(n)) ? `rgb(${v.join(',')})` : fb;
  };
  const C = {
    wall: cssRGB('--t-bg', '#1b1027'), band: cssRGB('--o900', '#2a1441'), gold: cssRGB('--bright', '#FDB927'),
    purple: cssRGB('--o600', '#552583'), purple2: cssRGB('--o700', '#46206c'), paintLine: cssRGB('--o400', '#8f5cc4'),
    wood: '#c98a4b', wood2: '#b97b3f', wood3: '#d69a5a', line: '#f4efe6',
    skin: '#d9a273', skin2: '#b98256', hair: '#2a1c14', shoe: '#f4f4f4',
    ball: '#e2702a', ballDark: '#8f3f12', money: '#FDB927', moneyDark: '#9a6a08',   // 머니볼은 팀과 상관없이 골드
    rim: '#ff6a1a', rimBack: '#b8460f', board: '#f2f2f2', boardEdge: '#8e98a3', net: '#ffffff',
    deep: '#38bdf8', deepDark: '#0369a1',                                               // 로고샷 공
    green: '#34d399', fire: '#fb923c', dark: '#0f0b16', slot: '#2b2240', slotLine: '#5a4f6d', miss: '#4a3a5e', white: '#ffffff',
  };
  const FONT = '"Press Start 2P", ui-monospace, monospace';

  // ---------------------------------------------------------------- 코트 기하
  const HOOP = { x: 80, y: 40 };
  const ARC = { cx: 80, cy: 46, rx: 68, ry: 112 };
  const SPOT_DEG = [170, 135, 90, 45, 10];          // 왼쪽 코너 → 오른쪽 코너
  const ZONE_C = [0.58, 0.65, 0.72, 0.65, 0.58, 0.85];   // 지점별 '딱 맞는 힘' (탑이 가장 멀고, 로고샷은 더)
  const ZONE_MUL = [1.35, 1.0, 0.75, 1.0, 1.35, 0.6];    // 지점별 성공 구간 배율: 코너 넓게, 탑 좁게, 로고샷 가장 좁게
  const DEEP = RACKS;                                    // 여섯 번째 '지점' = 로고샷 (공 1개, 3점)
  const NSHOTS = RACKS * BALLS + 1;
  const LOGO = { x: 80, y: 168 };
  const SWISH_COMBO = 3;                                 // 스위시가 3번 이어질 때마다 +1 (서버 score_shots 와 같은 규칙)

  // ---------------------------------------------------------------- 난이도 (2026-10 상향: 평균 22.5점 → 약 10점 목표)
  const DIFF = {
    zone: 0.07,        // 성공 구간 폭 (예전 0.16)
    swish: 0.012,      // 스위시 반폭 (예전 0.03)
    rim: 0.04,         // 성공 구간 밖 '림 맞음' 폭 (예전 0.07)
    rollIn: 0.15,      // 림 맞고 들어갈 확률 (예전 0.25)
    fire: 1.25,        // ON FIRE 때 성공 구간 배율 (예전 1.5)
    period: 0.8,       // 게이지 왕복 주기(초), 지점마다 -periodStep (예전 1.05)
    periodStep: 0.06,
    shift: 0.10,       // 슛마다 성공 구간 위치가 ±shift/2 만큼 바뀐다 (예전 고정)
  };
  const spotXY = deg => {
    const t = deg * Math.PI / 180;
    return { x: ARC.cx + (ARC.rx + 6) * Math.cos(t), y: ARC.cy + (ARC.ry + 6) * Math.sin(t) };
  };
  const SPOTS = SPOT_DEG.map(spotXY);
  const posOf = i => i === DEEP ? LOGO : SPOTS[i];
  const ballsAt = i => i === DEEP ? 1 : BALLS;

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
    // 로고샷 지점 (센터 쪽 팀 로고)
    for (let a = 0; a < 360; a += 6) {
      const t = a * Math.PI / 180;
      o.fillStyle = C.gold; o.fillRect(Math.round(LOGO.x + 9 * Math.cos(t)), Math.round(LOGO.y + 5 * Math.sin(t)), 1, 1);
    }
    o.fillStyle = C.purple; o.fillRect(LOGO.x - 5, LOGO.y - 2, 10, 5);
    o.font = `4px ${FONT}`; o.textAlign = 'center'; o.fillStyle = C.gold; o.fillText('KB', LOGO.x, LOGO.y - 1);
    // 백보드 (기둥은 관중석 뒤)
    o.fillStyle = '#3b3f46'; o.fillRect(78, 30, 4, 4);
    o.fillStyle = C.boardEdge; o.fillRect(59, 5, 42, 26);
    o.fillStyle = C.board; o.fillRect(60, 6, 40, 24);
    o.fillStyle = C.rim; o.fillRect(72, 17, 16, 1); o.fillRect(72, 28, 16, 1); o.fillRect(72, 17, 1, 12); o.fillRect(87, 17, 1, 12);
    BG = off;
  }

  // ---------------------------------------------------------------- 소리 (Web Audio 로 합성, 파일 없음)
  const SND = (() => {
    let ac = null, nbuf = null, muted = false;
    try { muted = localStorage.getItem('arcade-sound') === 'off'; } catch (e) { /* 저장소 막힘 */ }
    function ctx() {
      if (muted) return null;
      if (!ac) {
        const A = window.AudioContext || window.webkitAudioContext;
        if (!A) return null;
        try { ac = new A(); } catch (e) { return null; }
      }
      if (ac.state === 'suspended') ac.resume();
      return ac;
    }
    function tone(f, dur, type = 'square', vol = 0.1, f2 = null, delay = 0) {
      const a = ctx(); if (!a) return;
      const t = a.currentTime + delay, o = a.createOscillator(), gn = a.createGain();
      o.type = type; o.frequency.setValueAtTime(f, t);
      if (f2) o.frequency.exponentialRampToValueAtTime(f2, t + dur);
      gn.gain.setValueAtTime(vol, t); gn.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(gn).connect(a.destination); o.start(t); o.stop(t + dur + 0.02);
    }
    function noise(dur, vol, freq, type = 'bandpass', q = 1, delay = 0, attack = 0.005) {
      const a = ctx(); if (!a) return;
      if (!nbuf) {
        nbuf = a.createBuffer(1, a.sampleRate, a.sampleRate);
        const d = nbuf.getChannelData(0);
        for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      }
      const t = a.currentTime + delay, src = a.createBufferSource(), f = a.createBiquadFilter(), gn = a.createGain();
      src.buffer = nbuf; src.loop = true; f.type = type; f.frequency.value = freq; f.Q.value = q;
      gn.gain.setValueAtTime(0.0001, t); gn.gain.exponentialRampToValueAtTime(vol, t + attack);
      gn.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      src.connect(f).connect(gn).connect(a.destination); src.start(t); src.stop(t + dur + 0.05);
    }
    return {
      unlock: () => { ctx(); },
      get muted() { return muted; },
      toggle() {
        muted = !muted;
        try { localStorage.setItem('arcade-sound', muted ? 'off' : 'on'); } catch (e) { /* 무시 */ }
        if (muted && ac) ac.suspend();
      },
      release: () => tone(260, 0.06, 'triangle', 0.06, 420),
      swish: () => noise(0.28, 0.35, 6000, 'highpass', 0.7),
      net: () => { tone(700, 0.05, 'square', 0.04); noise(0.2, 0.22, 4500, 'highpass', 0.7, 0.03); },
      rim: () => { tone(620, 0.16, 'square', 0.07, 560); tone(930, 0.12, 'triangle', 0.05, null, 0.01); },
      brick: () => tone(140, 0.14, 'square', 0.09, 70),
      money: () => { tone(1046, 0.08, 'square', 0.05); tone(1568, 0.14, 'square', 0.05, null, 0.08); },
      beep: hi => tone(hi ? 988 : 523, hi ? 0.25 : 0.12, 'square', 0.07),
      buzzer: () => { tone(155, 0.8, 'sawtooth', 0.11); tone(158, 0.8, 'square', 0.05); },
      cheer: big => {                                     // 관중 함성
        noise(big ? 1.6 : 1.0, big ? 0.3 : 0.18, 1100, 'bandpass', 0.6, 0, 0.25);
        noise(big ? 1.4 : 0.8, 0.12, 2600, 'bandpass', 0.8, 0.05, 0.3);
      },
      fanfare: () => [523, 659, 784, 1046].forEach((f, i) => tone(f, 0.16, 'square', 0.05, null, i * 0.1)),
    };
  })();

  // ---------------------------------------------------------------- 진동
  // 안드로이드: navigator.vibrate. 아이폰(사파리)은 vibrate 가 없어서, iOS 18+ 의 스위치 체크박스를
  // 누를 때 나는 햅틱을 빌려 쓴다 — 화면을 만진 그 순간에만 되므로 슛을 놓을 때(tap)만 울린다.
  const HAPTIC = (() => {
    const canVibrate = typeof navigator.vibrate === 'function';
    const vib = p => { try { navigator.vibrate(p); } catch (e) { /* 무시 */ } };
    function iosTap() {
      const label = document.createElement('label'), input = document.createElement('input');
      label.setAttribute('aria-hidden', 'true'); label.style.display = 'none';
      input.type = 'checkbox'; input.setAttribute('switch', '');
      label.appendChild(input); document.head.appendChild(label);
      try { label.click(); } finally { label.remove(); }
    }
    return {
      tap: () => (canVibrate ? vib(8) : iosTap()),      // 손을 뗀 순간 (사용자 입력 안에서 호출)
      buzz: p => { if (canVibrate) vib(p); },            // 골·머니볼 (안드로이드만)
    };
  })();

  // ---------------------------------------------------------------- 상태
  const S = {
    phase: 'idle', t0: 0, countT: 0, score: 0, made: 0, money: 0,
    shots: new Array(RACKS * BALLS).fill('pending'),
    spot: 0, ballInSpot: 0, walking: null, holding: false, holdT: 0, lastRelease: -1e9, armsUp: 0,
    streak: 0, fire: false, fireFlash: 0, balls: [], floats: [], parts: [], net: 0, timeUp: false, endT: 0,
    runId: null, ending: false, target: ZONE_C[0],
  };
  const zoneW = () => DIFF.zone * ZONE_MUL[S.spot] * (S.fire ? DIFF.fire : 1);
  const period = () => DIFF.period - DIFF.periodStep * S.spot;   // 뒤로 갈수록 게이지가 빨라진다
  // 이번 공의 성공 구간 중심 (공마다 새로 뽑고 게이지에 보여준다)
  const zoneC = () => S.target;
  function newTarget() {
    const c = ZONE_C[S.spot] + (Math.random() - 0.5) * DIFF.shift;
    S.target = Math.min(0.9, Math.max(0.3, c));
  }
  const tri = x => 1 - Math.abs((x % 2) - 1);
  const power = () => tri(S.holdT * 2 / period());
  const remaining = now => Math.max(0, SECONDS - (now - S.t0) / 1000);
  const allShot = () => S.spot === DEEP && S.ballInSpot >= 1;

  function playerPos() {
    if (!S.walking) return posOf(S.spot);
    const w = S.walking, u = Math.min(1, w.t / w.dur);
    const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
    if (w.to === DEEP) {                       // 오른쪽 코너 → 로고: 곧장 걸어간다
      const a = posOf(w.from);
      return { x: a.x + (LOGO.x - a.x) * e, y: a.y + (LOGO.y - a.y) * e };
    }
    return spotXY(SPOT_DEG[w.from] + (SPOT_DEG[w.to] - SPOT_DEG[w.from]) * e);
  }
  const canShoot = now => S.phase === 'play' && !S.timeUp && !S.walking && S.ballInSpot < ballsAt(S.spot) && now - S.lastRelease > 300;

  // ---------------------------------------------------------------- 슛
  function press(now) { if (canShoot(now) && !S.holding) { S.holding = true; S.holdT = 0; } }
  function release(now) {
    if (!S.holding) return;
    S.holding = false;
    const p = power(), c = zoneC(), half = zoneW() / 2, d = p - c, ad = Math.abs(d);
    let res;
    if (ad <= DIFF.swish) res = 'swish';
    else if (ad <= half) res = 'make';
    else if (ad <= half + DIFF.rim) res = Math.random() < DIFF.rollIn ? 'rollin' : 'rimout';
    else res = d < 0 ? 'short' : 'long';
    const deep = S.spot === DEEP;
    const money = !deep && S.ballInSpot === BALLS - 1;
    const idx = deep ? NSHOTS - 1 : S.spot * BALLS + S.ballInSpot;
    const made = res === 'swish' || res === 'make' || res === 'rollin';
    S.codes[idx] = { swish: 'S', make: 'M', rollin: 'R' }[res] || 'X';
    let bonus = 0;
    if (made) {
      S.made++; if (money) S.money++; if (deep) S.deep = 1;
      S.streak++;
      if (S.streak === 3) { S.fireFlash = 1.2; SND.cheer(false); }
      if (S.streak >= 3) S.fire = true;
      S.swishRun = res === 'swish' ? S.swishRun + 1 : 0;
      if (S.swishRun && S.swishRun % SWISH_COMBO === 0) { bonus = 1; S.combos++; }
    } else { S.streak = 0; S.fire = false; S.swishRun = 0; }
    S.ballInSpot++; S.lastRelease = now; S.armsUp = 0.28;
    SND.release();
    HAPTIC.tap();
    spawnBall(res, deep ? 2 : money ? 1 : 0, idx, made, bonus);
    if (S.ballInSpot < ballsAt(S.spot)) newTarget();
  }
  function spawnBall(res, kind, idx, made, bonus) {
    const p = playerPos(), h = bodyH();
    const x0 = p.x, y0 = p.y - h - 6;
    let x1 = HOOP.x, y1 = HOOP.y - 1;
    if (res === 'rollin') x1 += 2;
    if (res === 'rimout') x1 += x0 < 80 ? -4 : 4;
    if (res === 'short') { y1 = HOOP.y + 7; x1 += (x0 - 80) * 0.08; }
    if (res === 'long') { y1 = 22; x1 += (Math.random() - 0.5) * 10; }
    const dist = Math.hypot(x1 - x0, y1 - y0);
    S.balls.push({
      res, kind, bonus, idx, made, buzzer: false, x0, y0, x1, y1, x: x0, y: y0, u: 0, dur: 0.62 + dist / 520,
      peak: (res === 'short' ? 22 : 34) + dist * 0.18, state: 'fly', t: 0, vx: 0, vy: 0, fire: S.fire,
    });
  }
  function land(b) {
    if (b.made) {
      if (b.res === 'rollin') { b.state = 'roll'; b.t = 0; S.rimShake = 0.25; SND.rim(); return; }
      score(b);
    } else {
      S.shots[b.idx] = 'miss';
      b.state = 'bounce'; b.t = 0;
      if (b.res === 'long') { b.vx = (Math.random() - 0.5) * 50; b.vy = 25; }
      else if (b.res === 'short') { b.vx = (Math.random() - 0.5) * 20; b.vy = -15; }
      else { b.vx = b.x < 80 ? -45 : 45; b.vy = -55; }
      const brick = b.res === 'long' || b.res === 'short';
      if (brick) SND.brick(); else { SND.rim(); S.rimShake = 0.35; }
      float(brick ? 'BRICK' : 'RIM OUT', '#c9bedb');
    }
  }
  function score(b) {
    const pts = (b.kind === 2 ? 3 : b.kind === 1 ? 2 : 1) + b.bonus;
    S.score += pts;
    S.shots[b.idx] = 'made';
    S.ev.push([Math.round(performance.now() - S.t0), S.score]);
    b.state = 'drop'; b.x = HOOP.x; b.y = HOOP.y; b.t = 0;
    S.net = 0.45;
    const swish = b.res === 'swish';
    const label = b.kind === 2 ? 'LOGO +3!' : b.kind === 1 ? (swish ? 'MONEY!' : '+2') : (swish ? 'SWISH!' : '+1');
    float(label, b.kind === 2 ? C.deep : b.kind === 1 ? C.gold : C.green);
    if (b.bonus) float('COMBO +1', C.fire);
    if (swish) SND.swish(); else SND.net();
    if (b.kind) { SND.money(); S.shake = 0.3; }
    if (b.buzzer) { float('BUZZER BEATER!', C.gold, 7); SND.cheer(true); S.shake = 0.45; }
    HAPTIC.buzz(b.kind || b.buzzer ? [20, 40, 20] : 15);
  }
  function float(str, color, size = 6) {
    const stack = S.floats.filter(f => f.t < 0.5).length;
    S.floats.push({ str, color, size, x: HOOP.x, y: HOOP.y + 20 + stack * 9, t: 0 });
  }

  // ---------------------------------------------------------------- 업데이트
  function update(dt, now) {
    if (S.phase === 'count') {
      S.countT -= dt;
      const n = Math.ceil(S.countT / 0.6);
      if (n !== S.lastCount && n >= 1 && n <= 3) SND.beep(false);
      S.lastCount = n;
      if (S.countT <= 0) { S.phase = 'play'; S.t0 = now; SND.beep(true); }
    }
    if (S.phase === 'play') {
      if (!S.timeUp && remaining(now) <= 0) {
        S.timeUp = true; S.holding = false;
        SND.buzzer();
        // 버저 전에 손을 떠난 공이 들어가면 버저비터: 잠깐 슬로모션
        for (const b of S.balls) if (b.state === 'fly' && b.made) { b.buzzer = true; S.slow = 1.1; }
      }
      if (S.holding) S.holdT += dt;
      if (S.walking) {
        S.walking.t += dt;
        if (S.walking.t >= S.walking.dur) { S.spot = S.walking.to; S.walking = null; S.ballInSpot = 0; newTarget(); }
      } else if (S.ballInSpot >= ballsAt(S.spot) && S.spot < DEEP && now - S.lastRelease > 380 && !S.timeUp) {
        const to = S.spot + 1;
        S.walking = { from: S.spot, to, t: 0, dur: to === DEEP ? 0.8 : 0.55 };
        if (to === DEEP) float('LOGO SHOT!', C.deep);
      }
      if ((S.timeUp || allShot()) && S.balls.every(b => b.state === 'done') && !S.ending) {
        S.ending = true; S.endT = now; S.phase = 'end';
        if (allShot() && !S.timeUp) SND.fanfare();
        finish();
      }
    }
    // ON FIRE: 손에 든 공에서 불꽃이 올라간다
    if (S.fire && S.phase === 'play' && !S.walking && Math.random() < 0.7) {
      const p = playerPos(), h = bodyH(), up2 = S.holding || S.armsUp > 0;
      const bx = p.x + (up2 ? 0 : 6), by = p.y - h + (up2 ? -7 : 8);
      S.parts.push({ x: bx + (Math.random() - 0.5) * 5, y: by, t: 0, vy: -18 - Math.random() * 14, c: Math.random() < 0.5 ? C.fire : C.gold });
    }
    S.armsUp = Math.max(0, S.armsUp - dt);
    S.rimShake = Math.max(0, S.rimShake - dt);
    S.shake = Math.max(0, S.shake - dt);
    S.net = Math.max(0, S.net - dt);
    S.fireFlash = Math.max(0, S.fireFlash - dt);
    for (const b of S.balls) {
      if (b.state === 'fly') {
        b.u += dt / b.dur;
        const u = Math.min(1, b.u);
        b.x = b.x0 + (b.x1 - b.x0) * u;
        b.y = b.y0 + (b.y1 - b.y0) * u - b.peak * 4 * u * (1 - u);
        if (b.fire) for (let k = 0; k < 2; k++) S.parts.push({ x: b.x + (Math.random() - 0.5) * 4, y: b.y + (Math.random() - 0.5) * 4, t: 0, vy: -6, c: Math.random() < 0.5 ? C.fire : C.gold });
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
    S.parts = S.parts.filter(p => { p.y += (p.vy || 0) * dt; return (p.t += dt) < 0.3; });
    S.floats = S.floats.filter(f => { f.t += dt; f.y -= 14 * dt; return f.t < 0.9; });
  }

  // ---------------------------------------------------------------- 그리기
  function bodyParts() {
    return CFG.pos === 'G' ? { jh: 8, lh: 3 } : CFG.pos === 'C' ? { jh: 10, lh: 5 } : { jh: 9, lh: 4 };
  }
  function bodyH() { const b = bodyParts(); return 5 + 1 + b.jh + 4 + b.lh + 2; }

  function drawBall(x, y, s, kind) {
    const base = kind === 2 ? C.deep : kind === 1 ? C.money : C.ball;
    const dk = kind === 2 ? C.deepDark : kind === 1 ? C.moneyDark : C.ballDark;
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
      drawBall(x, y - 7, 5, !S.holding ? 0 : S.spot === DEEP ? 2 : S.ballInSpot === BALLS - 1 ? 1 : 0);
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
    // 로고샷 공 (받침대 위 한 개)
    if (S.spot < DEEP || (S.spot === DEEP && S.ballInSpot === 0 && !S.walking)) {
      const rx = LOGO.x + 11, ry = LOGO.y - 4;
      px(rx, ry + 4, 4, 1, '#6b6f78'); px(rx, ry + 5, 1, 2, '#6b6f78'); px(rx + 3, ry + 5, 1, 2, '#6b6f78');
      px(rx + 1, ry + 2, 2, 2, C.deep);
    }
  }

  function drawHoopBack() { px(73, HOOP.y - 2, 14, 1, C.rimBack); }
  function drawHoopFront(now) {
    const sway = S.net > 0 ? Math.sin(now / 30) * S.net * 2 : 0;
    const rs = S.rimShake > 0 ? Math.round(Math.sin(now / 18) * 1.5 * Math.min(1, S.rimShake / 0.2)) : 0;   // 림 흔들림
    g.fillStyle = C.net;
    for (let i = 0; i <= 4; i++) {
      const xt = 73 + i * 3.5, xb = 76 + i * 2 + sway;
      for (let k = 0; k <= 9; k++) { const u = k / 9; g.fillRect(Math.round(xt + (xb - xt) * u), HOOP.y + 1 + k, 1, 1); }
    }
    for (let k = 3; k <= 9; k += 3) { const w = 14 - k * 0.6; g.fillRect(Math.round(80 - w / 2 + sway * k / 9), HOOP.y + 1 + k, Math.round(w), 1); }
    px(72 + rs, HOOP.y, 16, 2, C.rim);
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
    const x0 = Math.round((W - (RACKS * gw - 3 + 7)) / 2);
    for (let r = 0; r <= RACKS; r++) for (let k = 0; k < ballsAt(r); k++) {
      const deep = r === DEEP, st = S.shots[deep ? NSHOTS - 1 : r * BALLS + k], m = !deep && k === BALLS - 1;
      const x = deep ? x0 + RACKS * gw + 1 : x0 + r * gw + k * 4;
      const col = st === 'made' ? (deep ? C.deep : m ? C.gold : C.green) : st === 'miss' ? C.miss : C.slot;
      px(x, y0, 3, 3, col);
      if (st === 'pending') { g.fillStyle = deep ? C.deepDark : m ? C.moneyDark : C.slotLine; g.fillRect(x, y0, 3, 1); }
    }
  }

  function drawGauge(now) {
    const x = 20, y = 189, w = 120, h = 8;
    const active = S.phase === 'play' && !S.timeUp;
    g.globalAlpha = active ? 1 : 0.45;
    px(x - 1, y - 1, w + 2, h + 2, '#0f0b16');
    px(x, y, w, h, '#2b2240');
    const c = zoneC(), half = zoneW() / 2;
    px(x + Math.round((c - half) * w), y, Math.max(2, Math.round(half * 2 * w)), h, S.fire ? C.fire : C.green);
    px(x + Math.round((c - DIFF.swish) * w), y, Math.max(1, Math.round(DIFF.swish * 2 * w)), h, S.fire ? C.gold : '#a7f3d0');
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
    const sk = S.shake > 0 ? Math.min(1, S.shake / 0.3) * 2 : 0;    // 화면 흔들림 (머니볼·로고샷·버저비터)
    g.save();
    g.translate(Math.round((Math.random() - 0.5) * sk), Math.round((Math.random() - 0.5) * sk));
    g.drawImage(BG, 0, 0);
    drawHoopBack();
    for (const b of S.balls) if (b.state === 'drop' || b.state === 'roll') drawBall(b.x, b.y, 3, b.kind);
    drawHoopFront(now);
    drawRacks();
    const p = playerPos();
    // 공이 선수보다 뒤(위)에 있으면 먼저 그린다
    for (const b of S.balls) if ((b.state === 'fly' || b.state === 'bounce') && b.y < p.y - 30) drawBall(b.x, b.y, ballSize(b), b.kind);
    drawPlayer(p, now);
    for (const b of S.balls) if ((b.state === 'fly' || b.state === 'bounce') && b.y >= p.y - 30) drawBall(b.x, b.y, ballSize(b), b.kind);
    for (const q of S.parts) { g.globalAlpha = 1 - q.t / 0.3; px(q.x, q.y, 1, 1, q.c); }
    g.globalAlpha = 1;
    for (const f of S.floats) { g.globalAlpha = Math.min(1, 2 * (1 - f.t / 0.9)); text(f.str, f.x, f.y, f.color, f.size, 'center'); }
    g.globalAlpha = 1;
    g.restore();
    drawHUD(now);
    drawGauge(now);
    if (S.fire && S.phase === 'play' && (S.fireFlash > 0 ? Math.floor(now / 120) % 2 === 0 : true)) text('ON FIRE', 80, 108, C.fire, 6, 'center');
    if (S.phase === 'idle') {
      g.fillStyle = 'rgba(15,11,22,.55)'; g.fillRect(0, 34, W, 140);
      text('3PT', 80, 70, C.gold, 16, 'center');
      text('CONTEST', 80, 92, C.gold, 8, 'center');
      if (Math.floor(now / 600) % 2 === 0) text('TAP TO START', 80, 120, C.white, 6, 'center');
      text('HOLD & RELEASE TO SHOOT', 80, 140, '#c9bedb', 4, 'center');
    } else if (S.phase === 'count') {
      const n = Math.ceil(S.countT / 0.6);
      text(n > 3 ? '' : n >= 1 ? String(n) : '', 80, 92, C.white, 16, 'center');
    } else if (S.phase === 'play' && now - S.t0 < 600) {
      text('GO!', 80, 92, C.gold, 16, 'center');
    } else if (S.phase === 'end') {
      g.fillStyle = 'rgba(15,11,22,.55)'; g.fillRect(0, 60, W, 70);
      text(allShot() && !S.timeUp ? 'FINISH!' : 'TIME UP!', 80, 78, C.gold, 10, 'center');
      text(`${S.score} PTS`, 80, 100, C.white, 8, 'center');
      if (now - S.endT > 1500 && Math.floor(now / 600) % 2 === 0) text('TAP TO RETRY', 80, 118, '#c9bedb', 5, 'center');
    }
  }
  const ballSize = b => b.state === 'bounce' ? 3 : Math.max(3, Math.round(5 - 2 * Math.min(1, b.u)));

  function loop(ts) {
    const now = ts;
    const raw = Math.min(0.05, (now - (loop.last || now)) / 1000);
    loop.last = now;
    const dt = S.slow > 0 ? raw * 0.3 : raw;        // 버저비터 슬로모션
    S.slow = Math.max(0, S.slow - raw);
    update(dt, now);
    stage.classList.toggle('playing', S.phase === 'count' || S.phase === 'play');
    draw(now);
    updateGhost(now);
    requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------- 입력
  const stage = document.getElementById('stage');
  // 게임 중에만 코트에서 스크롤을 막는다 (그 외에는 코트 위에서 쓸어도 페이지가 내려간다)
  const playing = () => S.phase === 'count' || S.phase === 'play';
  stage.addEventListener('pointerdown', e => {
    if (!playing()) return;                   // 대기·결과 화면: 스크롤 허용, 시작은 click 으로
    e.preventDefault();
    SND.unlock();
    try { stage.setPointerCapture(e.pointerId); } catch (_) { /* 일부 브라우저 미지원 */ }
    press(performance.now());
  });
  // 대기 화면이나 결과 화면에서는 코트를 탭해도 시작 (쓸어서 스크롤한 경우엔 click 이 안 생긴다)
  stage.addEventListener('click', () => {
    if (S.phase === 'idle' || (S.phase === 'end' && performance.now() - S.endT > 1500)) { SND.unlock(); start(); }
  });
  const up = e => { if (playing()) e.preventDefault(); release(performance.now()); };
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
      shots: new Array(NSHOTS).fill('pending'), codes: new Array(NSHOTS).fill('-'), ev: [],
      deep: 0, swishRun: 0, combos: 0, slow: 0, shake: 0, rimShake: 0, lastCount: 0,
    });
    newTarget();
  }
  reset();

  let starting = false;
  async function start() {
    if (starting || S.phase === 'count' || S.phase === 'play') return;
    starting = true;
    SND.unlock();
    showErr('');
    startBtn.disabled = true; againBtn.disabled = true;
    try {
      const r = await fetch('/arcade/runs', { method: 'POST', headers: { 'Accept': 'application/json' } });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || '게임을 시작하지 못했어요.');
      reset();
      if (nextGhosts) { GHOSTS = nextGhosts; nextGhosts = null; }
      S.runId = data.run_id;
      S.phase = 'count'; S.countT = 1.8;
      startBtn.classList.add('hidden'); result.classList.add('hidden'); hint.classList.remove('hidden');
      stage.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {
      showErr(e.message);
    } finally {
      starting = false;
      startBtn.disabled = false; againBtn.disabled = false;
    }
  }

  async function finish() {
    $('r-score').textContent = S.score;
    const extra = [S.money ? `머니볼 ${S.money}개` : '', S.deep ? '로고샷 성공!' : '', S.combos ? `스위시 콤보 ${S.combos}번` : ''].filter(Boolean);
    $('r-made').textContent = `${S.codes.filter(c => c !== '-').length}개 중 ${S.made}개 성공` + (extra.length ? ' · ' + extra.join(' · ') : '');
    $('r-title').textContent = allShot() && !S.timeUp ? '로고샷까지 다 던졌어요!' : '타임 업!';
    $('r-msg').textContent = '기록 저장 중…';
    hint.classList.add('hidden');
    setTimeout(() => result.classList.remove('hidden'), 700);
    try {
      const r = await fetch(`/arcade/runs/${S.runId}/finish`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ shots: S.codes.join(''), events: S.ev, made: S.made, money: S.money }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || '기록을 저장하지 못했어요.');
      const msg = [];
      $('r-score').textContent = d.score;
      if (d.new_season_best && d.score > 0) msg.push('🎉 시즌 개인 신기록!');
      else if (d.new_week_best && d.score > 0) msg.push('🔥 이번 주 개인 최고!');
      for (const c of d.beaten || []) msg.push(`⚔️ ${c.name}님의 도전장(${c.target}점) 격파!`);
      msg.push(`이번 주 최고 ${d.week_best}점 · ${d.week_rank}위`);
      $('r-msg').textContent = msg.join(' ');
      $('my-week-score').textContent = d.week_best; $('my-week-rank').textContent = d.week_rank; $('my-week').classList.remove('hidden');
      if (d.new_season_best && d.score > 0) {          // 다음 판부터는 이번 기록과 비교
        nextGhosts = [{ label: '내 최고', score: d.score, ev: S.ev.slice() }, ...GHOSTS.filter(x => x.label !== '내 최고')];
      }
      if (window.htmx) {
        htmx.trigger(document.body, 'arcadeChanged');      // 랭킹·도전장 새로고침
        htmx.ajax('GET', '/arcade/stats', { target: '#my-stats', swap: 'innerHTML' });
      }
    } catch (e) {
      $('r-msg').textContent = e.message;
    }
  }

  // ---------------------------------------------------------------- 고스트: 내 최고·주간 1위와 같은 시각의 점수 비교
  let GHOSTS = CFG.ghosts || [], nextGhosts = null, ghostAt = 0;
  const ghostEl = $('ghost');
  const ghostScore = (ev, ms) => { let v = 0; for (const [t, sc] of ev) { if (t > ms) break; v = sc; } return v; };
  function updateGhost(now) {
    const on = GHOSTS.length && (S.phase === 'play' || S.phase === 'end');
    ghostEl.classList.toggle('hidden', !on);
    if (!on || now - ghostAt < 120) return;
    ghostAt = now;
    const ms = S.phase === 'end' ? Infinity : now - S.t0;
    ghostEl.replaceChildren(...GHOSTS.map(gh => {
      const d = S.score - ghostScore(gh.ev, ms);
      const span = document.createElement('span'), b = document.createElement('b');
      span.textContent = `👻 ${gh.label} `;
      b.textContent = d > 0 ? `+${d}` : String(d);
      b.className = d > 0 ? 'text-emerald-600' : d < 0 ? 'text-red-600' : 'text-stone-500';
      span.appendChild(b);
      return span;
    }));
  }

  const soundBtn = $('sound');
  const paintSound = () => { soundBtn.textContent = SND.muted ? '🔇' : '🔊'; };
  soundBtn.addEventListener('click', () => { SND.toggle(); paintSound(); if (!SND.muted) SND.beep(true); });
  paintSound();

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
