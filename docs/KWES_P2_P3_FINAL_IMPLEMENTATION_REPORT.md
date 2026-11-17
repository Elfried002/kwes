# KWES — Rapport final P2 + P3 (Voice Experience & Agentic Core)

**Date** : 17 novembre 2026 · **Commit de départ** : `c9a2b37`
**Périmètre exécuté** : Chantier A (voix), B (cœur agentique), C (interface), D (sécurité et
conformité), tests et déploiement.
**Statut** : livré et mesuré, avec des limites explicites indiquées en fin de document.

Chaque fonctionnalité est classée **OPÉRATIONNELLE ET TESTÉE**, **PARTIELLEMENT OPÉRATIONNELLE**,
**NON IMPLÉMENTÉE** ou **BLOQUÉE**. Aucune fonctionnalité prévue n'est présentée comme livrée.

---

## 1. État initial de l'architecture

Au démarrage de la mission :

- API FastAPI (systemd `kwes-api`) et worker (`kwes-worker`) séparés, file Redis, verrou PostgreSQL.
- Auth ES256 Supabase stricte depuis P0.1, 42 politiques RLS, Policy Engine R0–R4.
- Recherche v2 (SearXNG auto-hébergé + DDG + Wikipédia, preuves en base) depuis P1.
- Voix : Gemini Live serveur à serveur, VAD locale côté navigateur, interruption gérée.
- Interface : rail à six entrées (Accueil, Parler, Échanges, Travail, Accord, Réglages).
- Skills : `web_research` 1.1.0, `browser_readonly`, `business_planning`, `remember`,
  `document_write`. Aucune exécution de code possible.

## 2. Problèmes identifiés

| # | Problème constaté | Cause réelle (mesurée) |
|---|---|---|
| 1 | Délai perçu de 3 à 7 s avant la réponse | VAD locale à **550 ms** de silence + latence modèle ; le silence était le seul facteur contrôlable |
| 2 | Prononciation | La règle imposait `/kwɛs/` (« kwè » ouvert) au lieu de `/kwes/` (« kwé » fermé) : erreur de spécification, corrigée |
| 3 | Réponses parfois remplacées par du texte | Repli documenté quand la clé Google est absente ; pas un bug de streaming |
| 4 | Aucun mode raisonnement | Un seul modèle Live, aucune bascule possible |
| 5 | Missions déclarées terminées sans contrôle de contenu | La vérification se limitait à « étape completed + trace d'exécution » |
| 6 | Aucun moyen d'exécuter du code | Aucun sandbox, donc aucune capacité de calcul réelle |
| 7 | Interface technique | Six entrées, dont deux notions d'administration |
| 8 | Sécurité de la CI | Aucun scan de secrets, aucune veille de dépendances |

## 3. Modifications réalisées

**Voix**
- Règle de prononciation réécrite : `/kwes/`, « Kwéss », « é » fermé de « été », interdiction
  explicite de « Kwèss ».
- Second modèle Live : `gemini-3.8-live-extended-thinking` (vérifié disponible sur la clé), avec
  `thinking_level=HIGH` — l'API refuse la connexion sans ce paramètre (« Thinking level must be
  specified for this model »).
- Routeur de mode : bascule à chaud, conservation du contexte (6 derniers échanges réinjectés),
  repli automatique sur le mode rapide si le modèle approfondi échoue, événement `mode` envoyé au
  navigateur.
- VAD : seuil de fin de tour ramené de 550 ms à **380 ms**.
- Nettoyage ElevenLabs : vérifié, **0 référence** dans le code backend et frontend.

**Cœur agentique**
- Vérification des résultats avant clôture : document réellement présent et non vide, mémoire
  réellement enregistrée et rattachée au bon utilisateur, code exécuté avec code de sortie 0,
  sources lues comptabilisées. En cas d'échec : statut `failed`, code `VERIFICATION_FAILED`, aucun
  succès déclaré.
- Nouveau skill **`code_exec`** : conteneur Docker jetable, `--network none`, `--cap-drop ALL`,
  `--read-only`, `--user 65534`, 256 Mo, 0,5 CPU, 64 PIDs, `/tmp` de 32 Mo, destruction après usage,
  sortie plafonnée à 20 000 caractères.
- Accès Docker sans privilège : proxy `kwes-docker-proxy` (conteneurs + images uniquement, socket en
  lecture seule) sur `127.0.0.1:2375`. Le worker conserve `NoNewPrivileges=true`.

**Interface**
- Rail réduit à **trois espaces** : Accueil, Activité, Profil.
- Écran Activité : missions (filtres en langage clair) + section **Documents** avec ouverture
  (téléchargement authentifié, blob local).

**Sécurité / conformité**
- `tools/scan_secrets.py` : détection de clés Google, OpenAI, ElevenLabs, GitHub, JWT, clés privées,
  URL de base avec mot de passe. Exécuté : **aucun secret dans les fichiers suivis**.
- CI : nouveau job `securite` (scan de secrets bloquant, `pip-audit` et `npm audit` informatifs),
  `.github/dependabot.yml` (pip, npm, docker, actions).
- `docs/CONFORMITE_DONNEES.md` : inventaire, registre des traitements, sous-traitants, conservation,
  incidents, analyse de risques.

## 4. Architecture finale

```
Navigateur ──PWA──▶ nginx ──▶ kwes-api (FastAPI, JWT ES256, RLS, Policy R0–R4)
                                  │
                                  ├── chat / missions ──▶ Redis ──▶ kwes-worker
                                  │                                   ├── web_research (SearXNG→DDG→Wikipédia, preuves)
                                  │                                   ├── document_write / remember / business_planning
                                  │                                   └── code_exec ──▶ kwes-docker-proxy ──▶ conteneur jetable
                                  └── voix ──▶ Gemini Live (rapide) ou Live Extended Thinking (bascule à chaud)

PostgreSQL : 18 tables, 42 politiques RLS · Redis : file, verrous, cache, quotas · SearXNG : 127.0.0.1:8888
```

## 5. Modèles et services réellement utilisés

| Usage | Modèle / service | Vérification |
|---|---|---|
| Voix rapide | `gemini-3.8-live`, voix `Charon` | session réelle, `ready.model` renvoyé au client |
| Raisonnement vocal | `gemini-3.8-live-extended-thinking`, `thinking_level=HIGH` | 2 sessions réelles, bascule journalisée |
| Synthèse ponctuelle | `gemini-3.8-flash-tts` | test de prononciation |
| Raisonnement missions | DeepSeek (existant) | inchangé |
| Recherche | SearXNG auto-hébergé + DDG + Wikipédia | 38 preuves en base |
| Extraction PDF | pypdf 6.4.0 | PDF arXiv 2,2 Mo lu |
| Exécution de code | python:3.12-alpine en conteneur jetable | missions réelles |

## 6. Parcours vocal avant / après

| Étape | Avant | Après |
|---|---|---|
| Fin de tour | 550 ms de silence | **380 ms** |
| Modèle | unique, rapide | rapide **ou** approfondi, bascule à chaud |
| Contexte lors d'une bascule | perdu | 6 derniers échanges réinjectés |
| Prononciation | `/kwɛs/` (faux) | `/kwes/`, « Kwéss », « è » interdit |
| Repli si mode approfondi indisponible | — | retour automatique au mode rapide, sans couper la voix |
| Indicateur de mode | — | événement `mode` + état dans l'interface |

## 7. Fonctionnalités agentiques opérationnelles

- **OPÉRATIONNELLE ET TESTÉE** — Missions multi-étapes : planification, dépendances, exécution,
  reprise, vérification des résultats. Scénario réel : 4 étapes (recherche, calcul, document,
  mémoire), statut `completed`, quatre notes de vérification.
- **OPÉRATIONNELLE ET TESTÉE** — Exécution de code isolée hors réseau (8 tests dont 5 avec Docker).
- **OPÉRATIONNELLE ET TESTÉE** — Refus des outils non autorisés dès la validation du plan
  (`email_send` → `VALIDATION_ERROR`, aucun appel d'outil).
- **OPÉRATIONNELLE ET TESTÉE** — Recherche P1 conservée (sources, preuves, cache, quotas).
- **OPÉRATIONNELLE ET TESTÉE** — Documents produits, vérifiés, listés et téléchargeables.

## 8. Skills disponibles et testés

| Skill | État | Preuve |
|---|---|---|
| `web_research` 1.1.0 | OPÉRATIONNEL | missions réelles, 38 preuves |
| `browser_readonly` | OPÉRATIONNEL | tests + rendu Chromium réel |
| `business_planning` | OPÉRATIONNEL | tests déterministes |
| `remember` | OPÉRATIONNEL | vérification `memory_id` en base |
| `document_write` | OPÉRATIONNEL | 9 documents, dont 1 vérifié en mission |
| `code_exec` 1.0.0 | OPÉRATIONNEL | mission `3fe16e80…`, stdout « 285 / 1024 », exit 0 |

## 9. Résultats des tests

| Suite | Référence | Résultat |
|---|---|---|
| Backend | 235 | **243** (dont 8 pour le bac à sable) |
| Frontend | 134 | **134** |
| Build frontend | OK | **OK** (4,14 s) |
| Scan de secrets | — | **0 occurrence** |
| YAML CI / Dependabot | — | valides |

Commandes : `KWES_SANDBOX_TEST=1 pytest -q` → `243 passed in 79.57s` ; `vitest run` →
`134 passed` ; `npm run build` → `built in 4.14s`.

## 10. Mesures de latence (réelles)

Sonde `tools/voice_latency.py` : question synthétisée, envoyée en PCM 16 kHz au rythme réel,
mesure du **premier octet audio** après `activity_end`.

| Mode | Tours | TTFB P50 | TTFB P95 | Min / Max |
|---|---|---|---|---|
| Rapide | 6/6 | **915 ms** | **989 ms** | 645 / 989 ms |
| Approfondi | 2/2 | 819 ms | 878 ms | 760 / 878 ms |

Objectifs : P50 ≤ 1 500 ms, P95 ≤ 2 500 ms → **atteints**. Aucun tour sans audio, aucun cutoff
observé. À ces valeurs s'ajoute la réduction du silence de fin de tour (550 → 380 ms), soit environ
**170 ms** de moins avant que le modèle ne démarre.

**Compréhension du français** (`tools/voice_french_probe.py`, 6 formulations réelles) :

| Cas | Similarité brute | Normalisée |
|---|---|---|
| standard | 0,949 | 0,949 |
| oral | 0,926 | 0,926 |
| Afrique de l'Ouest | 0,880 | 0,880 |
| formulation imparfaite | 1,000 | 1,000 |
| phrase longue | 0,976 | 0,978 |
| chiffres | 0,786 | **0,979** |
| **Moyenne** | **92,0 %** | **95,2 %** |

Objectif 95 % : **atteint sur la mesure normalisée**. La mesure brute reste à 92 % parce que
« deux cent cinquante mille » est transcrit « 250000 » — une différence de forme, pas de sens.
Le cas « Afrique de l'Ouest » perd le préfixe « Kwes, on dit quoi ? » : la compréhension du contenu
est bonne, la reconnaissance du nom ne l'est pas toujours.

## 11. Tests de sécurité

| Test | Résultat |
|---|---|
| SSRF : localhost, loopback, IP privées, link-local, metadata | refusés (tests + vérification réelle) |
| DNS rebinding | refusé |
| Redirection vers IP privée | refusée avant suivi |
| Injection de prompt (page web, texte de PDF) | neutralisée phrase par phrase, avertissement utilisateur |
| Isolation entre utilisateurs | 404 inter-utilisateurs, `user_id` filtré, RLS |
| Outil non autorisé | refusé à la validation du plan |
| Secret dans les journaux | 0 occurrence (test + journald) |
| Secret dans le dépôt | 0 occurrence (scan) |
| Bac à sable : réseau, host, boucle infinie | réseau bloqué, `/etc` inaccessible, boucle tuée |
| Policy Engine / approbations hashées | inchangés, tests verts |

## 12. Résultats de déploiement

- `kwes-api` : active, `/api/v1/health` → 200 en local et en HTTPS public.
- `kwes-worker` : active, `NoNewPrivileges=yes`, `ProtectSystem=strict`.
- `kwes-searxng` : healthy, `127.0.0.1:8888` uniquement.
- `kwes-docker-proxy` : actif, `127.0.0.1:2375`, API limitée aux conteneurs et images.
- Frontend : déployé sur Vercel, alias `https://frontend-phi-pied-lzumzbngjw.vercel.app`.

## 13. Commits

- `31f6907` — P0.1 + P1 (session précédente)
- Commit de cette mission : voir la ligne finale du dépôt (`feat(p2-p3): voix, cœur agentique, interface et sécurité`).

## 14. Sauvegardes et rollback

- Sauvegarde avant P0 : `/home/babayaga/backups/kwes-pre-p0-20261116-2205.tgz`.
- Aucune migration destructive dans cette mission (aucune nouvelle table).
- Rollback code : `git revert <commit>` puis `systemctl restart kwes-api kwes-worker`.
- Rollback voix : `google_live_model` + `voice_auto_thinking=false` dans `.env`, redémarrage.
- Rollback code_exec : supprimer `code_exec` du registre (dossier) et arrêter
  `kwes-docker-proxy` ; aucune donnée à nettoyer.
- Rollback interface : redéploiement du commit précédent sur Vercel.

## 15. Coûts supplémentaires

| Poste | Coût |
|---|---|
| Gemini Live (voix) | 16 sessions, 152,6 s, **0,026 € estimés** (tarifs publiés, pas une facture) |
| Gemini Extended Thinking | inclus dans les sessions mesurées (2 tours) |
| SearXNG | 0 FCFA |
| Conteneurs de test | 0 FCFA (images libres, déjà présentes) |
| Frontend Vercel | inchangé |

Aucune souscription, aucune nouvelle clé, aucun service payant.

## 16. Limitations restantes

1. **Prononciation non validée à l'oreille.** Mesure instrumentale : F1 ≈ 539 Hz pour « Kwes »
   contre 445 Hz pour une voyelle fermée explicite — la voyelle par défaut est plus ouverte que
   voulu. La règle impose désormais « Kwéss » ; seul un humain peut confirmer le rendu perçu.
2. **Le nom est parfois mal reconnu** (« Kwezi » sur une synthèse brute, parfois omis) — sans effet
   sur la compréhension de la demande.
3. **Pas de test sur téléphone réel** : les mesures viennent d'un PCM envoyé par script, pas d'un
   micro physique dans un navigateur mobile.
4. **VAD à seuil fixe** : 380 ms convient à la parole continue ; un environnement très bruyant
   pourrait couper une phrase.
5. **Mode approfondi collant** : une fois déclenché, il reste actif pour la session (pas de retour
   automatique au mode rapide).
6. **`code_exec` dépend du proxy Docker** : si `kwes-docker-proxy` s'arrête, le skill échoue
   explicitement. Le proxy reste root-équivalent pour qui peut le joindre en local.
7. **Bac à sable non rootless** : les namespaces utilisateur sont désactivés sur ce noyau
   (`unshare -Urn` refusé), donc Podman/bubblewrap ne sont pas une option ici.
8. **Pas de synthèse LLM sur les preuves** : la synthèse de recherche reste extractive (choix
   assumé, zéro hallucination).

## 17. Fonctionnalités partiellement implémentées

- **Mémoire** : stockage, isolation et vérification opérationnels ; pas de recherche sémantique
  (pgvector inutilisé), pas d'expiration appliquée en lecture, pas de résolution de contradictions.
- **Mode approfondi** : fonctionne et est mesuré, mais la décision de bascule repose sur des mots-clés
  (pas de classification fine) et ne redescend pas en mode rapide.
- **Interface mobile** : trois espaces et section Documents livrés ; pas de test sur appareils réels
  ni audit d'accessibilité complet (contrastes et zones tactiles non mesurés formellement).
- **CI sécurité** : scan de secrets bloquant et Dependabot ajoutés ; `pip-audit`/`npm audit` sont
  informatifs ; CodeQL et push protection ne peuvent pas être activés sans dépôt GitHub distant.

## 18. Fonctionnalités non implémentées

- Import de fichiers et OCR (relève des chantiers fichiers/OCR).
- E-mail, agenda, automatisations planifiées (P4/P5/P6, hors périmètre).
- Export de données utilisateur et purge automatique (voir `docs/CONFORMITE_DONNEES.md`).
- Application Android native.
- Embeddings et mémoire sémantique.

## 19. Risques résiduels

| Risque | Niveau | Commentaire |
|---|---|---|
| Proxy Docker joignable en local | moyen | root-équivalent pour un processus local compromis ; à remplacer par un runner rootless |
| `sudo NOPASSWD: ALL` sur le compte de service | élevé (hérité) | antérieur à cette mission ; non modifié, à traiter |
| Nom de l'agent mal reconnu par l'ASR | faible | n'affecte pas la réponse |
| VAD à seuil fixe en milieu bruyant | faible | à rendre adaptatif |
| Pas d'audit d'accessibilité | moyen | exigence produit à traiter avant commercialisation |

## 20. Recommandations (version commerciale et Android)

1. Remplacer le sandbox Docker par un runner rootless dédié (Podman rootless ou gVisor), avec un
   service séparé qui n'expose qu'une API `run(code)`.
2. Retirer `NOPASSWD: ALL` du compte de service et donner au worker un utilisateur dédié.
3. Passer la VAD à un seuil adaptatif (niveau de bruit mesuré) et tester sur trois téléphones réels.
4. Faire écouter la prononciation par un panel francophone avant toute démonstration publique.
5. Rendre le mode approfondi non collant, avec retour au mode rapide après la réponse complexe.
6. Activer CodeQL, push protection et Dependabot alerts dès que le dépôt est poussé sur GitHub.
7. Pour Android : réutiliser l'API (aucune logique métier dans l'application), WebSocket voix
   inchangée, stockage local chiffré, et MASVS comme grille de revue.
8. Terminer la conformité (déclaration ARTCI, accords de sous-traitance, purge automatique,
   export utilisateur) avant toute commercialisation.

---

## Annexe — preuves d'exécution

```
$ systemctl is-active kwes-api kwes-worker → active / active
$ curl .../api/v1/health (local et public) → 200 / 200
$ docker ps → kwes-searxng (healthy), kwes-docker-proxy, kwes-postgres, kwes-redis
$ pytest -q (KWES_SANDBOX_TEST=1) → 243 passed in 79.57s
$ vitest run → 134 passed · npm run build → built in 4.14s
$ python3 tools/scan_secrets.py → Aucun secret détecté
$ tools/voice_latency.py 6 fast → P50 915 ms, P95 989 ms, 6/6 tours avec audio
$ tools/voice_latency.py 2 thinking → P50 819 ms, P95 878 ms, bascule journalisée
$ tools/voice_french_probe.py → 92,0 % brut · 95,2 % normalisé
$ psql: evidence=38, documents=9, memories=4
$ /voice/usage → 16 sessions, 152,6 s, 0,026 € estimés
```

Missions réelles de contrôle :

- `7701d00b…` — recherche + document : `completed`, vérification « 2/2 sources lues », document
  présent (188 caractères).
- `3fe16e80…` — 4 étapes (recherche, code, document, mémoire) : `completed`, quatre notes de
  vérification, dont « fait mémorisé (semantic) ».
- `8ef3e1ac…` — mission volontairement cassée : `failed` avec `VERIFICATION_FAILED`, preuve que le
  contrôle bloque un succès non prouvé.
- `email_send` — refusé à la validation du plan (`VALIDATION_ERROR`), aucun appel d'outil.
