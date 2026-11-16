import { useEffect, useMemo, useRef } from 'react';
import { usePrefersReducedMotion } from '../../lib/hooks';
import { ORB_STATE_META, type OrbState } from './orb-state-machine';

interface HybridOrbProps {
  state: OrbState;
  /** Taille CSS ; le canvas s'adapte à son conteneur. */
  className?: string;
  /** Rend l'Orb actionnable (ouvre la conversation). */
  onActivate?: () => void;
  label?: string;
}

interface Particle {
  angle: number;
  radius: number;
  speed: number;
  direction: number;
  size: number;
  phase: number;
  depth: number;
  hue: number;
}

interface Palette {
  core: string;
  mid: string;
  edge: string;
  particle: string;
}

const PALETTES: Record<OrbState, Palette> = {
  idle: { core: '#f7fbff', mid: '#5ce7ff', edge: '#267bff', particle: '#5ce7ff' },
  listening: { core: '#f7fbff', mid: '#5ce7ff', edge: '#267bff', particle: '#9af1ff' },
  thinking: { core: '#eaf2ff', mid: '#7c8dff', edge: '#6b58ff', particle: '#8fb6ff' },
  executing: { core: '#f7fbff', mid: '#267bff', edge: '#6b58ff', particle: '#5ce7ff' },
  speaking: { core: '#f7fbff', mid: '#b9a8ff', edge: '#6b58ff', particle: '#d9c9ff' },
  response: { core: '#f7fbff', mid: '#5ce7ff', edge: '#267bff', particle: '#bfefff' },
  success: { core: '#f7fbff', mid: '#4be3ae', edge: '#267bff', particle: '#9df5d6' },
  error: { core: '#fff1f3', mid: '#ff8a9b', edge: '#7a2140', particle: '#ff8a9b' },
  waiting_approval: { core: '#fff6e6', mid: '#ffc774', edge: '#8a5a1f', particle: '#ffd79a' },
};

const SPEED: Record<OrbState, number> = {
  idle: 0.22,
  listening: 0.45,
  thinking: 0.85,
  executing: 0.65,
  speaking: 0.38,
  response: 0.25,
  success: 0.3,
  error: 1.15,
  waiting_approval: 0.28,
};

function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function makeParticles(count: number): Particle[] {
  const random = mulberry32(0x6b7765);
  return Array.from({ length: count }, () => {
    const depth = random();
    return {
      angle: random() * Math.PI * 2,
      radius: 0.42 + random() * 0.62,
      speed: 0.25 + random() * 0.85,
      direction: random() > 0.32 ? 1 : -1,
      size: 0.6 + depth * 1.9,
      phase: random() * Math.PI * 2,
      depth,
      hue: random(),
    };
  });
}

function rgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
}

/** Écran/ordinateur affiché au centre de l'Orb pendant `executing`. */
function drawDevice(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  time: number,
  animated: boolean,
): void {
  const w = r * 0.92;
  const h = r * 0.56;
  const x = cx - w / 2;
  const y = cy - h / 2 - r * 0.04;

  ctx.save();
  ctx.translate(x, y);

  // Halo de l'écran
  const halo = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w * 0.75);
  halo.addColorStop(0, 'rgba(92, 231, 255, 0.35)');
  halo.addColorStop(1, 'rgba(92, 231, 255, 0)');
  ctx.fillStyle = halo;
  ctx.fillRect(-w * 0.25, -h * 0.4, w * 1.5, h * 1.8);

  // Écran
  const radius = Math.max(3, r * 0.045);
  ctx.beginPath();
  ctx.roundRect(0, 0, w, h, radius);
  ctx.fillStyle = 'rgba(8, 6, 28, 0.94)';
  ctx.fill();
  ctx.lineWidth = Math.max(1, r * 0.014);
  ctx.strokeStyle = 'rgba(180, 235, 255, 0.85)';
  ctx.stroke();

  // Contenu de l'écran : lignes + barre de progression
  const pad = w * 0.1;
  const lineHeight = Math.max(1, r * 0.02);
  for (let i = 0; i < 3; i += 1) {
    const lineWidth = w * (i === 2 ? 0.45 : 0.68);
    ctx.fillStyle = rgba('#5ce7ff', 0.32 - i * 0.06);
    ctx.fillRect(pad, pad + i * lineHeight * 3, lineWidth, lineHeight);
  }

  const barY = h - pad - lineHeight;
  const barW = w - pad * 2;
  ctx.fillStyle = 'rgba(140, 155, 255, 0.22)';
  ctx.fillRect(pad, barY, barW, lineHeight * 1.6);
  const progress = animated ? 0.35 + 0.35 * (0.5 + 0.5 * Math.sin(time * 1.4)) : 0.62;
  const grad = ctx.createLinearGradient(pad, 0, pad + barW * progress, 0);
  grad.addColorStop(0, '#267bff');
  grad.addColorStop(1, '#5ce7ff');
  ctx.fillStyle = grad;
  ctx.fillRect(pad, barY, barW * progress, lineHeight * 1.6);

  // Base du portable
  ctx.beginPath();
  ctx.moveTo(-w * 0.08, h + r * 0.012);
  ctx.lineTo(w * 1.08, h + r * 0.012);
  ctx.lineTo(w * 0.97, h + r * 0.075);
  ctx.lineTo(w * 0.03, h + r * 0.075);
  ctx.closePath();
  ctx.fillStyle = 'rgba(12, 9, 42, 0.96)';
  ctx.fill();
  ctx.strokeStyle = 'rgba(140, 190, 255, 0.55)';
  ctx.stroke();

  // Voyant d'activité
  if (animated) {
    const blink = 0.4 + 0.6 * Math.abs(Math.sin(time * 2.2));
    ctx.beginPath();
    ctx.arc(w / 2, h + r * 0.043, Math.max(1.2, r * 0.012), 0, Math.PI * 2);
    ctx.fillStyle = rgba('#4be3ae', blink);
    ctx.fill();
  }

  ctx.restore();
}

function drawGlyph(
  ctx: CanvasRenderingContext2D,
  state: OrbState,
  cx: number,
  cy: number,
  r: number,
  time: number,
  animated: boolean,
): void {
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  if (state === 'waiting_approval') {
    const barW = r * 0.09;
    const barH = r * 0.3;
    ctx.fillStyle = rgba('#ffc774', 0.92);
    ctx.beginPath();
    ctx.roundRect(cx - barW * 1.7, cy - barH / 2, barW, barH, barW / 2);
    ctx.roundRect(cx + barW * 0.7, cy - barH / 2, barW, barH, barW / 2);
    ctx.fill();
  }

  if (state === 'success') {
    const pulse = animated ? 0.5 + 0.5 * Math.sin(time * 2) : 0.6;
    ctx.beginPath();
    ctx.arc(cx, cy, r * (0.46 + pulse * 0.1), 0, Math.PI * 2);
    ctx.strokeStyle = rgba('#4be3ae', 0.35 + pulse * 0.25);
    ctx.lineWidth = Math.max(1, r * 0.018);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(cx - r * 0.16, cy + r * 0.01);
    ctx.lineTo(cx - r * 0.03, cy + r * 0.14);
    ctx.lineTo(cx + r * 0.19, cy - r * 0.14);
    ctx.strokeStyle = '#f7fbff';
    ctx.lineWidth = Math.max(2, r * 0.035);
    ctx.stroke();
  }

  if (state === 'error') {
    ctx.beginPath();
    ctx.moveTo(cx, cy - r * 0.19);
    ctx.lineTo(cx, cy + r * 0.04);
    ctx.strokeStyle = '#fff1f3';
    ctx.lineWidth = Math.max(2, r * 0.045);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy + r * 0.15, Math.max(1.6, r * 0.026), 0, Math.PI * 2);
    ctx.fillStyle = '#fff1f3';
    ctx.fill();
  }

  if (state === 'listening') {
    const wave = animated ? 0.5 + 0.5 * Math.sin(time * 3.4) : 0.5;
    ctx.beginPath();
    ctx.arc(cx, cy, r * (0.34 + wave * 0.16), 0, Math.PI * 2);
    ctx.strokeStyle = rgba('#5ce7ff', 0.5 - wave * 0.3);
    ctx.lineWidth = Math.max(1, r * 0.016);
    ctx.stroke();
  }

  if (state === 'thinking') {
    for (let i = 0; i < 3; i += 1) {
      const angle = (animated ? time * 1.1 : 0) + (i * Math.PI * 2) / 3;
      const orbit = r * 0.28;
      ctx.beginPath();
      ctx.arc(cx + Math.cos(angle) * orbit, cy + Math.sin(angle) * orbit, Math.max(2, r * 0.03), 0, Math.PI * 2);
      ctx.fillStyle = rgba('#c9d6ff', 0.8 - i * 0.15);
      ctx.fill();
    }
  }

  if (state === 'speaking') {
    const orbit = r * 0.42;
    for (let i = 0; i < 3; i += 1) {
      const wobble = animated ? Math.sin(time * 2 + i) * 0.05 : 0;
      ctx.beginPath();
      ctx.arc(cx, cy, orbit * (1 + i * 0.16 + wobble), 0, Math.PI * 2);
      ctx.strokeStyle = rgba('#d9c9ff', 0.28 - i * 0.07);
      ctx.lineWidth = Math.max(1, r * 0.012);
      ctx.stroke();
    }
  }

  ctx.restore();
}

export function HybridOrb({ state, className, onActivate, label }: HybridOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef<OrbState>(state);
  const redrawRef = useRef<(() => void) | null>(null);
  const reduced = usePrefersReducedMotion();
  const particles = useMemo(() => makeParticles(150), []);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    const parent = canvas.parentElement;
    if (!parent) return;

    let width = 0;
    let height = 0;
    let frame = 0;
    let visible = !document.hidden;
    const start = performance.now();

    const resize = (): boolean => {
      const rect = parent.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const nextWidth = Math.max(1, rect.width);
      const nextHeight = Math.max(1, rect.height);
      if (nextWidth === width && nextHeight === height) return false;
      width = nextWidth;
      height = nextHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      return true;
    };

    const render = (elapsedMs: number): void => {
      resize();
      const current = stateRef.current;
      const palette = PALETTES[current];
      const animated = !reduced;
      const time = animated ? elapsedMs / 1000 : 1.2;
      const cx = width / 2;
      const cy = height / 2;
      const r = Math.min(width, height) * 0.38;
      const energy = SPEED[current];

      context.clearRect(0, 0, width, height);

      // Halo volumétrique
      const glow = context.createRadialGradient(cx, cy, r * 0.1, cx, cy, r * 2.05);
      glow.addColorStop(0, rgba(palette.mid, 0.34));
      glow.addColorStop(0.45, rgba(palette.edge, 0.16));
      glow.addColorStop(1, rgba(palette.edge, 0));
      context.fillStyle = glow;
      context.fillRect(0, 0, width, height);

      context.save();
      context.globalCompositeOperation = 'lighter';

      // Particules en orbite
      const count = Math.round(particles.length * (width < 380 ? 0.55 : 1));
      for (let i = 0; i < count; i += 1) {
        const p = particles[i];
        if (!p) continue;
        const drift = p.angle + time * energy * p.speed * p.direction * 0.6;
        let radius = r * p.radius;

        if (current === 'thinking') {
          const t = (p.radius + time * 0.055 * p.speed) % 1;
          radius = r * (0.22 + t * 0.86);
        } else if (current === 'listening') {
          radius = r * p.radius * (1 + Math.sin(time * 1.6 + p.phase) * 0.045);
        } else if (current === 'executing') {
          const band = i % 3;
          radius = r * (0.5 + band * 0.16) + Math.sin(time * 0.9 + p.phase) * r * 0.025;
        } else if (current === 'speaking') {
          radius = r * p.radius * (1 + Math.sin(time * 1.8 + p.phase) * 0.06);
        } else if (current === 'success') {
          radius = r * p.radius * (1 + 0.12 * (0.5 + 0.5 * Math.sin(time * 1.4 + p.phase)));
        } else if (current === 'waiting_approval') {
          radius = r * p.radius * (1 + Math.sin(time * 0.7 + p.phase) * 0.02);
        } else if (current === 'error') {
          radius = r * p.radius;
        } else {
          radius = r * p.radius * (1 + Math.sin(time * 0.5 + p.phase) * 0.02);
        }

        let x = cx + Math.cos(drift) * radius;
        let y = cy + Math.sin(drift) * radius * 0.94;
        if (current === 'error') {
          x += Math.sin(time * 12 + p.phase) * r * 0.012 * (0.4 + p.depth);
          y += Math.cos(time * 9 + p.phase) * r * 0.008;
        }

        const alpha = 0.18 + p.depth * 0.62;
        const size = Math.max(0.6, p.size * (r / 150));
        context.beginPath();
        context.arc(x, y, size, 0, Math.PI * 2);
        context.fillStyle = rgba(palette.particle, alpha * 0.85);
        context.fill();
      }
      context.restore();

      // Sphère centrale
      const coreRadius = r * (current === 'listening' ? 0.6 + Math.sin(time * 2) * 0.012 : 0.62);
      const core = context.createRadialGradient(
        cx - coreRadius * 0.3,
        cy - coreRadius * 0.34,
        coreRadius * 0.08,
        cx,
        cy,
        coreRadius,
      );
      core.addColorStop(0, rgba(palette.core, 0.98));
      core.addColorStop(0.32, rgba(palette.mid, 0.82));
      core.addColorStop(0.72, rgba(palette.edge, 0.42));
      core.addColorStop(1, rgba(palette.edge, 0.02));
      context.beginPath();
      context.arc(cx, cy, coreRadius, 0, Math.PI * 2);
      context.fillStyle = core;
      context.fill();

      // Anneau de verre
      context.beginPath();
      context.arc(cx, cy, r * 0.9, 0, Math.PI * 2);
      context.strokeStyle = rgba(palette.mid, current === 'waiting_approval' ? 0.34 : 0.14);
      context.lineWidth = Math.max(1, r * 0.008);
      context.stroke();

      if (current === 'waiting_approval' || current === 'success') {
        const dash = current === 'success' ? 18 : 10;
        context.beginPath();
        context.setLineDash([dash, dash * 1.4]);
        context.lineDashOffset = animated ? -time * 14 : 0;
        context.arc(cx, cy, r * (current === 'success' ? 1.02 : 0.96), 0, Math.PI * 2);
        context.strokeStyle = rgba(current === 'success' ? '#4be3ae' : '#ffc774', 0.5);
        context.lineWidth = Math.max(1, r * 0.012);
        context.stroke();
        context.setLineDash([]);
      }

      if (current === 'executing') {
        drawDevice(context, cx, cy, r, time, animated);
      } else {
        drawGlyph(context, current, cx, cy, r, time, animated);
      }
    };

    const loop = (now: number): void => {
      if (!visible) return;
      render(now - start);
      frame = window.requestAnimationFrame(loop);
    };

    const startLoop = (): void => {
      if (reduced) {
        render(0);
        return;
      }
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(loop);
    };

    const stopLoop = (): void => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
    };

    const onVisibility = (): void => {
      visible = !document.hidden;
      if (visible) startLoop();
      else stopLoop();
    };

    const observer = new ResizeObserver(() => {
      if (reduced) render(0);
    });
    observer.observe(parent);
    document.addEventListener('visibilitychange', onVisibility);
    redrawRef.current = () => render(0);
    startLoop();

    return () => {
      stopLoop();
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      redrawRef.current = null;
    };
  }, [particles, reduced]);

  // En mode réduit, un changement d'état redessine une frame statique.
  useEffect(() => {
    if (reduced) redrawRef.current?.();
  }, [reduced, state]);

  const meta = ORB_STATE_META[state];
  const content = (
    <canvas
      ref={canvasRef}
      className="orb__canvas"
      aria-hidden="true"
      role="presentation"
      data-orb-state={state}
    />
  );

  if (onActivate) {
    return (
      <button
        type="button"
        className={`orb orb--interactive ${className ?? ''}`}
        onClick={onActivate}
        aria-label={label ?? `Orb Kwes — ${meta.label}. Activer la conversation.`}
      >
        {content}
      </button>
    );
  }

  return (
    <div className={`orb ${className ?? ''}`} aria-hidden="true">
      {content}
    </div>
  );
}
