/**
 * Kwes — le personnage de l'écran vocal, dessiné au Canvas 2D.
 *
 * Ce n'est pas une bille : c'est une petite créature d'argile.
 *   - corps BLOB irrégulier (plusieurs arcs modulés + grain), jamais une sphère ;
 *   - deux GRANDS yeux qui portent l'expression : clignement, regard qui suit le
 *     curseur, sourcils, yeux plissés quand il parle ;
 *   - une bouche minuscule dont l'ouverture suit l'amplitude réelle du son ;
 *   - un accessoire signature unique : un anneau cyan qui flotte au-dessus ;
 *   - respiration, squash & stretch, inclinaison de la tête, réactions réelles.
 *
 * L'amplitude vient de `levelRef` (mesure réelle : RMS de l'audio TTS quand Kwes
 * parle, activité de reconnaissance quand l'utilisateur parle). Rien n'est
 * inventé quand il ne se passe rien : il respire, cligne, et c'est tout.
 *
 * Aucune image bitmap (le grain est généré en mémoire), aucun `shadowBlur`,
 * une seule boucle rAF, DPR plafonné à 2, boucle suspendue onglet masqué,
 * image figée mais complète quand `prefers-reduced-motion` est actif.
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
const INK = '#0C0720';

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

function mix(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/* ------------------------------------------------------------------ */
/* Grain d'argile (généré une fois, jamais une image externe)          */
/* ------------------------------------------------------------------ */

function buildGrainTile(size = 96): HTMLCanvasElement | null {
  if (typeof document === 'undefined') return null;
  const tile = document.createElement('canvas');
  tile.width = size;
  tile.height = size;
  const context = tile.getContext('2d');
  if (!context) return null;
  const image = context.createImageData(size, size);
  for (let index = 0; index < image.data.length; index += 4) {
    const value = 118 + Math.random() * 137;
    image.data[index] = value;
    image.data[index + 1] = value;
    image.data[index + 2] = value;
    image.data[index + 3] = 54;
  }
  context.putImageData(image, 0, 0);
  return tile;
}

/* ------------------------------------------------------------------ */
/* Contour du blob                                                     */
/* ------------------------------------------------------------------ */

const WOBBLE_PHASES = [0.7, 2.4, 4.1, 5.6];
const BLOB_SEGMENTS = 64;

/**
 * Rayon organique : trois harmoniques lentes + une asymétrie de base, pour un
 * galet d'argile pétri à la main plutôt qu'un cercle parfait.
 */
function blobRadius(angle: number, time: number, wobble: number): number {
  const [p1, p2, p3, p4] = WOBBLE_PHASES as [number, number, number, number];
  const harmonic =
    0.046 * Math.sin(3 * angle + time * 0.62 + p1) +
    0.030 * Math.sin(5 * angle - time * 0.48 + p2) +
    0.016 * Math.sin(7 * angle + time * 0.83 + p3);
  // Asymétrie : le flanc droit est un peu plus plein, le gauche plus haut.
  const asym = 0.038 * Math.cos(angle) - 0.026 * Math.sin(angle + p4);
  return 1 + (harmonic + asym) * wobble;
}

function traceBlob(
  context: CanvasRenderingContext2D,
  R: number,
  time: number,
  scaleX: number,
  scaleY: number,
  wobble: number,
): void {
  const points: Array<[number, number]> = [];
  for (let index = 0; index < BLOB_SEGMENTS; index += 1) {
    const angle = (index / BLOB_SEGMENTS) * TAU;
    const radius = R * blobRadius(angle, time, wobble);
    // Les bords s'aplatissent un peu en bas : l'argile repose.
    const settle = 1 - 0.05 * Math.max(0, Math.sin(angle));
    points.push([Math.cos(angle) * radius * scaleX, Math.sin(angle) * radius * scaleY * settle]);
  }
  context.beginPath();
  const first = points[0] as [number, number];
  const last = points[points.length - 1] as [number, number];
  context.moveTo((last[0] + first[0]) / 2, (last[1] + first[1]) / 2);
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index] as [number, number];
    const next = points[(index + 1) % points.length] as [number, number];
    context.quadraticCurveTo(point[0], point[1], (point[0] + next[0]) / 2, (point[1] + next[1]) / 2);
  }
  context.closePath();
}

/* ------------------------------------------------------------------ */
/* Visage                                                             */
/* ------------------------------------------------------------------ */

interface Face {
  /** Ouverture des paupières (1 = grand ouvert). */
  open: number;
  /** Yeux plissés « sourire » : un arc au lieu d'un ovale. */
  happy: boolean;
  /** Regard : décalage en fraction de rayon d'œil. */
  lookX: number;
  lookY: number;
  /** Sourcils : élévation (positif = relevés), inclinaison et asymétrie. */
  browLift: number;
  browTilt: number;
  browSkew: number;
  mouth: 'smile' | 'flat' | 'round' | 'talk' | 'frown';
}

function faceFor(phase: DotPhase, level: number, time: number): Face {
  switch (phase) {
    case 'listening':
      return {
        open: 1.14,
        happy: false,
        lookX: 0,
        lookY: 0.16,
        browLift: 0.9,
        browTilt: -0.1,
        browSkew: 0.15,
        mouth: 'round',
      };
    case 'thinking':
      return {
        open: 0.84,
        happy: false,
        lookX: 0.42 + 0.12 * Math.sin(time * 0.9),
        lookY: -0.55,
        browLift: 0.5,
        browTilt: 0.22,
        browSkew: 0.55,
        mouth: 'flat',
      };
    case 'speaking':
      return {
        open: 0.98 - level * 0.14,
        happy: false,
        lookX: 0.05 * Math.sin(time * 2.1),
        lookY: 0,
        browLift: 0.2 + level * 0.5,
        browTilt: 0,
        browSkew: 0.1,
        mouth: 'talk',
      };
    case 'error':
      return {
        open: 0.58,
        happy: false,
        lookX: 0,
        lookY: 0.3,
        browLift: -0.9,
        browTilt: 0.5,
        browSkew: -0.2,
        mouth: 'frown',
      };
    default:
      return {
        open: 0.94,
        happy: false,
        lookX: 0.06 * Math.sin(time * 0.42),
        lookY: 0.04 * Math.sin(time * 0.31 + 1.2),
        browLift: 0,
        browTilt: 0,
        browSkew: 0,
        mouth: 'smile',
      };
  }
}

function drawEye(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  rx: number,
  ry: number,
  face: Face,
  blink: number,
  side: number,
  time: number,
): void {
  const open = Math.max(0.06, face.open * blink);
  const height = ry * open;

  // Paupière tombante de l'état erreur : l'œil est coupé en biais.
  const tilt = side * 0.12;

  if (face.happy && open > 0.45) {
    // Yeux plissés « sourire » : un simple arc, très lisible.
    context.save();
    context.beginPath();
    context.lineWidth = Math.max(2, ry * 0.22);
    context.lineCap = 'round';
    context.strokeStyle = rgba(INK, 0.92);
    context.arc(x, y + ry * 0.25, rx * 0.9, Math.PI * 1.12, Math.PI * 1.88);
    context.stroke();
    context.restore();
    return;
  }

  context.save();
  context.translate(x, y);
  context.rotate(tilt);

  // Globe sombre : c'est lui qui donne le regard.
  context.beginPath();
  context.ellipse(0, 0, rx, Math.max(1.2, height), 0, 0, TAU);
  context.fillStyle = rgba(INK, 0.94);
  context.fill();

  // Reflet : petit, en haut à gauche, il rend l'œil « vivant ».
  if (open > 0.28) {
    const lookX = face.lookX * rx * 0.22;
    const lookY = face.lookY * ry * 0.22;
    const glintR = rx * 0.3;
    const glint = context.createRadialGradient(
      lookX - rx * 0.34,
      lookY - height * 0.34,
      0,
      lookX - rx * 0.34,
      lookY - height * 0.34,
      glintR,
    );
    glint.addColorStop(0, `rgba(255, 255, 255, ${(0.92 * Math.min(1, open * 1.4)).toFixed(3)})`);
    glint.addColorStop(1, 'rgba(230, 240, 255, 0)');
    context.fillStyle = glint;
    context.beginPath();
    context.arc(lookX - rx * 0.34, lookY - height * 0.34, glintR, 0, TAU);
    context.fill();

    // Second reflet, minuscule, en bas à droite (asymétrie volontaire).
    context.fillStyle = rgba(WHITE, 0.34 * Math.min(1, open * 1.2));
    context.beginPath();
    context.arc(
      lookX + rx * 0.36,
      lookY + height * 0.42,
      Math.max(0.8, rx * 0.13),
      0,
      TAU,
    );
    context.fill();
  }

  // Ligne de paupière supérieure : donne le plissé et la concentration.
  if (open < 0.9) {
    context.beginPath();
    context.strokeStyle = rgba(INK, 0.5);
    context.lineWidth = Math.max(1.2, ry * 0.1);
    context.moveTo(-rx * 0.98, -height * 0.92);
    context.quadraticCurveTo(0, -height * 1.42, rx * 0.98, -height * 0.92);
    context.stroke();
  }
  context.restore();

  // Sourcil : une virgule au-dessus de l'œil.
  const lift = face.browLift + side * face.browSkew;
  const browY = y - ry * (1.5 + 0.16 * lift) + Math.sin(time * 0.9 + side) * ry * 0.02;
  context.save();
  context.translate(x, browY);
  context.rotate(face.browTilt * side);
  context.beginPath();
  context.lineWidth = Math.max(2, ry * 0.2);
  context.lineCap = 'round';
  context.strokeStyle = rgba(INK, 0.7);
  context.moveTo(-rx * 0.82, ry * 0.12);
  context.quadraticCurveTo(0, -ry * (0.16 + 0.12 * Math.max(0, lift)), rx * 0.82, ry * 0.06);
  context.stroke();
  context.restore();
}

function drawMouth(
  context: CanvasRenderingContext2D,
  y: number,
  R: number,
  face: Face,
  level: number,
  time: number,
): void {
  const width = R * 0.15;
  context.save();
  context.lineCap = 'round';
  context.lineJoin = 'round';

  if (face.mouth === 'talk') {
    const openness = 0.22 + level * 0.95;
    const height = R * (0.035 + 0.085 * openness);
    context.beginPath();
    context.ellipse(
      0,
      y + height * 0.35,
      width * (0.86 + level * 0.16),
      height,
      0,
      0,
      TAU,
    );
    context.fillStyle = rgba(INK, 0.86);
    context.fill();
    // Langue discrète quand la bouche est très ouverte.
    if (openness > 0.72) {
      context.beginPath();
      context.ellipse(0, y + height * 1.1, width * 0.46, height * 0.36, 0, 0, TAU);
      context.fillStyle = rgba('#FF8FA8', 0.5);
      context.fill();
    }
    context.restore();
    return;
  }

  if (face.mouth === 'round') {
    context.beginPath();
    context.ellipse(0, y, width * 0.46, R * 0.045, 0, 0, TAU);
    context.fillStyle = rgba(INK, 0.62);
    context.fill();
    context.restore();
    return;
  }

  if (face.mouth === 'frown') {
    context.beginPath();
    context.strokeStyle = rgba(INK, 0.72);
    context.lineWidth = Math.max(2, R * 0.022);
    context.moveTo(-width * 0.7, y + R * 0.02);
    context.quadraticCurveTo(0, y - R * 0.045, width * 0.7, y + R * 0.02);
    context.stroke();
    context.restore();
    return;
  }

  if (face.mouth === 'flat') {
    context.beginPath();
    context.strokeStyle = rgba(INK, 0.6);
    context.lineWidth = Math.max(2, R * 0.02);
    context.moveTo(-width * 0.5, y);
    context.quadraticCurveTo(0, y + R * 0.012 * Math.sin(time), width * 0.5, y);
    context.stroke();
    context.restore();
    return;
  }

  // Sourire : arc ouvert vers le haut, coin droit un peu plus relevé.
  context.beginPath();
  context.strokeStyle = rgba(INK, 0.76);
  context.lineWidth = Math.max(2, R * 0.024);
  context.moveTo(-width * 0.72, y);
  context.quadraticCurveTo(0, y + R * 0.075, width * 0.78, y - R * 0.008);
  context.stroke();
  context.restore();
}

/* ------------------------------------------------------------------ */
/* Composant                                                          */
/* ------------------------------------------------------------------ */

export function LivingDot({ phase, levelRef, className }: LivingDotProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const clockRef = useRef(0);
  const blinkRef = useRef({ next: 2.4, at: -1 });
  const phaseRef = useRef<DotPhase>(phase);
  const gazeRef = useRef({ x: 0, y: 0, targetX: 0, targetY: 0, hasPointer: false });
  const reduced = usePrefersReducedMotion();
  const reducedRef = useRef(reduced);
  phaseRef.current = phase;
  reducedRef.current = reduced;

  /* Le regard suit le curseur ; au doigt, il dérive doucement. */
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onPointer = (event: PointerEvent): void => {
      if (event.pointerType === 'touch') return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      if (rect.width < 2) return;
      const dx = (event.clientX - (rect.left + rect.width / 2)) / (rect.width * 0.7);
      const dy = (event.clientY - (rect.top + rect.height / 2)) / (rect.height * 0.7);
      const gaze = gazeRef.current;
      gaze.targetX = Math.max(-1, Math.min(1, dx));
      gaze.targetY = Math.max(-1, Math.min(1, dy));
      gaze.hasPointer = true;
    };
    window.addEventListener('pointermove', onPointer, { passive: true });
    return () => window.removeEventListener('pointermove', onPointer);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    let width = 0;
    let height = 0;
    let frame = 0;
    let last = 0;

    const grain = buildGrainTile();
    let grainPattern: CanvasPattern | null = null;
    if (grain) {
      try {
        grainPattern = context.createPattern(grain, 'repeat');
      } catch {
        grainPattern = null;
      }
    }

    // Particules de réflexion : elles montent le long du corps, jamais un anneau.
    const particles = Array.from({ length: 12 }, (_, index) => {
      const seed = (index * 2654435761) % 4294967296;
      return {
        offset: ((seed >>> 9) % 1000) / 1000,
        drift: (((seed >>> 19) % 300) / 300 - 0.5) * 0.7,
        speed: 0.16 + ((seed >>> 5) % 200) / 200 * 0.12,
        size: 0.7 + ((seed >>> 13) % 300) / 300 * 1.3,
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

    /* ---------- Ombre au sol : le blob repose sur quelque chose ---------- */

    const drawShadow = (S: number, R: number, time: number, level: number, muted: boolean): void => {
      const cx = S / 2;
      const groundY = S / 2 + R * 1.02;
      const breathe = 0.5 + 0.5 * Math.sin(time * 0.7);
      const spread = 1 + level * 0.06;
      context.save();
      context.translate(cx, groundY);
      context.scale(1, 0.2);
      const shadow = context.createRadialGradient(0, 0, R * 0.1, 0, 0, R * 1.05 * spread);
      shadow.addColorStop(0, rgba(muted ? '#1A1B24' : '#1B0F4A', 0.55 + 0.04 * breathe));
      shadow.addColorStop(0.55, rgba(muted ? '#121319' : '#140B36', 0.26));
      shadow.addColorStop(1, rgba('#000000', 0));
      context.fillStyle = shadow;
      context.beginPath();
      context.arc(0, 0, R * 1.05 * spread, 0, TAU);
      context.fill();
      context.restore();
    };

    /* ---------- Halo doux derrière (cyan, respiration réelle) ---------- */

    const drawHalo = (S: number, R: number, time: number, level: number, phase: DotPhase): void => {
      const cx = S / 2;
      const cy = S / 2;
      if (phase === 'error') return;
      const radius = Math.min(R * (1.5 + 0.05 * Math.sin(time * 0.6) + level * 0.16), S * 0.49);
      const halo = context.createRadialGradient(cx, cy, R * 0.7, cx, cy, radius);
      const tint = phase === 'listening' ? CYAN : VIOLET;
      const strength = phase === 'listening' ? 0.16 : 0.11;
      halo.addColorStop(0, rgba(tint, strength + level * 0.06));
      halo.addColorStop(0.55, rgba(tint, (strength + level * 0.05) * 0.34));
      halo.addColorStop(1, rgba(tint, 0));
      context.fillStyle = halo;
      context.beginPath();
      context.arc(cx, cy, radius, 0, TAU);
      context.fill();
    };

    /* ---------- L'anneau signature, au-dessus de la tête ---------- */

    const drawRing = (
      time: number,
      R: number,
      level: number,
      phase: DotPhase,
      tilt: number,
      headTop: number,
    ): void => {
      const muted = phase === 'error';
      const bob = Math.sin(time * 1.55) * R * 0.022;
      const spin = phase === 'thinking' ? Math.sin(time * 1.6) * 0.34 : 0;
      const pulse = phase === 'speaking' ? level : 0;
      const centerY = headTop - R * 0.2 + bob;
      const rx = R * (0.3 + pulse * 0.035);
      const ry = R * (0.088 + pulse * 0.02);

      context.save();
      context.translate(0, centerY);
      context.rotate(tilt * 0.9 + spin);
      context.beginPath();
      context.ellipse(0, 0, rx, ry, 0, 0, TAU);
      context.lineWidth = Math.max(2.4, R * 0.033);
      context.strokeStyle = muted ? rgba('#6F7284', 0.6) : rgba(CYAN, 0.92);
      context.stroke();

      if (!muted) {
        context.beginPath();
        context.ellipse(0, 0, rx, ry, 0, 0, TAU);
        context.lineWidth = Math.max(4, R * 0.09);
        context.strokeStyle = rgba(CYAN, 0.14 + pulse * 0.16);
        context.stroke();
      }
      context.restore();
    };

    /* ---------- Le personnage ---------- */

    const drawCharacter = (S: number, time: number, level: number, phase: DotPhase): void => {
      const cx = S / 2;
      const cy = S / 2 + S * 0.02;
      const R = S * 0.315;
      const muted = phase === 'error';
      const calm = phase === 'idle' || muted;

      // --- Respiration, squash & stretch, inclinaison ------------------
      const breath = 1 + 0.014 * Math.sin(time * 0.85);
      let scaleX = breath;
      let scaleY = breath;
      if (phase === 'speaking') {
        scaleX *= 1 + 0.055 * level;
        scaleY *= 1 - 0.06 * level;
      } else if (phase === 'listening') {
        // Il se penche vers la voix, légèrement plus haut.
        scaleY *= 1 + 0.012 * Math.sin(time * 1.3);
      }
      scaleY *= 0.92; // galet plus large que haut
      scaleX *= 1.03;

      const gaze = gazeRef.current;
      const tiltBase =
        phase === 'listening'
          ? gaze.x * 0.06
          : phase === 'thinking'
            ? 0.03 * Math.sin(time * 0.8)
            : phase === 'speaking'
              ? 0.016 * Math.sin(time * 1.9) * (0.4 + level)
              : 0.024 * Math.sin(time * 0.5);
      const tilt = tiltBase;

      // Le regard : vers le curseur en écoute, sinon dérive / saccades.
      let lookX = 0;
      let lookY = 0;
      if (phase === 'listening') {
        lookX = gaze.x * 0.9;
        lookY = gaze.y * 0.7 + 0.18;
      } else if (phase !== 'thinking') {
        lookX = gaze.hasPointer ? gaze.x * 0.55 : Math.sin(time * 0.37) * 0.2;
        lookY = gaze.hasPointer ? gaze.y * 0.4 : Math.cos(time * 0.29) * 0.12;
      }

      const face = faceFor(phase, level, time);
      if (phase !== 'thinking') {
        face.lookX = lookX;
        face.lookY = lookY;
      }

      // --- Clignement ---------------------------------------------------
      const blinkState = blinkRef.current;
      const blinkProgress = (time - blinkState.at) / 0.2;
      let blink = 1;
      if (blinkProgress >= 0 && blinkProgress <= 1) {
        blink = 1 - Math.sin(Math.PI * blinkProgress) * 0.94;
      }

      drawHalo(S, R, time, level, phase);
      drawShadow(S, R, time, level, muted);

      context.save();
      context.translate(cx, cy);
      context.rotate(tilt);
      context.scale(scaleX, scaleY);

      // --- Corps ---------------------------------------------------------
      traceBlob(context, R, time, 1, 1, calm ? 0.8 : 1);
      const body = context.createLinearGradient(-R * 0.5, -R, R * 0.6, R);
      if (muted) {
        body.addColorStop(0, '#8E8E9E');
        body.addColorStop(0.5, '#5E5F70');
        body.addColorStop(1, '#454656');
      } else if (phase === 'listening') {
        body.addColorStop(0, '#A79AFF');
        body.addColorStop(0.48, '#6F63FF');
        body.addColorStop(1, BLUE);
      } else if (phase === 'speaking') {
        body.addColorStop(0, '#A294FF');
        body.addColorStop(0.5, VIOLET);
        body.addColorStop(1, BLUE);
      } else {
        body.addColorStop(0, '#9E92FF');
        body.addColorStop(0.52, '#6153F5');
        body.addColorStop(1, '#2B5BDB');
      }
      context.fillStyle = body;
      context.fill();

      // Modelé d'argile : lumière douce en haut à gauche, ombre en bas.
      context.save();
      traceBlob(context, R, time, 1, 1, calm ? 0.8 : 1);
      context.clip();

      const light = context.createRadialGradient(
        -R * 0.42,
        -R * 0.52,
        R * 0.05,
        -R * 0.3,
        -R * 0.3,
        R * 1.35,
      );
      light.addColorStop(0, `rgba(255, 255, 255, ${muted ? 0.1 : 0.2})`);
      light.addColorStop(0.45, 'rgba(255, 255, 255, 0.03)');
      light.addColorStop(1, 'rgba(255, 255, 255, 0)');
      context.fillStyle = light;
      context.fillRect(-R * 1.2, -R * 1.2, R * 2.4, R * 2.4);

      const shade = context.createRadialGradient(
        R * 0.4,
        R * 0.5,
        R * 0.1,
        R * 0.2,
        R * 0.35,
        R * 1.15,
      );
      shade.addColorStop(0, 'rgba(9, 3, 32, 0)');
      shade.addColorStop(1, `rgba(9, 3, 32, ${muted ? 0.34 : 0.26})`);
      context.fillStyle = shade;
      context.fillRect(-R * 1.2, -R * 1.2, R * 2.4, R * 2.4);

      // Teinte cyan en bas : l'identité de Kwes, sans brillance de verre.
      const bottom = context.createRadialGradient(0, R * 0.95, 0, 0, R * 0.85, R * 0.85);
      bottom.addColorStop(0, rgba(muted ? '#7C808E' : CYAN, muted ? 0.1 : 0.12 + level * 0.07));
      bottom.addColorStop(1, rgba(CYAN, 0));
      context.fillStyle = bottom;
      context.fillRect(-R, -R, R * 2, R * 2);

      // Grain : la matière.
      if (grainPattern) {
        context.save();
        context.globalCompositeOperation = 'overlay';
        context.globalAlpha = 0.75;
        context.fillStyle = grainPattern;
        context.fillRect(-R * 1.2, -R * 1.2, R * 2.4, R * 2.4);
        context.restore();
      }
      context.restore();

      // Bord : un liseré très fin, mat (pas de reflet).
      traceBlob(context, R, time, 1, 1, calm ? 0.8 : 1);
      context.lineWidth = Math.max(1.4, R * 0.012);
      context.strokeStyle = muted ? rgba('#2A2B33', 0.5) : rgba('#2A1C6B', 0.42);
      context.stroke();

      // --- Visage --------------------------------------------------------
      const eyeY = -R * 0.14;
      const eyeR = R * 0.185;
      const eyeX = R * 0.345;
      const gazeShift = face.lookX * eyeR * 0.26;

      for (const side of [-1, 1] as const) {
        drawEye(
          context,
          side * eyeX + gazeShift,
          eyeY + face.lookY * eyeR * 0.2,
          eyeR * (phase === 'thinking' ? 0.94 : 1),
          eyeR * 1.1,
          face,
          blink,
          side,
          time,
        );
      }

      drawMouth(context, R * 0.26, R, face, level, time);

      // Joues : deux touches cyan très douces, uniquement quand il s'anime.
      if (!muted && (phase === 'speaking' || phase === 'listening')) {
        for (const side of [-1, 1] as const) {
          const blush = context.createRadialGradient(
            side * R * 0.48,
            R * 0.16,
            0,
            side * R * 0.48,
            R * 0.16,
            R * 0.2,
          );
          blush.addColorStop(0, rgba(CYAN, 0.16 + level * 0.1));
          blush.addColorStop(1, rgba(CYAN, 0));
          context.fillStyle = blush;
          context.beginPath();
          context.arc(side * R * 0.48, R * 0.16, R * 0.2, 0, TAU);
          context.fill();
        }
      }

      // --- L'anneau signature -------------------------------------------
      drawRing(time, R, level, phase, tilt, -R * 0.98);

      context.restore();

      /* ---------- Signatures d'état, hors du corps ---------- */

      if (phase === 'thinking') {
        // Petites particules qui montent : la réflexion se voit, discrètement.
        context.save();
        for (const particle of particles) {
          const progress = (((time * particle.speed + particle.offset) % 1) + 1) % 1;
          const y = cy + R * (0.9 - progress * 2.1);
          const x = cx + R * (particle.drift * (0.6 + progress)) + Math.sin(time + particle.offset * 8) * R * 0.06;
          const alpha = Math.sin(Math.PI * progress) * 0.9;
          context.beginPath();
          context.arc(x, y, particle.size * (R / 150), 0, TAU);
          context.fillStyle = rgba('#DCD6FF', alpha);
          context.fill();
        }
        context.restore();
      }

    };

    const render = (time: number): void => {
      resize();
      if (width < 2 || height < 2) return;
      const S = Math.min(width, height);
      const phase = phaseRef.current;
      const level = clamp01(levelRef?.current ?? 0);

      // Clignement : jamais pendant une erreur, moins souvent quand il parle.
      const blink = blinkRef.current;
      if (phase !== 'error' && time > blink.next) {
        blink.at = time;
        const gap = phase === 'speaking' ? 3.4 + Math.random() * 1.6 : 2.8 + Math.random() * 2.6;
        blink.next = time + gap;
      }

      // Regard : interpolation douce (le suivi ne doit pas trembler).
      const gaze = gazeRef.current;
      gaze.x = mix(gaze.x, gaze.targetX, 0.08);
      gaze.y = mix(gaze.y, gaze.targetY, 0.08);

      context.clearRect(0, 0, width, height);
      context.save();
      context.translate((width - S) / 2, (height - S) / 2);
      drawCharacter(S, time, level, phase);
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
      // Image figée mais complète : même visage, même anneau, aucun mouvement.
      render(2.2);
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
            if (reducedRef.current) render(2.2);
          });
    observer?.observe(canvas);

    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', onVisibility);
      observer?.disconnect();
    };
    // `phase` : en mouvement réduit, l'image statique est redessinée à chaque
    // changement d'état. Les constantes de temps, elles, continuent de courir.
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
