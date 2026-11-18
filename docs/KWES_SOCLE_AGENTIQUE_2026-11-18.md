# Socle agentique KWES — état vérifié

**Date :** 18 novembre 2026
**Serveur :** `185.181.122.118` — `https://api.agent-kwes.com/api/v1`
**Référence :** `KWES_REFERENTIEL_FONCTIONNEL_COMPLET.md` v1.0
**Nature :** constat d'exécution, pas une feuille de route. Chaque ligne « vérifié »
renvoie à une mission réellement exécutée en production, identifiable par son UUID.

---

## 1. Architecture réellement en service

```
Navigateur / PWA  ──►  kwes.vercel.app (Vercel)
                          │  HTTPS
                          ▼
              api.agent-kwes.com  ──►  nginx (TLS Let's Encrypt)
                                          │
                        ┌─────────────────┼──────────────────┐
                        ▼                 ▼                  ▼
                  kwes-api          kwes-worker          searxng
                (FastAPI,          (missions,            (recherche
                 systemd)           outils, files         auto-hébergée
                        │            Redis)              127.0.0.1:8888)
                        └────────► PostgreSQL 16 ◄──────────┘
                                   (RLS active, 21 tables)
```

Aucun conteneur. Services `systemd` : `kwes-api`, `kwes-worker`, `searxng`,
`postgresql`, `redis-server`, `nginx`. Sauvegarde quotidienne à 02:15.
Le worker exécute le code des missions sous l'utilisateur `kwesexec`, jamais root
(`PrivateTmp`, `ProtectSystem=full`, `NoNewPrivileges`).

---

## 2. Contrôles exécutés — 8 sur 8 réussis

Script : `tools/preuves_socle.py` (aucune donnée simulée, appels réels à l'API
de production). Sortie machine : `docs/preuves/socle-20261118-213506.json`.

| # | Contrôle | Résultat observé | Mission |
|---|---|---|---|
| 1 | Mission à deux outils (calcul puis document) | `completed`, `RESULTAT=1081`, 2 étapes `completed` | `d032beeb-…` |
| 2 | Document produit et téléchargeable | `GET /documents/{id}/download` → 200, 64 octets conformes | — |
| 3 | Mémoire écrite par une mission | mission `completed`, marqueur retrouvé via `GET /memory` | `77241282-…` |
| 4 | Mémoire réinjectée dans une réponse | réponse : « Vous exigez des preuves horodatées avant toute conclusion de ma part. » | — |
| 5 | Continuité serveur, client déconnecté | mission terminée pendant 25 s sans aucun appel client, `stdout=CONTINUITE_OK` | `5a667667-…` |
| 6 | Contrôle humain avant action R2 | `awaiting_approval` → approbation → `completed`, `stdout=APPROUVE_ET_EXECUTE` | `304aef2b-…` |
| 7 | Pause puis reprise | état `paused` observé, reprise → `completed` | — |
| 8 | Traces consultables | 5 missions et 20 preuves lisibles via l'API | — |

Tests unitaires et d'intégration : **247 passés, 4 ignorés** (`pytest -q`).

---

## 3. Isolation inter-tenant — prouvée avec le rôle applicatif réel

Exécuté sur la base de production avec `kwes_app` (ni superuser ni `BYPASSRLS`),
et les claims de l'utilisateur A (`0542f1d4…`) :

| Contrôle | Résultat |
|---|---|
| Conversations visibles par A | **54** (les siennes) |
| Conversations de B (`3a33757e…`) visibles par A | **0** |
| Insertion d'une conversation dans l'espace de B par A | **refusée** (`new row violates row-level security policy`) |

Script : `tools/preuve_isolation.sql`.

> ⚠️ Le rôle propriétaire `kwes` porte `BYPASSRLS` (nécessaire aux fonctions
> `SECURITY DEFINER` de création d'espace). Il ne doit **jamais** servir à servir
> des requêtes utilisateur : l'API passe par `kwes_app`, le worker par `kwes` en
> assumant le contournement. Un test lancé avec `kwes` renvoie tout et ne prouve
> rien — c'est ce qui a été constaté puis corrigé pendant l'audit.

---

## 4. Défauts réels trouvés et corrigés pendant l'audit

1. **Toute mission approuvée échouait.** L'orchestrateur marque l'approbation
   `consumed`, mais la contrainte `approvals_status_check` n'autorisait que
   `pending/approved/rejected/expired` : `CheckViolation` au moment de consommer,
   étape bloquée en `running`, mission en `failed`. → migration
   `0015_approval_consumed.sql`, appliquée en production.
2. **Écritures refusées de façon intermittente.** Un `commit()` rend la connexion
   au pool ; la requête suivante pouvait en recevoir une autre, sans identité RLS
   (`auth.uid()` nul) → insertion d'audit refusée. → écouteur de pool qui repose
   rôle et claims à chaque emprunt de connexion (`app/db/rls.py`,
   `install_rls_listener`).
3. **Sessions vocales jamais enregistrées.** La politique d'insertion exige
   l'appartenance à l'espace ; la ligne partait sans `tenant_id`
   (`is_tenant_member(NULL)` = faux), l'erreur était avalée. → contexte RLS posé et
   `tenant_id` renseigné avant l'écriture.
4. **Création de mission en erreur 500.** `session.refresh()` sur une instance
   détachée après les commits de l'orchestrateur. → relecture par identifiant.
5. **Poignée de main Gemini Live transitoirement expirée** (10 s) : l'usager
   recevait « service vocal indisponible ». → nouvelle tentative et délai explicite.
6. **La RLS n'était pas active du tout avant le 18/11.** `KWES_RLS_ENABLED` était
   ignorée (le champ attendait `DB_RLS_ENABLED`) : l'API tournait avec le rôle
   administrateur. Corrigé et vérifié.

---

## 5. Matrice de capacités (référentiel §23)

### 5.1 Vérifié en production

- missions multi-étapes avec dépendances, exécution, vérification du résultat ;
- exécution de code (`code_exec`) sous utilisateur dédié, avec accès réseau ;
- production de documents et téléchargement ;
- mémoire durable, relue par l'API et réinjectée dans les réponses ;
- contrôle humain (approbation) sur les actions R2 ;
- pause / reprise / annulation de mission ;
- continuité serveur quand le client est fermé ;
- traces : missions, étapes, audit, preuves ;
- isolation multi-tenant par RLS ;
- conversation vocale temps réel (Gemini Live), barge-in ;
- recherche web (SearXNG auto-hébergé + repli Wikipédia/DuckDuckGo) ;
- PWA installable, mises à jour gérées.

### 5.2 Partiel ou en cours de fiabilisation

- **Choix du skill par le planificateur** : sur une demande « écris un fichier »,
  il a choisi `business_planning` au lieu de `code_exec`. Le moteur exécute
  correctement ce qu'on lui donne, mais le routage doit être amélioré.
- **Lecture de pages JavaScript** : installation Playwright en cours de validation.
- **Recherche** : fiabilisation des moteurs SearXNG en cours (sous-agent dédié).

### 5.3 Non intégré — annoncé comme indisponible

Email, WhatsApp, Telegram, SMS et appels, calendrier, contrôle Android, OCR et
indexation documentaire avancée, navigation authentifiée, notifications push,
**KWES Pay** (désactivé par défaut, aucune capacité financière active).

---

## 6. Limites connues, à ne pas masquer

- `code_exec` : **25 s maximum** par étape (contrainte de schéma) — une mission
  longue doit être découpée en plusieurs étapes.
- Le code s'exécute avec accès réseau : ce n'est pas un bac à sable réseau.
- Les preuves d'isolation sont établies au niveau base ; elles ne remplacent pas
  un test de bout en bout avec deux comptes réels connectés simultanément.
- Aucun test sur téléphone physique dans cette passe : la voix a été vérifiée en
  navigateur headless (micro simulé) et en WebSocket directe.
- Les langues ivoiriennes ne sont ni prises en charge ni validées.
- Les preuves d'indexation par les moteurs de recherche ne dépendent pas de ce
  document.

---

## 7. Comment rejouer les preuves

```bash
# Contrôles de bout en bout (production)
cd /home/babayaga/business/kwes
backend/.venv/bin/python tools/preuves_socle.py

# Isolation inter-tenant, avec le rôle applicatif réel
ssh root@185.181.122.118 \
  'PGPASSWORD="$KWES_DB_APP_PASSWORD" psql -h 127.0.0.1 -U kwes_app -d kwes -f /tmp/isolation.sql'

# Tests unitaires
cd backend && .venv/bin/python -m pytest -q
```

---

## 8. Prochaines actions (ordre de valeur)

1. **Routage du planificateur** : choisir le bon skill selon l'intention (P0 — un
   bon moteur avec un mauvais routage rate la mission).
2. **Fin de la fiabilisation recherche + rendu JS** (sous-agent en cours).
3. **Email** (lecture, brouillon, envoi après confirmation) — première capacité de
   communication réellement utile.
4. **Calendrier et rappels**.
5. **OCR** sur factures et reçus.
6. **Notifications push** pour les missions longues.
7. **Deuxième compte de test** pour une preuve d'isolation de bout en bout via l'API.
