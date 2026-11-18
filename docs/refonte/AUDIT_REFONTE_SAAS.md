# Kwes : audit de la refonte SaaS multi-tenant (phase 1)

**Branche** : `feature/refonte-saas-audit-seo` (créée depuis `alpha/jour-1`, commit de base `2c5032b`)
**Périmètre** : lecture du dépôt, sans accès à Supabase ni au VPS. Les constats base de données reprennent l'audit du 18 novembre (`docs/KWES_AUDIT_SOCLE_2026-11-18.md`) et ne sont pas revérifiés ici.

## 1. Ce qui existe

| Zone | État constaté |
|---|---|
| Frontend | React + Vite + TypeScript, CSS maison (`app.css`, `home.css`, `chat.css`, `login-brand.css`). Pas de Tailwind ni de bibliothèque UI. |
| Routes | Publique : `PublicHome`. Privées (après connexion) : accueil, parler (chat et vocal), échanges, tâches, détail de tâche, validations, réglages. Routage maison dans `lib/router.ts`. |
| Authentification | Supabase Auth côté navigateur (`lib/supabase.ts`, `lib/auth.ts`). Connexion, inscription, récupération de mot de passe présents. |
| Backend | FastAPI + SQLAlchemy + worker (`backend/app`), déployé sur VPS (systemd). |
| Données | Tables par utilisateur (`user_id`) : conversations, messages, tâches, étapes, mémoire, validations, documents, notifications, appareils, sessions vocales. |
| Isolation | Vérifiée au niveau API par `backend/tests/test_isolation.py` (conversations, mémoire, notifications). |
| PWA | Manifeste présent. Service worker `sw.js` en cache d'application (`kwes-shell-v3`). |
| SEO | `index.html` avec title, description, Open Graph, Twitter Card, JSON-LD (SoftwareApplication, Organization). `robots.txt` et `sitemap.xml` présents. |

## 2. Écarts avec la mission

### 2.1 Multi-tenant
- **Il n'existe pas de modèle tenant.** Aucune table `tenants`, `tenant_memberships` ni `tenant_id`. Le modèle est mono-utilisateur étendu : chaque ligne porte un `user_id`.
- Pas de rôles `owner` / `admin` / `member` / `viewer`.
- Pas d'invitations ni de paramètres par espace.
- **Bloquant pour la mission** : la phase 2 suppose une migration de schéma. Elle nécessite l'accès Supabase et une sauvegarde avant toute écriture.

### 2.2 Isolation base de données (risque critique)
- D'après l'audit du 18 novembre : le rôle PostgreSQL de l'application est superutilisateur avec `BYPASSRLS`. Les politiques RLS existent (16 tables, 42 politiques) mais **ne s'appliquent pas** à la connexion de Kwes. Aucune table n'a `FORCE ROW LEVEL SECURITY`.
- Conséquence : l'isolation repose uniquement sur le code applicatif. Un `WHERE user_id = …` oublié expose les données d'un autre compte.
- Correctif recommandé dans l'audit (non appliqué) : rôle `kwes_app` sans `BYPASSRLS`, `FORCE RLS`, politiques basées sur `current_setting('app.user_id')`, rôle séparé pour les migrations.
- Ce correctif touche la base de production : il attend ton accord et un test de restauration.

### 2.3 Interface
- Accueil centré sur le texte de l'orbe et une feuille, pas sur le droïde comme élément principal. Le HomeScreen est vocal et droïde-first (voir `HomeScreen.tsx`).
- Incohérence documentaire à trancher : la doc du design system et l'issue demandent une expérience écrite à l'accueil, le code fait parler Kwes.
- Les tokens de design documentés et ceux du code divergent (couleurs, polices). À réconcilier avant la refonte visuelle.

### 2.4 PWA
- `sw.js` appelle `skipWaiting()` à l'installation et `clients.claim()` à l'activation : une nouvelle version s'active sans que l'utilisateur soit prévenu.
- Pas de détection de nouvelle version côté interface, pas de bouton « Mettre à jour », pas de report.
- Les assets sont en cache d'abord sans empreinte de version : risque d'assets périmés après un déploiement.
- Les appels `/api/` et Supabase ne sont pas mis en cache : c'est correct.

### 2.5 SEO, AEO, GEO, LLMO
- `canonical`, `og:url`, `og:image`, `sitemap.xml` et JSON-LD pointent vers `frontend-phi-pied-lzumzbngjw.vercel.app`. Le domaine de production réel reste à confirmer.
- Pas de `llms.txt` ni de `llms-full.txt` avant ce commit.
- JSON-LD : pas de `Person`. Les informations professionnelles fournies pour la mission (section 7.5) n'étaient donc pas exposées en données structurées.
- `sitemap.xml` ne contient que la page d'accueil : c'est correct tant que les autres pages publiques n'existent pas.

### 2.6 Android et Play Store
- La PWA ne peut pas accéder aux notifications, contacts ni applications du téléphone. L'audit du 18 novembre situe ce besoin dans une application native.

## 3. Ce que fait ce commit

- Ce document d'audit.
- `frontend/public/llms.txt` et `frontend/public/llms-full.txt` : présentation publique, capacités réelles et limites, identité professionnelle limitée à ce que tu as fourni.
- `index.html` : ajout d'une entité `Person` dans le JSON-LD (rôle professionnel uniquement, aucun titre de fondateur ni de CTO).

Aucun changement de base, d'authentification, de route ou de dépendance.

## 4. Bloqué sans accès externe

| Élément | Pourquoi |
|---|---|
| Isolation RLS et rôle applicatif | Accès Supabase requis, plus sauvegarde et test de rollback. |
| Tables tenants et migrations | Même raison, plus une décision de modèle (utilisateur dans plusieurs espaces ou non). |
| Domaine canonique | Il faut confirmer le domaine de production. |
| Informations légales pour llms.txt | Aucune mention légale n'a été ajoutée. |
| Application Android | Projet séparé, hors dépôt web. |
| Mesure de latence et test sur téléphone | Nécessite un appareil physique. |

## 5. Prochaines phases proposées

1. **Design system et accueil** : réconcilier les tokens, rendre le droïde central, traiter la question écrit ou vocal.
2. **PWA** : détection de nouvelle version, bannière de mise à jour non intrusive, report, versionnement du cache.
3. **Parcours et états** : chargement, vide, erreur, session expirée, absence d'autorisation sur chaque écran.
4. **Isolation base** (après accès Supabase et sauvegarde) : rôle applicatif, `FORCE RLS`, tests négatifs entre deux comptes.
5. **Modèle tenant** : seulement après la décision sur les espaces multiples.
