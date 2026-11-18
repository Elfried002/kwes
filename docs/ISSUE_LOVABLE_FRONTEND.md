# Reprise du frontend de Kwes — état réel, règles à respecter, travail restant

Ce ticket est le point d'entrée pour continuer le frontend de **Kwes**, l'agent personnel autonome. Il décrit ce qui existe, ce qui a été mesuré, ce qui est interdit de réintroduire, et les chantiers à mener. Le backend est **hors périmètre** : il tourne, il est testé, ses contrats sont figés ici.

- **Dépôt** : `Elfried002/kwes` (privé) — branche de travail `alpha/jour-1`
- **Production** : https://www.agent-kwes.com (secours : https://kwes.vercel.app)
- **Déploiement** : automatique. Chaque push sur `alpha/jour-1` part en production ; chaque branche ou PR ouvre une prévisualisation.
- **Code** : React 18 + TypeScript + Vite. **CSS écrit à la main**, aucun Tailwind, aucune librairie UI. Ne pas en introduire.

---

## 1. Le produit en une phrase

On parle à Kwes, il comprend l'intention, planifie, exécute avec des outils vérifiés, demande une validation quand l'action est sensible, puis rend compte. Interface **en français**, **mobile d'abord**, avec un personnage — un droïde vivant — qui montre ce qu'il fait.

Trois surfaces :

| Surface | Rôle | Comportement |
|---|---|---|
| Accueil `#/` | Écrire à Kwes | Réponse **écrite**, jamais parlée |
| Conversation `#/chat/:id` | Fil de discussion | Bulles type messagerie, historique |
| Voix `#/parler` | Parler à Kwes | Micro **automatique**, plein écran |

---

## 2. Lancer le projet

```bash
git clone https://github.com/Elfried002/kwes.git
cd kwes/frontend
npm ci
npm run dev          # http://127.0.0.1:5173
npm run test         # 134 tests (vitest)
npm run build        # tsc --noEmit + vite build
```

Le frontend parle à l'API publique `https://n8n.streetflexs.store/kwes-api/api/v1` (variable `VITE_API_BASE_URL`). En local, créer `frontend/.env.production` avec `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` — **ces valeurs ne sont pas dans le dépôt**, les demander au propriétaire. Sans elles le build pointe sur `127.0.0.1` et l'interface affiche « Backend injoignable ».

Authentification : Supabase, session stockée dans `localStorage` sous la clé `kwes.auth.supabase`. Toutes les requêtes API envoient `Authorization: Bearer <access_token>`.

---

## 3. Cartographie du code

```
src/
  screens/      HomeScreen, ChatScreen, ConversationsScreen, VoiceScreen,
                TasksScreen, TaskDetailScreen, ApprovalsScreen, SettingsScreen,
                LoginScreen, PublicHome
  components/   AppShell, MessageBubble, Composer, KwesDroid, Icon, BrandMark,
                OrbStatus, StatusPill, ConfirmDialog, EmptyState, ErrorBoundary, InstallApp
  lib/          api.ts (client + SSE), types.ts, router.ts (hash router maison),
                auth.ts, supabase.ts, prefs.ts, format.ts,
                use-gemini-live.ts (WebSocket voix), voice-session.ts,
                home-voice.ts (machine à états de l'accueil), use-audio-level.ts,
                kwes-speech.ts, speech.ts, ws.ts
  styles/       tokens.css, app.css, chat.css, home.css, voice-screen.css,
                login-brand.css, mobile-first.css, ui-polish.css, brand.css, site.css, voice.css
```

Routes : `/`, `/connexion`, `/inscription`, `/mot-de-passe-oublie`, `/chat/:id`, `/parler`, `/conversations`, `/tasks`, `/activity`, `/approvals`, `/settings`.

**Ordre d'import des CSS compte** : `mobile-first.css` est chargé en dernier et surcharge les autres. Toute nouvelle règle responsive va là.

### Points d'API consommés

```
POST  /chat                      (SSE : meta, delta, done)
GET   /conversations             GET /conversations/:id/messages
POST  /voice/ticket              → ticket court (le navigateur ne voit jamais la clé)
WS    /voice/live?ticket=…       audio PCM 16 kHz, activity_start/activity_end
GET   /voice/usage
GET   /documents/:id/download
GET   /tasks  /tasks/:id  /approvals  /approvals/:id
```

Le protocole vocal est figé : `start | audio | text | stop_audio | close` vers le serveur, `ready | state | audio | transcript | tool | interrupted | usage | error | closed` vers le client. **Ne pas modifier** sans coordination backend.

---

## 4. Règles UX non négociables

Ces règles viennent du propriétaire après deux semaines de corrections. Les réintroduire est un échec, pas un détail.

1. **Le chat écrit ne parle jamais.** Pas de synthèse vocale sur une réponse tapée, pas de bouton « Lire la réponse », pas d'élément `<audio>` créé. Si quelqu'un écrit, c'est pour lire.
2. **Aucun bouton menant ailleurs depuis la réponse** (« Lire la réponse », « Ouvrir dans les échanges »). La réponse s'affiche, point.
3. **L'écran vocal démarre le micro tout seul** à l'ouverture. **Pas de bouton micro.** Il reste la croix pour fermer ; toucher le droïde coupe et relance.
4. **Fil façon messagerie** : message de l'utilisateur en bulle à droite, réponse de Kwes à gauche avec avatar et nom `KWES`, heure dans la bulle. On doit voir qui a écrit quoi, comme dans WhatsApp.
5. **Mobile d'abord** : téléphone 390×844, tablette 820×1180, bureau 1440×900. Une colonne sur téléphone, rail de 76 px sur bureau, contenu centré max 1040 px.
6. **Le droïde est vivant** : il bouge la bouche quand il parle (pilotée par le niveau audio réel), pense, exécute, attend une validation, signale une erreur. Aucun état décoratif mensonger — s'il affiche « exécution », quelque chose s'exécute vraiment.
7. **Français, ton direct**, pas de jargon technique dans l'interface. Distinguer « planifié / en cours / terminé / bloqué » plutôt qu'afficher un pourcentage inventé.
8. **Accessibilité** : `prefers-reduced-motion` respecté, contrastes AA, navigation clavier, `aria-live` sur la conversation.

---

## 5. Ce qui est fait et vérifié

Mesures réelles, pas des intentions.

**Voix**
- Gemini Live, ticket court, WebSocket public en WSS via nginx.
- Latence avant le premier son : **694 ms médian, 974 ms au P95**.
- Barge-in mesuré : l'utilisateur reprend la parole → `interrupted` à **1,50 s**, zéro bloc audio ensuite.
- Session maintenue sur plusieurs tours (3 tours consécutifs vérifiés) après correction de deux bugs : `activity_end` orphelin et `receive()` qui se termine à chaque fin de tour.
- Micro automatique à l'ouverture de `#/parler`.

**Texte**
- Réponse écrite affichée en **2 s** sur une question simple ; premier fragment SSE à 1,16 s.
- Fil type messagerie avec avatar, nom, heure.
- Chat sans dictée vocale, sans bouton de lecture.

**Le reste**
- Connexion : écran dédié, carte unique, onglets connexion/inscription, icônes droïde (SVG + 32/64/180/192/512).
- PWA installable (manifest, icônes, thème), `InstallApp` sur mobile.
- Écrans tâches, approbations, documents présents et branchés.
- 134 tests frontend, `tsc` propre, build Vite sans erreur.

---

## 6. Chantiers à mener

Priorité par impact utilisateur. Chaque item a son critère d'acceptation — un item sans test réel n'est pas terminé.

### P0 — finir ce que l'utilisateur voit d'abord

- [ ] **Accueil** : hiérarchie visuelle du hero (titre, droïde, saisie) à revoir pour petits écrans 360×640 ; le droïde ne doit pas pousser la saisie sous la ligne de flottaison.
  *Acceptation* : sur 360×640, saisie visible sans scroll, aucun chevauchement avec les suggestions.
- [ ] **Réponse longue à l'accueil** : au-delà de ~6 lignes, la réponse doit défiler dans une zone bornée avec fondu, pas étirer la page.
  *Acceptation* : 1 500 caractères affichés sans casser la mise en page ; capture avant/après.
- [ ] **États vides** des conversations, tâches et approbations : message utile + action (« Démarrer une conversation »), pas une page blanche.
- [ ] **Erreurs réseau** : bandeau discret, réessai, jamais un écran mort. Le message « Backend injoignable » doit nommer l'action possible.
- [ ] **Streaming** : curseur de frappe fluide, pas de saut de mise en page quand le texte arrive.

### P1 — qualité perçue

- [ ] **Transitions** entre écrans (fondu léger, 150–200 ms), respect de `prefers-reduced-motion`.
- [ ] **Composer** : croissance automatique jusqu'à 6 lignes, `Entrée` envoie / `Maj+Entrée` retour à la ligne, état désactivé clair pendant l'envoi.
- [ ] **Fil** : regroupement des messages consécutifs du même auteur (avatar une seule fois), séparateurs de jour (« Aujourd'hui », « Hier »).
- [ ] **Copier / relancer** : actions au survol sur bureau, appui long sur mobile, retour visuel « Copié ».
- [ ] **Documents** : carte de téléchargement lisible (nom, taille, format), état de chargement.
- [ ] **Réglages** : langue vocale, voix, notifications — avec explication honnête de ce qui est expérimental (voir `docs/LANGUES_VOIX.md`).
- [ ] **Onboarding première visite** : 3 écrans max, ce que Kwes sait faire, ce qu'il ne sait pas encore, demande des permissions au moment utile.

### P2 — finitions

- [ ] Thème clair complet (le sombre est la référence), bascule persistée dans `kwes.prefs.v1`.
- [ ] Mode paysage téléphone (hauteur 390) sans écraser le droïde.
- [ ] Squelettes de chargement sur listes (conversations, tâches).
- [ ] Perf : bundle initial sous 300 kB gzip, préchargement de l'écran suivant au survol.
- [ ] Tests : couvrir l'accueil (envoi, réponse écrite), le fil (rendu par auteur), l'écran vocal (démarrage auto) — aujourd'hui couverts indirectement.

---

## 7. Design system

- Tokens dans `tokens.css` : `--surface`, `--surface-raised`, `--text`, `--muted`, accents bleus. Ne pas coder de couleur en dur ailleurs.
- Typographie : `Sora` (titres), `Instrument Sans` (texte), via `@fontsource-variable`.
- Rayons : 4 px côté « queue » de bulle, 16 px côté arrondi. Bulles max 86 % de largeur.
- Le droïde : `KwesDroid.tsx` + `kwes-droid.css`, états `idle / thinking / speaking / executing / success / waiting_approval / error`. La bouche réagit au niveau audio réel, jamais à un minuteur.
- Iconographie : composant `Icon` maison, jeu fermé. Ne pas ajouter une librairie d'icônes.

---

## 8. Pièges connus — à lire avant de coder

1. **CORS** : l'API n'accepte que des origines déclarées. Une nouvelle URL de prévisualisation doit être ajoutée côté backend, sinon « Backend injoignable ». Toute URL `*.vercel.app` de prévisualisation est acceptée ; pour un domaine, le demander.
2. **Vercel Security Checkpoint** : les navigateurs automatisés depuis le serveur de build sont parfois bloqués (403 « Failed to verify your browser »). Ce n'est pas un bug du frontend, c'est la protection anti-bot.
3. **Variables d'environnement** : `VITE_*` sont figées au build. Les changer impose un redéploiement. Elles sont déclarées sur Vercel (production, preview, development).
4. **Session Supabase** : clé `kwes.auth.supabase`. Un jeton expiré renvoie vers `#/connexion`, ce qui est normal.
5. **Voix** : ne jamais envoyer `activity_end` sans `activity_start` — Gemini ferme la session. Le serveur protège désormais contre ça, ne pas court-circuiter son protocole depuis le client.
6. **Pas de `Audio()` pour lire une réponse écrite.** Un `<audio>` créé dans le chat est un bug.
7. **Ne pas ajouter de dépendance UI** (Tailwind, shadcn, framer-motion, lucide…). Le style est écrit à la main et doit le rester.

---

## 9. Definition of Done

Une PR est acceptable si :

- [ ] `npm run build` et `npm run test` passent ;
- [ ] vérifié dans un vrai navigateur à 390×844, 820×1180 et 1440×900, captures jointes ;
- [ ] aucune des règles de la section 4 n'est contournée ;
- [ ] aucune couleur, taille ou espacement codé en dur hors tokens ;
- [ ] les états vides, de chargement et d'erreur sont traités ;
- [ ] pas de secret, pas de clé, pas de coordonnée bancaire dans le code ou une capture ;
- [ ] la prévisualisation Vercel de la PR est ouverte et testée.

---

## 10. Hors périmètre

Backend, modèle, base de données, RLS, protocole vocal, worker, sandbox d'exécution, facturation. Ces parties sont testées et figées ; les modifier casse la production.

Ne pas non plus : inventer un RCCM, un numéro fiscal ou une mention légale ; afficher des statistiques non mesurées ; promettre une fonctionnalité non branchée.

---

## 11. Ce qu'il faut demander avant de commencer

- les valeurs `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE_URL` (communication hors dépôt) ;
- un compte de test (email + mot de passe) pour la prévisualisation ;
- l'accès au dépôt et à Vercel ;
- les captures de référence du propriétaire (ChatGPT mobile/desktop) si un arbitrage visuel se pose.

Le reste est dans le dépôt : `README.md`, `IMPLEMENTATION_STATUS.md`, `DECISIONS_LOG.md`, `docs/`.
