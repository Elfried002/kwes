/**
 * « Dot vivant » — la matière de l'écran vocal, dessinée en Canvas 2D.
 *
 * Aucune image, aucun GIF : tout est calculé à chaque image (dégradé radial
 * violet/bleu/cyan, rubans internes qui dérivent comme un liquide, halo au
 * sol, respiration, clignement des yeux, micro-squash à la parole).
 *
 * L'amplitude vient d'un niveau réel (`levelRef`) fourni par `useAudioLevel` :
 * analyse du flux audio de la réponse quand Kwes parle, activité réelle de la
 * reconnaissance quand l'utilisateur parle. Aucun mouvement n'est inventé quand
 * rien ne se passe : en veille, le dot respire et cligne, c'est tout.
 *
 * Performance : une seule boucle rAF, aucun `shadowBlur` (remplacé par des
 * dégradés), DPR plafonné à 2, boucle suspendue quand l'onglet est masqué,
 * rendu statique quand `prefers-reduced-motion` est actif.
 */

import { useEffect, useRef } from 'react';
import { usePrefersReducedMotion } from '../../lib/hooks';

export type DotPhase = 'idle' | 'listening' | 'thinking' | 'speaking' | 'error';

interface LivingDotProps {
  phase: DotPhase;
  /** Niveau 0..1 (réf mutable : lue dans la boucle, aucun rendu React). */
  levelRef?: { current: number };
  className?: string;
}

const TAU = Math.PI * 2;
const VIOLET = '#6B58FF';
const BLUE = '#267BFF';
const CYAN = '#5CE7FF';
const WHITE = '#F7FBFF';

function rgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
}

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

export function LivingDot({ phase, levelRef, className }: LivingDotProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const clockRef = useRef(0);
  const blinkRef = useRef({ next: 4.6, at: -1 });
  const phaseRef = useRef<DotPhase>(phase);
  const reduced = usePrefersReducedMotion();
  const reducedRef = useRef(reduced);
  phaseRef.current = phase;
  reducedRef.current = reduced;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    let width = 0;
    let height = 0;
    let frame = 0;
    let last = 0;

    // Particules « convergentes » de l'état réflexion (positions déterministes).
    const particles = Array.from({ length: 22 }, (_, index) => {
      const seed = (index * 2654435761) % 4294967296;
      return {
        angle: (((seed >>> 8) % 1000) / 1000) * TAU,
        offset: ((seed >>> 18) % 500) / 500,
        speed: 0.1 + (((seed >>> 4) % 300) / 300) * 0.09,
        size: 0.6 + (((seed >>> 12) % 400) / 400) * 1.1,
      };
    });

    const resize = (): void => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const nextWidth = Math.max(1, Math.round(rect.width));
      const nextHeight = Math.max(1, Math.round(rect.height));
      if (nextWidth === width && nextHeight === height) return;
      width = nextWidth;
      height = nextHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    /* ---------- Sol : halo elliptique + reflet ---------- */

    const drawGround = (S: number, R: number, time: number, level: number, muted: boolean): void => {
      const cx = S / 2;
      const groundY = S / 2 + R * 1.03;
      const breathe = 0.5 + 0.5 * Math.sin(time * 0.68);
      const energy = level * 0.55;
      const tint = muted ? '#4E5872' : BLUE;
      const glowTint = muted ? '#5B6076' : CYAN;

      context.save();
      context.globalCompositeOperation = 'lighter';
      context.translate(cx, groundY);
      context.scale(1, 0.26);
      const glow = context.createRadialGradient(0, 0, R * 0.05, 0, 0, R * 1.25);
      glow.addColorStop(0, rgba(glowTint, 0.42 + 0.08 * breathe + energy * 0.24));
      glow.addColorStop(0.32, rgba(tint, 0.24 + 0.05 * breathe + energy * 0.16));
      glow.addColorStop(0.66, rgba(tint, 0.06 + energy * 0.06));
      glow.addColorStop(1, rgba(tint, 0));
      context.fillStyle = glow;
      context.beginPath();
      context.arc(0, 0, R * 1.25, 0, TAU);
      context.fill();
      context.restore();

      // Un seul anneau, très doux : le dot « touche » le sol.
      context.save();
      context.globalCompositeOperation = 'lighter';
      context.beginPath();
      context.ellipse(cx, groundY, R * 1.12, R * 0.135, 0, 0, TAU);
      context.strokeStyle = rgba(glowTint, 0.1 + 0.04 * breathe + energy * 0.12);
      context.lineWidth = 1;
      context.stroke();
      context.restore();
    };

    /* ---------- Aura circulaire (jamais un rectangle) ---------- */

    const drawAura = (S: number, R: number, time: number, level: number, muted: boolean): void => {
      const cx = S / 2;
      const cy = S / 2;
      // Borné au canvas : un halo plus grand serait coupé net par le bord.
      const radius = Math.min(R * (1.55 + 0.05 * Math.sin(time * 0.55) + level * 0.12), S * 0.49);
      const aura = context.createRadialGradient(cx, cy, R * 0.82, cx, cy, radius);
      const a = muted ? '#3C3F55' : VIOLET;
      aura.addColorStop(0, rgba(a, muted ? 0.14 : 0.16 + level * 0.05));
      aura.addColorStop(0.4, rgba(a, muted ? 0.06 : 0.05 + level * 0.03));
      aura.addColorStop(0.82, rgba(a, muted ? 0.015 : 0.015));
      aura.addColorStop(1, rgba(a, 0));
      context.fillStyle = aura;
      context.beginPath();
      context.arc(cx, cy, radius, 0, TAU);
      context.fill();
    };

    /* ---------- Ruban liquide interne ---------- */

    const ribbon = (
      R: number,
      baseY: number,
      amplitude: number,
      frequency: number,
      drift: number,
      slope: number,
      thickness: number,
      color: string,
      alpha: number,
    ): void => {
      const segments = 44;
      const from = -R * 1.02;
      const to = R * 1.02;
      const step = (to - from) / segments;
      const wave = (x: number): number => {
        const u = x / R;
        return (
          baseY +
          slope * u * R +
          amplitude * Math.sin(frequency * u + drift) +
          amplitude * 0.46 * Math.sin(frequency * 2.15 * u - drift * 1.35)
        );
      };

      context.beginPath();
      for (let index = 0; index <= segments; index += 1) {
        const x = from + step * index;
        const y = wave(x);
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      for (let index = segments; index >= 0; index -= 1) {
        const x = from + step * index;
        const u = x / R;
        const y = wave(x) + thickness * (1 + 0.3 * Math.sin(frequency * 0.8 * u + drift * 0.7));
        context.lineTo(x, y);
      }
      context.closePath();

      const gradient = context.createLinearGradient(0, baseY - amplitude, 0, baseY + thickness * 2);
      gradient.addColorStop(0, rgba(color, alpha * 0.3));
      gradient.addColorStop(0.5, rgba(color, alpha * 0.72));
      gradient.addColorStop(1, rgba(color, alpha));
      context.fillStyle = gradient;
      context.fill();

      // Liseré lumineux sur la crête : c'est lui qui donne le « liquide ».
      context.beginPath();
      for (let index = 0; index <= segments; index += 1) {
        const x = from + step * index;
        const y = wave(x);
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.strokeStyle = rgba('#EDE9FF', Math.min(0.18, alpha * 0.5));
      context.lineWidth = Math.max(1, R * 0.006);
      context.stroke();
    };

    /* ---------- Sphère ---------- */

    const drawSphere = (S: number, time: number, level: number, phase: DotPhase): void => {
      const cx = S / 2;
      const cy = S / 2;
      const R = S * 0.39;
      const muted = phase === 'error';
      const calm = phase === 'idle' || muted;

      // Respiration 1.00 → 1.02 ; micro-squash quand la voix sort.
      const breath = 1 + 0.01 * (1 + Math.sin(time * 0.82));
      let scaleX = breath;
      let scaleY = breath;
      if (phase === 'speaking') {
        scaleX *= 1 + 0.028 * level;
        scaleY *= 1 - 0.042 * level;
      }

      drawAura(S, R, time, level, muted);

      context.save();
      context.translate(cx, cy);
      context.scale(scaleX, scaleY);

      // Corps : cœur clair en haut à gauche, violet, puis bleu.
      context.beginPath();
      context.arc(0, 0, R, 0, TAU);
      const body = context.createRadialGradient(-R * 0.26, -R * 0.34, R * 0.02, 0, 0, R * 1.05);
      if (muted) {
        body.addColorStop(0, rgba('#B9BBC6', 0.9));
        body.addColorStop(0.28, rgba('#5E6178', 0.94));
        body.addColorStop(0.68, rgba('#454A5E', 0.94));
        body.addColorStop(1, rgba('#33374A', 0.92));
      } else {
        body.addColorStop(0, rgba('#F1EEFF', 0.96));
        body.addColorStop(0.16, rgba('#B4A6FF', 0.95));
        body.addColorStop(0.5, rgba(VIOLET, 0.93));
        body.addColorStop(0.82, rgba('#2C4CDC', 0.93));
        body.addColorStop(1, rgba('#2668F2', 0.92));
      }
      context.fillStyle = body;
      context.fill();

      // Intérieur : rubans + lueur cyan en bas, confinés dans la sphère.
      context.save();
      context.beginPath();
      context.arc(0, 0, R * 0.995, 0, TAU);
      context.clip();
      context.globalCompositeOperation = 'lighter';

      const tempo =
        muted ? 0.32 : phase === 'thinking' ? 0.62 : phase === 'speaking' ? 1.35 : 0.9;
      const energy = (calm ? 0.7 : 1) * (0.7 + level * 0.55);

      ribbon(
        R,
        -R * 0.06,
        R * 0.115 * energy,
        1.5,
        time * 0.34 * tempo,
        0.2,
        R * 0.16,
        muted ? '#8A8C9A' : '#DED8FF',
        muted ? 0.24 : 0.34,
      );
      ribbon(
        R,
        R * 0.05,
        R * 0.075 * energy,
        2.2,
        -time * 0.27 * tempo + 1.7,
        -0.14,
        R * 0.12,
        muted ? '#7E8394' : '#93B9FF',
        muted ? 0.2 : 0.3,
      );
      ribbon(
        R,
        R * 0.23,
        R * 0.05 * energy,
        3,
        time * 0.21 * tempo + 3.4,
        0.07,
        R * 0.085,
        muted ? '#767C8C' : CYAN,
        muted ? 0.16 : 0.22,
      );

      // Cyan qui remonte du bas de la sphère.
      const bottom = context.createRadialGradient(0, R * 0.92, R * 0.04, 0, R * 0.82, R * 0.95);
      bottom.addColorStop(0, rgba(muted ? '#767C8C' : CYAN, muted ? 0.16 : 0.24 + level * 0.06));
      bottom.addColorStop(0.55, rgba(muted ? '#5C6172' : '#2F7BFF', muted ? 0.1 : 0.14));
      bottom.addColorStop(1, rgba(BLUE, 0));
      context.fillStyle = bottom;
      context.fillRect(-R, -R, R * 2, R * 2);
      context.restore();

      // Profondeur : le bas du globe s'assombrit légèrement.
      const depth = context.createRadialGradient(0, R * 0.3, R * 0.2, 0, R * 0.6, R * 1.12);
      depth.addColorStop(0, 'rgba(7, 3, 28, 0)');
      depth.addColorStop(1, 'rgba(7, 3, 28, 0.34)');
      context.fillStyle = depth;
      context.beginPath();
      context.arc(0, 0, R, 0, TAU);
      context.fill();

      // Deux lueurs internes : les yeux. Discrets, ils s'ouvrent et se ferment.
      const blinkProgress = (time - blinkRef.current.at) / 0.24;
      const openness =
        blinkProgress >= 0 && blinkProgress <= 1
          ? 1 - Math.sin(Math.PI * blinkProgress) * 0.95
          : 1;
      const attentive = phase === 'listening' ? 1.14 : phase === 'thinking' ? 0.92 : 1;
      const eyeY = -R * 0.045;
      const eyeR = R * 0.04 * attentive;
      context.save();
      context.globalCompositeOperation = 'lighter';
      for (const side of [-1, 1]) {
        const x = side * R * 0.165;
        const gradient = context.createRadialGradient(x, eyeY, 0, x, eyeY, eyeR * 2.2);
        gradient.addColorStop(0, `rgba(255, 255, 255, ${(0.26 * openness).toFixed(3)})`);
        gradient.addColorStop(0.35, `rgba(226, 240, 255, ${(0.11 * openness).toFixed(3)})`);
        gradient.addColorStop(1, 'rgba(198, 224, 255, 0)');
        context.save();
        context.translate(x, eyeY);
        context.scale(1, Math.max(0.08, openness));
        context.translate(-x, -eyeY);
        context.fillStyle = gradient;
        context.beginPath();
        context.arc(x, eyeY, eyeR * 2.2, 0, TAU);
        context.fill();
        context.restore();
      }
      context.restore();

      // Reflet spéculaire diffus (pas de « pastille » blanche).
      context.save();
      context.globalCompositeOperation = 'lighter';
      const specular = context.createRadialGradient(
        -R * 0.32,
        -R * 0.42,
        0,
        -R * 0.32,
        -R * 0.42,
        R * 0.78,
      );
      specular.addColorStop(0, 'rgba(255, 255, 255, 0.1)');
      specular.addColorStop(0.45, 'rgba(226, 236, 255, 0.05)');
      specular.addColorStop(1, 'rgba(226, 236, 255, 0)');
      context.fillStyle = specular;
      context.beginPath();
      context.arc(0, 0, R, 0, TAU);
      context.fill();
      context.restore();

      // Liseré : clair en haut, cyan en bas — la matière devient une sphère.
      const rim = context.createLinearGradient(-R * 0.3, -R, R * 0.2, R);
      rim.addColorStop(0, rgba(WHITE, muted ? 0.18 : 0.42));
      rim.addColorStop(0.55, rgba(WHITE, muted ? 0.1 : 0.16));
      rim.addColorStop(1, rgba(muted ? '#8C90A0' : CYAN, muted ? 0.16 : 0.46 + level * 0.08));
      context.beginPath();
      context.arc(0, 0, R * 0.988, 0, TAU);
      context.strokeStyle = rim;
      context.lineWidth = Math.max(1, R * 0.011);
      context.stroke();

      context.restore();

      /* ---------- Signatures d'état, toutes en dehors du corps ---------- */

      if (phase === 'listening') {
        context.save();
        context.globalCompositeOperation = 'lighter';
        context.translate(cx, cy);
        for (let index = 0; index < 3; index += 1) {
          const progress = (((time * 0.3 + index / 3) % 1) + 1) % 1;
          const radius = R * (1.04 + progress * 0.46 + level * 0.05);
          const alpha = (1 - progress) * (0.1 + level * 0.24);
          context.beginPath();
          context.arc(0, 0, radius, 0, TAU);
          context.strokeStyle = rgba(CYAN, alpha);
          context.lineWidth = 1.1;
          context.stroke();
        }
        context.restore();
      }

      if (phase === 'thinking') {
        context.save();
        context.globalCompositeOperation = 'lighter';
        for (const particle of particles) {
          const progress = (((time * particle.speed + particle.offset) % 1) + 1) % 1;
          const radius = R * (1.3 - progress * 1.0);
          const angle = particle.angle + time * 0.4 + progress * 1.4;
          const alpha = Math.sin(Math.PI * progress) * 0.42;
          context.beginPath();
          context.arc(
            cx + Math.cos(angle) * radius,
            cy + Math.sin(angle) * radius,
            particle.size * (R / 260),
            0,
            TAU,
          );
          context.fillStyle = `rgba(222, 216, 255, ${alpha.toFixed(3)})`;
          context.fill();
        }
        context.restore();
      }

      if (phase === 'speaking') {
        // Halo doux qui bat avec le son réel.
        const haloRadius = R * (1.1 + 0.06 * level);
        const halo = context.createRadialGradient(cx, cy, R * 0.99, cx, cy, haloRadius);
        halo.addColorStop(0, rgba(CYAN, 0.06 + level * 0.13));
        halo.addColorStop(1, rgba(CYAN, 0));
        context.save();
        context.globalCompositeOperation = 'lighter';
        context.fillStyle = halo;
        context.beginPath();
        context.arc(cx, cy, haloRadius, 0, TAU);
        context.fill();
        context.restore();
      }
    };

    const render = (time: number): void => {
      resize();
      if (width < 2 || height < 2) return;
      const S = Math.min(width, height);
      const phase = phaseRef.current;
      const level = clamp01(levelRef?.current ?? 0);
      const drift = phase === 'error' ? time * 0.34 : time;

      const blink = blinkRef.current;
      if (phase !== 'error' && drift > blink.next) {
        blink.at = drift;
        blink.next = drift + 5.2 + Math.random() * 1.7;
      }

      context.clearRect(0, 0, width, height);
      context.save();
      context.translate((width - S) / 2, (height - S) / 2);
      drawGround(S, S * 0.39, drift, level, phase === 'error');
      drawSphere(S, drift, level, phase);
      context.restore();
    };

    const tick = (now: number): void => {
      frame = window.requestAnimationFrame(tick);
      const delta = Math.min(0.06, Math.max(0, (now - last) / 1000));
      last = now;
      clockRef.current += delta;
      render(clockRef.current);
    };

    const onVisibility = (): void => {
      if (document.hidden) {
        if (frame) window.cancelAnimationFrame(frame);
        frame = 0;
        return;
      }
      if (!frame) {
        last = performance.now();
        frame = window.requestAnimationFrame(tick);
      }
    };

    resize();
    if (reducedRef.current) {
      render(1.6);
    } else {
      last = performance.now();
      frame = window.requestAnimationFrame(tick);
    }
    document.addEventListener('visibilitychange', onVisibility);

    const observer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            resize();
            if (reducedRef.current) render(1.6);
          });
    observer?.observe(canvas);

    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', onVisibility);
      observer?.disconnect();
    };
    // `phase` : en mouvement réduit, l'image statique est redessinée à chaque
    // changement d'état. Le temps, lui, continue de courir entre deux montages.
  }, [levelRef, reduced, phase]);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      data-phase={phase}
      aria-hidden="true"
      role="presentation"
    />
  );
}
