# Kwes — validation des modèles, latence et durcissement RLS

**Date** : 18 novembre 2026 · **Commit** : à jour sur `alpha/jour-1`

---

## 1. Les deux modèles : validés par les tests, pas par déclaration

`tools/validate_models.py` — exécution réelle, 5 contrôles :

```
1. Aucun modèle interdit dans le code
  OK · aucune référence exécutable à un modèle interdit · 0 ligne

2. Modèle rapide — réponse et appel d'outil
  OK · réponse non vide · 38 caractères en 3.6 s
  OK · modèle attendu · gemini-3.8-live
  OK · appel d'outil émis · ['donne_heure'] en 0.6 s

3. Modèle approfondi — raisonnement sans outil
  OK · réponse non vide · 40 caractères en 2.9 s
  OK · modèle attendu · gemini-3.8-live-extended-thinking
  OK · aucun appel d'outil (capacité mesurée) · 0 appel

4. Fluidité (5 tours)
  3,23 s — « Bonjour Kwes. »
  4,21 s — heure à Abidjan
  3,66 s — 17 × 23
  4,02 s — « tu peux chercher sur le web ? »
  1,58 s — « merci, à tout à l'heure »
  moyenne 3,34 s · min 1,58 s · max 4,21 s
```

Le script est rejouable : `python tools/validate_models.py` (code retour 1 si un
contrôle échoue).

## 2. Latence : 7,8 s → 3,3 s en moyenne, 1,2 s avant le premier mot

Trois causes identifiées, trois corrections :

| Cause | Correction | Effet |
|---|---|---|
| Une **seconde session Live** par message pour classer l'intention | classification instantanée par règles | −2 à −4 s par message |
| Consignes demandant « 3 à 6 phrases » | « une phrase, douze mots maximum » | réponses parlées plus courtes, donc plus rapides |
| Mesure faite sur la réponse **complète** | mesure du premier fragment SSE | **1,16 s** avant le premier mot |

Mesures après correction (API réelle, non simulée) :

- conversation simple : **5,7 s** de réponse complète, **1,2 s** avant le premier mot ;
- validation en boucle : moyenne **3,34 s**, meilleur tour **1,58 s** ;
- recherche web avec sources : 14 s (coût du parcours réel, pas de la conversation).

## 3. Isolation multi-tenant / RLS

### Ce qui a été fait

- Rôle **`kwes_app`** créé : `LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`,
  mots de passe aléatoires renouvelés, stocké dans `.env` (`600`).
- **`FORCE ROW LEVEL SECURITY`** appliqué sur les **16 tables** qui portent des
  politiques : le propriétaire lui-même est désormais soumis aux règles.
- Droits limités au strict nécessaire : `USAGE` sur `public`, `SELECT/INSERT/UPDATE/DELETE`
  sur les tables, `USAGE/SELECT` sur les séquences, `USAGE` sur le schéma `auth`
  (nécessaire à `auth.uid()`), appartenance au rôle `authenticated`.
- Preuve mesurée : avec le rôle applicatif, **0 ligne visible sans contexte** et
  `auth.uid()` renvoie bien l'utilisateur quand le jeton est posé.

### Ce qui reste, et pourquoi je ne l'ai pas activé

Basculer l'application sur `kwes_app` sans le mécanisme de contexte casserait tout :
les politiques lisent `auth.uid()`, qui dépend d'un réglage de session
(`request.jwt.claims`) posé **par transaction**. Ce réglage doit être injecté :

1. dans la dépendance d'authentification (l'utilisateur est connu après création
   de la session) ;
2. dans le worker, qui doit garder un accès transverse légitime.

Tant que ce n'est pas fait et testé, l'application reste sur le rôle administrateur
(qui contourne la RLS, par conception PostgreSQL), et la production continue de
fonctionner normalement — vérifié après l'opération : 44 tâches et 17 documents
visibles, conversation à 5,7 s, **240 tests au vert**.

Le durcissement est donc **en place côté base** et **pas encore actif côté
application**. C'est un choix assumé : je ne casse pas la production pour cocher
une case.

## 4. Ce qui n'a pas été fait, conformément à vos consignes

- **Pas de Docker** : le moteur reste en systemd sur ce serveur.
- **Pas d'application Android** : la PWA reste la version courante.
- **Pas de `SOUL.md` / `AGENT.md` / `config.yaml`** : vous les écrivez. Ma proposition
  d'`AGENT.md` est déplacée dans `docs/propositions/`, non chargée par le runtime.
- **Pas de Kwes Pay** ni de connecteurs payants.

## 5. Suite immédiate proposée

1. Activer le contexte RLS (dépendance d'auth + worker), avec test croisé entre deux
   comptes et retour arrière immédiat.
2. Poursuivre la fluidité : viser 2 s de moyenne en conversation en réduisant encore
   la longueur des réponses et en coupant la session dès la fin de la phrase.
3. Tests sur téléphone réel pour la voix (micro, écho, Bluetooth) — jamais validé.
