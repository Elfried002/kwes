import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { KwesDroid } from '../components/KwesDroid';
import { BrandMark } from '../components/BrandMark';
import { InstallApp } from '../components/InstallApp';
import { Icon, type IconName } from '../components/Icon';

/**
 * Page publique de Kwes.
 *
 * Règles de contenu : uniquement des faits vérifiables sur le produit. Aucun
 * client, logo, témoignage, chiffre d'usage ni promesse de classement n'est
 * affiché. Les captures proviennent de l'application elle-même (dossier
 * `public/shots`), jamais d'une maquette.
 */

/* ---------- Révélation au défilement (IntersectionObserver, sans librairie) ---------- */

function useReveal(): void {
  useLayoutEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || typeof IntersectionObserver === 'undefined') return;
    if (!document.querySelector('[data-reveal]')) return;

    const root = document.documentElement;
    root.dataset.reveal = 'on';

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add('is-revealed');
          observer.unobserve(entry.target);
        }
      },
      { rootMargin: '0px 0px -10% 0px', threshold: 0.08 },
    );

    for (const node of document.querySelectorAll('[data-reveal]')) observer.observe(node);

    return () => {
      observer.disconnect();
      delete root.dataset.reveal;
    };
  }, []);
}

function useScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = (): void => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return scrolled;
}

/* ---------- Petits blocs ---------- */

function Shot({
  src,
  alt,
  caption,
  className,
  priority = false,
}: {
  src: string;
  alt: string;
  caption?: string;
  className?: string;
  priority?: boolean;
}) {
  return (
    <figure className={`shot ${className ?? ''}`}>
      <div className="shot__frame">
        <div className="shot__bar" aria-hidden="true">
          <span className="shot__dot" />
          <span className="shot__dot" />
          <span className="shot__dot" />
          <span className="shot__label">Kwes · application</span>
        </div>
        <img
          src={src}
          alt={alt}
          width={1440}
          height={900}
          loading={priority ? 'eager' : 'lazy'}
          decoding="async"
        />
      </div>
      {caption ? <figcaption>{caption}</figcaption> : null}
    </figure>
  );
}

interface Capability {
  kicker: string;
  title: string;
  body: string;
  icon: IconName;
  media?: { src: string; alt: string };
  variant?: 'hero' | 'side' | 'wide';
  grants?: Array<{ code: string; text: string }>;
  limit?: string;
}

const CAPABILITIES: Capability[] = [
  {
    kicker: 'Conversation',
    title: 'Une conversation qui garde le fil',
    body: 'Chaque échange est enregistré côté serveur, rattaché à sa conversation et, si vous le demandez, à la mission correspondante. L’historique reste consultable.',
    icon: 'chat',
    media: {
      src: '/shots/chat.png',
      alt: 'Capture de l’écran de conversation de Kwes : question envoyée et réponse argumentée en trois points.',
    },
    variant: 'hero',
  },
  {
    kicker: 'Missions',
    title: 'Des missions, pas des réponses',
    body: 'Un objectif devient un enchaînement d’étapes dépendantes. Chaque étape est exécutée par un skill authorisé et la progression affichée vient du serveur.',
    icon: 'activity',
    media: {
      src: '/shots/missions.png',
      alt: 'Capture de la liste des missions : trois missions, leur statut et leur pourcentage d’avancement.',
    },
    variant: 'side',
  },
  {
    kicker: 'Recherche',
    title: 'Lire, pas improviser',
    body: 'La recherche et la lecture se limitent à des domaines autorisés, en lecture seule. Une page qui dépend de JavaScript est rendue puis lue, sans exécuter d’action.',
    icon: 'external',
    grants: [
      { code: 'web.search', text: 'chercher dans les domaines autorisés' },
      { code: 'web.read', text: 'lire une page, y compris rendue' },
      { code: 'allowlist', text: 'validée côté serveur, jamais par le modèle' },
    ],
    limit: 'Aucune écriture, aucun formulaire rempli, aucun achat : la lecture seule est une contrainte du skill, pas une option d’interface.',
  },
  {
    kicker: 'Planification',
    title: 'Un plan que vous pouvez contester',
    body: 'Cadrage, analyse, plan d’action, ressources, mesure : la planification produit un artefact structuré, avec risques et indicateurs, pas un paragraphe vague.',
    icon: 'spark',
    media: {
      src: '/shots/mission-detail.png',
      alt: 'Capture du détail d’une mission : progression, liste des étapes et résultat produit.',
    },
  },
  {
    kicker: 'Voix',
    title: 'La voix quand elle sert',
    body: 'Dictée navigateur après autorisation explicite. La lecture audio ne démarre que sur un fichier réellement synthétisé par le fournisseur configuré : aucun son n’est simulé.',
    icon: 'mic',
    media: {
      src: '/shots/composer.png',
      alt: 'Capture de la zone de saisie de Kwes, avec le bouton de dictée et le bouton d’envoi.',
    },
  },
  {
    kicker: 'Validation',
    title: 'Rien de sensible sans vous',
    body: 'Une action classée R2 ou au-delà interrompt la mission. La demande affiche l’action, la charge utile et son empreinte ; l’accord expire.',
    icon: 'shield',
    media: {
      src: '/shots/validations.png',
      alt: 'Capture de l’écran de validations : une demande en attente avec son type d’action et son échéance.',
    },
    variant: 'wide',
  },
];

const PROOF: Array<{ title: string; detail: string }> = [
  { title: 'Orb piloté par une machine à états', detail: 'Aucun état déduit du texte du modèle.' },
  { title: 'Validation liée à une empreinte', detail: 'Une charge utile modifiée invalide l’accord donné.' },
  { title: 'Clé publique uniquement', detail: 'Aucune clé de service dans le navigateur.' },
  { title: 'Progression issue du serveur', detail: 'Événements temps réel, repli par lecture REST.' },
  { title: 'Aucun témoignage, aucun logo client', detail: 'Cette page ne contient que des faits sur le produit.' },
];

const SECTIONS = [
  { id: 'produit', label: 'Produit' },
  { id: 'missions', label: 'Missions' },
  { id: 'controle', label: 'Contrôle' },
  { id: 'visibilite', label: 'Visibilité' },
];

/* ---------- Page ---------- */

export function PublicHome() {
  useReveal();
  const scrolled = useScrolled();
  const mainRef = useRef<HTMLElement | null>(null);

  const scrollToSection = useCallback((event: ReactMouseEvent<HTMLAnchorElement>, id: string) => {
    const target = document.getElementById(id);
    if (!target) return;
    event.preventDefault();
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    window.history.replaceState(null, '', `#${id}`);
  }, []);

  return (
    <div className="site">
      <a
        className="skip-link"
        href="#contenu"
        onClick={(event) => {
          event.preventDefault();
          mainRef.current?.focus();
        }}
      >
        Aller au contenu principal
      </a>

      <header className="site-head" data-scrolled={scrolled ? 'true' : 'false'}>
        <div className="wrap site-head__inner">
          <a className="site-brand" href="#/" aria-label="Kwes — accueil">
            <BrandMark size={32} />
            <span>Kwes</span>
          </a>

          <nav className="site-nav" aria-label="Sections de la page">
            {SECTIONS.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                onClick={(event) => scrollToSection(event, section.id)}
              >
                {section.label}
              </a>
            ))}
          </nav>

          <div className="site-head__actions">
            <InstallApp variant="ghost" size="sm" className="site-head__install" />
            <a className="btn btn--ghost btn--sm" href="#/connexion">
              Se connecter
            </a>
            <a className="btn btn--primary btn--sm" href="#/inscription">
              Créer un compte
            </a>
          </div>
        </div>
      </header>

      <main id="contenu" ref={mainRef} tabIndex={-1} className="site-main">
        <section className="site-hero" aria-labelledby="hero-title">
          <span className="site-hero__gridlines" aria-hidden="true" />
          <div className="wrap site-hero__grid">
            <div className="site-hero__copy" data-reveal>
              <p className="eyebrow">Agent personnel autonome</p>
              <h1 id="hero-title" className="site-h1">
                Un agent qui travaille.
                <span className="site-h1__soft"> Vous décidez.</span>
              </h1>
              <p className="site-hero__lede">
                Kwes transforme une intention en mission : il planifie, agit avec des outils
                volontairement limités, affiche son avancement réel — et s’arrête pour vous demander
                validation dès qu’une action devient sensible.
              </p>

              <div className="site-hero__actions">
                <a className="btn btn--primary btn--lg" href="#/parler">
                  Parler à Kwes
                </a>
                <a className="btn btn--lg" href="#/inscription">
                  Créer un compte
                </a>
              </div>

              <ul className="site-hero__facts">
                <li>
                  <Icon name="check" size={15} /> Compte sans carte bancaire
                </li>
                <li>
                  <Icon name="check" size={15} /> Validation avant toute action sensible
                </li>
              </ul>
            </div>

            <div className="site-hero__visual" data-reveal style={{ '--reveal-delay': '90ms' } as CSSProperties}>
              <KwesDroid phase="idle" className="droid--site" />
              <p className="site-hero__status">
                <span className="site-hero__dot" aria-hidden="true" />
                Disponible en français et en anglais
              </p>
            </div>
          </div>
        </section>

        <section className="site-section" id="produit" aria-labelledby="produit-title">
          <div className="wrap">
            <div className="site-head-block" data-reveal>
              <div>
                <p className="eyebrow">01 — Capacités</p>
                <h2 id="produit-title" className="site-h2">
                  Ce que Kwes fait vraiment
                </h2>
              </div>
              <p className="site-lede">
                Six fonctions, décrites avec leurs limites. Chaque aperçu ci-dessous est une capture
                de l’application en fonctionnement, pas une illustration.
              </p>
            </div>

            <div className="caps">
              {CAPABILITIES.map((cap, index) => (
                <article
                  key={cap.kicker}
                  className={`cap ${cap.variant ? `cap--${cap.variant}` : ''}`}
                  data-reveal
                  style={{ '--reveal-delay': `${Math.min(index, 3) * 60}ms` } as CSSProperties}
                >
                  <div className="cap__text">
                    <p className="cap__kicker">
                      <Icon name={cap.icon} size={14} />
                      {cap.kicker}
                    </p>
                    <h3 className="cap__title">{cap.title}</h3>
                    <p className="cap__body">{cap.body}</p>
                    {cap.grants ? (
                      <dl className="cap__grants">
                        {cap.grants.map((grant) => (
                          <div key={grant.code}>
                            <dt>{grant.code}</dt>
                            <dd>{grant.text}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : null}
                    {cap.limit ? <p className="cap__limit">{cap.limit}</p> : null}
                  </div>
                  {cap.media ? (
                    <div className="cap__media">
                      <img
                        src={cap.media.src}
                        alt={cap.media.alt}
                        width={1440}
                        height={900}
                        loading="lazy"
                        decoding="async"
                      />
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="site-section" id="missions" aria-labelledby="missions-title">
          <div className="wrap split">
            <div className="split__aside" data-reveal>
              <p className="eyebrow">02 — Exécution</p>
              <h2 id="missions-title" className="site-h2">
                Il travaille pendant que vous faites autre chose
              </h2>
              <p className="site-lede">
                Une mission se décompose en étapes qui peuvent dépendre les unes des autres. Vous
                suivez l’avancement sans relancer quoi que ce soit : la progression est recalculée
                côté serveur et poussée en temps réel.
              </p>

              <ul className="states">
                <li>
                  <span className="states__pill states__pill--run">En cours</span>
                  Une étape s’exécute, les suivantes attendent leur dépendance.
                </li>
                <li>
                  <span className="states__pill states__pill--wait">Validation</span>
                  La mission s’arrête net tant que vous n’avez pas tranché.
                </li>
                <li>
                  <span className="states__pill states__pill--done">Terminée</span>
                  Le résultat affiché est celui enregistré par le serveur.
                </li>
              </ul>

              <p className="site-note site-note--inline">
                <Icon name="clock" size={15} />
                Vous pouvez mettre une mission en pause, la reprendre ou l’annuler à tout moment.
              </p>
            </div>

            <div className="split__media" data-reveal style={{ '--reveal-delay': '80ms' } as CSSProperties}>
              <Shot
                src="/shots/mission-detail.png"
                alt="Capture du détail d’une mission Kwes : progression à 100 %, trois étapes terminées et résultat produit."
                caption="Capture réelle — mission « Brief de lancement — pack Pro », trois étapes, 100 %."
              />
            </div>
          </div>
        </section>

        <section className="site-section" id="controle" aria-labelledby="controle-title">
          <div className="wrap">
            <div className="site-head-block" data-reveal>
              <div>
                <p className="eyebrow">03 — Contrôle</p>
                <h2 id="controle-title" className="site-h2">
                  Vous gardez la main
                </h2>
              </div>
              <p className="site-lede">
                Le contrôle n’est pas une case cochée dans les réglages : c’est un arrêt dans le
                déroulé de la mission, décidé par un moteur de politiques exécuté côté serveur.
              </p>
            </div>

            <div className="control">
              <div className="control__list" data-reveal>
                <div className="control__item">
                  <span className="control__num" aria-hidden="true">
                    A
                  </span>
                  <div>
                    <h3>Approbations</h3>
                    <p>
                      La demande contient l’action, la charge utile et son empreinte. Un accord donné
                      pour une charge ne vaut pas pour une autre, et il expire.
                    </p>
                  </div>
                </div>
                <div className="control__item">
                  <span className="control__num" aria-hidden="true">
                    B
                  </span>
                  <div>
                    <h3>Journal d’actions</h3>
                    <p>
                      Chaque décision du moteur est tracée côté serveur : acteur, action, décision,
                      horodatage. L’interface affiche l’état confirmé, jamais un état supposé.
                    </p>
                  </div>
                </div>
                <div className="control__item">
                  <span className="control__num" aria-hidden="true">
                    C
                  </span>
                  <div>
                    <h3>Permissions par capacité</h3>
                    <p>
                      Un skill déclare ses droits — lecture web, écriture locale — et un manifeste ne
                      peut pas élargir l’allowlist du serveur. Une capacité inconnue est refusée par
                      défaut.
                    </p>
                  </div>
                </div>
              </div>

              <div data-reveal style={{ '--reveal-delay': '80ms' } as CSSProperties}>
                <Shot
                  src="/shots/validations.png"
                  alt="Capture de l’écran de validations de Kwes : demande en attente, type d’action, échéance et boutons Approuver et Refuser."
                  caption="Capture réelle — demande de validation en attente pour une publication externe."
                />
              </div>
            </div>
          </div>
        </section>

        <section className="site-section" id="visibilite" aria-labelledby="visibilite-title">
          <div className="wrap vis">
            <div data-reveal>
              <p className="eyebrow">04 — Visibilité</p>
              <h2 id="visibilite-title" className="site-h2">
                Visible et trouvable, sans promesse
              </h2>
              <p className="site-lede">
                Cette page est écrite pour être lue par des personnes et comprise par les moteurs :
                titre et description explicites, URL canonique, données structurées décrivant
                l’application, plan du site et règles de robot explicites.
              </p>

              <div className="vis__cols">
                <div>
                  <h3>Structure</h3>
                  <p>Sections nommées, hiérarchie de titres continue, une seule URL publique.</p>
                </div>
                <div>
                  <h3>Réponses</h3>
                  <p>Chaque capacité est décrite avec sa limite, sans superlatif ni chiffre inventé.</p>
                </div>
                <div>
                  <h3>Traçabilité</h3>
                  <p>Aucune note, aucun avis, aucune certification revendiquée sur cette page.</p>
                </div>
              </div>

              <p className="site-note">
                <Icon name="alert" size={15} />
                Aucune position dans un moteur de recherche ni citation par un assistant n’est promise
                ici : ces résultats dépendent des moteurs, de la concurrence et du temps.
              </p>
            </div>

            <div className="spec" data-reveal style={{ '--reveal-delay': '70ms' } as CSSProperties}>
              <div className="spec__head">
                <p className="eyebrow">05 — Vérifiable</p>
                <h2 className="site-h3">Ce que vous pouvez vérifier vous-même</h2>
              </div>
              <dl className="spec__list">
                {PROOF.map((item, index) => (
                  <div className="spec__row" key={item.title}>
                    <span className="spec__index" aria-hidden="true">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <dt>{item.title}</dt>
                    <dd>{item.detail}</dd>
                  </div>
                ))}
              </dl>
              <p className="spec__foot">
                Ni logo client, ni témoignage, ni chiffre d’usage sur cette page : uniquement des
                faits sur le produit.
              </p>
            </div>
          </div>
        </section>

        <section className="site-cta" aria-labelledby="cta-title">
          <div className="wrap">
            <p className="eyebrow eyebrow--center">Commencer</p>
            <h2 id="cta-title" className="site-cta__title">
              Commencez par une conversation.
            </h2>
            <p className="site-cta__lede">
              Créez votre compte en quelques secondes. Vous pourrez arrêter une mission, refuser une
              action ou fermer votre session quand vous le souhaitez.
            </p>
            <div className="site-cta__actions">
              <a className="btn btn--primary btn--lg" href="#/inscription">
                Créer un compte
              </a>
              <a className="btn btn--lg" href="#/connexion">
                J’ai déjà un compte
              </a>
            </div>

            <div className="site-cta__install">
              <p>
                Ou installez Kwes directement : une icône sur votre écran d’accueil, un affichage
                plein écran, aucun magasin d’applications.
              </p>
              <InstallApp variant="soft" />
            </div>
          </div>
        </section>
      </main>

      <footer className="site-foot">
        <div className="wrap site-foot__grid">
          <div className="site-foot__brand">
            <a className="site-brand" href="#/" aria-label="Kwes — accueil">
              <img src="/brand/droid-head.svg" alt="" width={30} height={30} />
              <span>Kwes</span>
            </a>
            <p>Agent personnel autonome, avec validation humaine.</p>
          </div>

          <nav className="site-foot__col" aria-labelledby="foot-produit">
            <h2 id="foot-produit">Produit</h2>
            <a href="#produit" onClick={(event) => scrollToSection(event, 'produit')}>
              Capacités
            </a>
            <a href="#missions" onClick={(event) => scrollToSection(event, 'missions')}>
              Missions
            </a>
            <a href="#controle" onClick={(event) => scrollToSection(event, 'controle')}>
              Contrôle
            </a>
          </nav>

          <nav className="site-foot__col" aria-labelledby="foot-compte">
            <h2 id="foot-compte">Compte</h2>
            <a href="#/connexion">Se connecter</a>
            <a href="#/inscription">Créer un compte</a>
            <a href="#/mot-de-passe-oublie">Mot de passe oublié</a>
          </nav>


        </div>

        <div className="wrap site-foot__bottom">
          <p>© 2026 Kwes</p>
          <p>Captures de l’application Kwes.</p>
        </div>
      </footer>
    </div>
  );
}
