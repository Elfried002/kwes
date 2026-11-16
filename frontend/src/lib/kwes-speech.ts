/**
 * Parole partagée — helpers purs, sans React ni DOM.
 *
 * L'écran vocal (`use-voice-conversation`) et l'accueil (`HomeScreen`) lisent
 * la même réponse : le sous-titre ne doit jamais courir plus vite que la voix.
 * Ces fonctions traduisent une position de lecture réelle (audio) ou un
 * événement de frontière (voix de l'appareil) en texte affichable.
 *
 * Rien n'est inventé : `revealCaption` ne fait que couper la phrase réellement
 * prononcée au dernier mot complet déjà atteint.
 */

function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value;
}

/**
 * Part de la phrase déjà prononcée, à partir de la lecture réelle.
 * `duration` inconnue (métadonnées absentes) → 0 : on n'affiche pas d'avance.
 */
export function playbackFraction(currentTime: number, duration: number): number {
  if (!Number.isFinite(currentTime) || !Number.isFinite(duration) || duration <= 0) return 0;
  return clamp(currentTime / duration, 0, 1);
}

/**
 * Sous-titre : la phrase, révélée au rythme de la parole.
 * On s'arrête toujours sur une frontière de mot — jamais « Bonjou ».
 */
export function revealCaption(sentence: string, fraction: number): string {
  const text = (sentence ?? '').trim();
  if (!text) return '';
  const part = clamp(Number.isFinite(fraction) ? fraction : 0, 0, 1);
  if (part >= 1) return text;

  const firstSpace = text.indexOf(' ');
  // Dès que la voix démarre, le premier mot est déjà en train d'être dit.
  const floor = firstSpace < 0 ? text.length : firstSpace;
  const target = Math.max(floor, Math.round(text.length * part));
  if (target >= text.length) return text;
  const cut = text.slice(0, target);
  const lastSpace = cut.lastIndexOf(' ');
  // Un seul mot : il n'y a pas de frontière, on montre ce qui est prononcé.
  if (lastSpace < 0) return cut;
  return cut.slice(0, lastSpace).trimEnd();
}

/**
 * Durée estimée d'une phrase lue par la voix de l'appareil (~14 caractères/s).
 * Sert uniquement de filet : si le moteur n'émet ni `end` ni `boundary`, la
 * file audio ne doit pas rester bloquée.
 */
export function estimateSpeechMs(text: string): number {
  const length = (text ?? '').trim().length;
  return Math.max(700, Math.round(length * 70));
}

/**
 * Cadence visuelle de la bouche quand la voix de l'appareil parle.
 *
 * `speechSynthesis` ne donne pas accès à son signal : impossible de mesurer
 * une amplitude réelle comme pour l'audio ElevenLabs. Cette oscillation ne
 * prétend pas décrire le son — elle anime la bouche pendant que le moteur
 * *parle réellement* (fait vérifié par `speechSynthesis.speaking`), et
 * s'arrête avec lui. Aucun contenu n'est inventé.
 */
export function speechEnvelope(seconds: number): number {
  const time = Number.isFinite(seconds) ? seconds : 0;
  const cadence = 0.5 + 0.5 * Math.sin(time * 9.1);
  const breath = 0.5 + 0.5 * Math.sin(time * 3.7 + 1.1);
  return clamp(0.14 + 0.4 * cadence * (0.5 + 0.5 * breath), 0.1, 0.72);
}
