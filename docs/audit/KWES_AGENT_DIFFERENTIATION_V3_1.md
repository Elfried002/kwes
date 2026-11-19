# KWES — Différenciation des procédures `AGENT.md` (V3.1)

**Date :** 19 novembre 2026
**Périmètre :** `agents/*/AGENT.md` — 16 fichiers réécrits, rien d’autre modifié dans le package.
**Fichiers préservés :** `SOUL.md`, `AGENT_SPEC.md`, `config.yaml`, `core/`, `registry/`, `shared/`.

## 1. Constat de départ, mesuré

Les 16 `AGENT.md` faisaient 42 lignes, dont 34 identiques mot pour mot. Entre deux agents,
8 lignes seulement différaient : le titre, la ligne « Spécificités métier », la liste de
collaboration et la ligne « Règles particulières ». La procédure, les contrôles, l’escalade
et la clôture étaient recopiés — d’où un agent « Audit » sans méthode d’échantillonnage et un
agent « Sécurité » sans vérification de périmètre.

## 2. Contrôles appliqués aux 16 fichiers réécrits

| Contrôle | Résultat |
|---|---|
| Structure exigée (8 sections, ordre imposé) | 16/16 conformes |
| Longueur | 60 à 61 lignes (cible 55–80) |
| Outils cités ⊂ `declared_tool_ids` de la config | 16/16 — aucun identifiant hors config |
| Outil `declared` annoté « déclaré, non disponible aujourd’hui » + contournement | 16/16 |
| Outil `implemented` annoté « implémenté et disponible aujourd’hui » | 16/16 |
| Règle de langue (dernière réplique de l’utilisateur) présente | 16/16 |
| Les 8 puces des règles communes conservées | 16/16 |
| Niveau d’approbation réaligné sur `approval_matrix` (A3 = approbation explicite) | 16/16 |
| Similarité 6-grammes hors règles communes, pire paire | **2,07 %** (cible < 45 %) |

Mesure reproductible :

```bash
cd docs/audit/KWES_AGENTIC_TEAM_CONFIG_V3_1
python3 /home/babayaga/business/kwes/tools/verif_agent_md.py
# → agents vérifiés : 16 | lignes min 60 max 61 | similarité max 2 % | problèmes : 0
```

Contrôles de validité du calcul (le harnais ne doit pas mentir) : sur le texte **intégral**,
règles communes incluses, la similarité maximale remonte à 17 % — c’est le tronc commun qui
produit ce score, ce qui confirme que la fonction détecte bien les passages partagés ; et
l’auto-comparaison d’un fichier avec lui-même renvoie 100 %. La mesure publiée ci-dessous
porte donc bien sur la partie propre à chaque métier.

## 3. Les 16 fichiers réécrits

| Agent | Fichier | Lignes | Sim. max | Voisin le plus proche | Outils disponibles |
|---|---|---|---|---|---|
| Audit | `agents/audit/AGENT.md` | 60 | 1,0 % | life | 0 / 3 |
| Automation | `agents/automation/AGENT.md` | 60 | 0,5 % | personal | 0 / 3 |
| Business | `agents/business/AGENT.md` | 60 | 0,8 % | operations | 1 / 4 |
| Documents | `agents/documents/AGENT.md` | 60 | 0,9 % | operations | 1 / 4 |
| Finance | `agents/finance/AGENT.md` | 60 | 2,1 % | relation | 0 / 3 |
| Learning | `agents/learning/AGENT.md` | 60 | 1,1 % | personal | 0 / 3 |
| Life | `agents/life/AGENT.md` | 60 | 1,3 % | sales | 2 / 3 |
| Marketing | `agents/marketing/AGENT.md` | 60 | 1,3 % | sales | 0 / 3 |
| Operations | `agents/operations/AGENT.md` | 60 | 1,2 % | relation | 0 / 3 |
| Personal | `agents/personal/AGENT.md` | 60 | 1,1 % | learning | 1 / 4 |
| Relation | `agents/relation/AGENT.md` | 60 | 2,1 % | finance | 0 / 3 |
| Research | `agents/research/AGENT.md` | 60 | 1,1 % | sales | 4 / 4 |
| Sales | `agents/sales/AGENT.md` | 60 | 1,3 % | marketing | 1 / 3 |
| Security | `agents/security/AGENT.md` | 60 | 1,7 % | vision | 0 / 4 |
| Tech | `agents/tech/AGENT.md` | 61 | 1,0 % | research | 3 / 4 |
| Vision | `agents/vision/AGENT.md` | 60 | 1,7 % | security | 3 / 4 |

« Outils disponibles » = `implemented` / total déclaré, d’après `capabilities.tool_status`.

## 4. Méthode propre retenue, trois gestes décisifs par agent

| Agent | Geste | Contenu de la procédure |
|---|---|---|
| Audit | 1 | Plan d’échantillonnage écrit **avant** lecture du livrable : population, taille, mode de tirage, critère de sélection, couverture n/N annoncée. |
| Audit | 2 | Contre-vérification sur source primaire et recalcul indépendant : valeur annoncée, valeur retrouvée, écart. Non traçable = « non vérifiable », jamais « conforme ». |
| Audit | 3 | Constat normalisé (identifiant, extrait littéral, localisation, critère violé, niveau) et preuves reproductibles par un tiers. |
| Automation | 1 | Fiche du workflow avant configuration : déclencheur, condition d’entrée, données lues/écrites, cible, fréquence, propriétaire. |
| Automation | 2 | Chemins d’échec nommés et idempotence prouvée : clé de déduplication, comportement au rejeu, pas de double envoi. |
| Automation | 3 | Test sur données factices, secrets par référence de coffre, activation A3 avec diff exact et retour arrière. |
| Business | 1 | État de l’activité daté et sourcé (vendu, produit, stocké, dû) avant toute recommandation. |
| Business | 2 | Trois contrôles de cohérence : somme des lignes, stock initial + entrées − sorties, encours = facturé − encaissé. |
| Business | 3 | Écarts isolés puis plan en tâches datées avec indicateur ; le chiffrage financier est renvoyé à KWES FINANCE, pas deviné. |
| Documents | 1 | Contrôle d’intégrité du fichier source : format réel vs extension, couche texte, pages/feuilles, mode de lecture annoncé. |
| Documents | 2 | Extraction localisée (page, feuille, cellule) puis contrôle de structure : comptage, totaux, doublons, lignes de total confondues. |
| Documents | 3 | Relecture du fichier généré, original intact, format réellement produit annoncé sans équivalence approximative. |
| Finance | 1 | Chaque montant rattaché à sa pièce, avec date, devise et période ; aucun solde de mémoire. |
| Finance | 2 | Rapprochement obligatoire **avant** tout chiffre : mouvements vs solde, facturé vs encaissé, budget vs consommé ; écart chiffré, jamais « négligeable ». |
| Finance | 3 | Scénarios bas/central/haut à hypothèses nommées ; toute opération de paiement reste une préparation A3/A4, jamais une exécution. |
| Learning | 1 | Diagnostic du niveau réel par exercice, pas par déclaration de l’apprenant. |
| Learning | 2 | Objectif en verbe observable, séquences de 20–40 min, chaque notion en définition → exemple → contre-exemple → erreur classique. |
| Learning | 3 | Correction de l’étape fautive (jamais la réponse à la place de l’apprenant) et rappel espacé J+1 / J+7 / J+30. |
| Life | 1 | Cadrage en cinq paramètres : zone, moment, budget, mobilité, urgence. |
| Life | 2 | Information critique confirmée à la source la plus directe, horodatée ; une fiche d’annuaire n’est pas une confirmation. |
| Life | 3 | Comparaison sur critères annoncés avec plan B et reste-à-confirmer ; urgence vitale → services compétents, recherche arrêtée. |
| Marketing | 1 | Cible et problème en une phrase vérifiable ; sans cible, la mission retourne à Core au lieu d’un contenu générique. |
| Marketing | 2 | Positionnement adossé à des preuves : toute promesse non démontrable est retirée avant rédaction. |
| Marketing | 3 | Mesure définie avant publication (indicateur, date, seuil) ; aucun budget engagé, aucun chiffre d’audience inventé. |
| Operations | 1 | État physique réel d’abord : stock compté et sa date, commandes ouvertes, livraisons attendues, retours. |
| Operations | 2 | Besoin article par article = demande + sécurité − disponible − attendu, chaque terme écrit et daté. |
| Operations | 3 | Ordonnancement sur délais constatés, puis preuve de bouclage : bon signé, écart de réception chiffré, stock cohérent. |
| Personal | 1 | Préférences et contraintes (plages de tranquillité, canal, fuseau) lues avant toute proposition. |
| Personal | 2 | État des engagements et conflits réels : chevauchements, temps de trajet, enchaînements irréalistes ; priorité à la promesse déjà faite. |
| Personal | 3 | Rappels datés (heure, fuseau, canal) et réversibilité : rien n’est déplacé ni annulé sans accord explicite. |
| Relation | 1 | Contexte reconstitué avant rédaction : qui, historique, demande exacte, engagements déjà pris. |
| Relation | 2 | Faits vérifiés sur pièce avant réponse ; réponse à la question posée dès la première phrase. |
| Relation | 3 | Brouillon A3 arrêté avant envoi : destinataire exact, base légitime, promesses datées uniquement. |
| Research | 1 | Découpage en 2 à 4 sous-questions rattachées à une décision, avec critères de source posés avant la recherche. |
| Research | 2 | Source primaire privilégiée, deux sources indépendantes par fait décisif, désaccords écrits au lieu d’être moyennés. |
| Research | 3 | Synthèse avec source et niveau de confiance par affirmation, recherches négatives rapportées, accès restreints signalés. |
| Sales | 1 | Qualification avant tout prix : besoin, décideur, budget, échéance, critère de choix. |
| Sales | 2 | Base légitime du contact vérifiée (consentement, relation, règle de plateforme) avant toute sollicitation. |
| Sales | 3 | Proposition en cinq blocs, prix issu d’une grille validée, aucune promesse de vente ni de délai de signature. |
| Security | 1 | Périmètre autorisé **avant** toute action : actifs, comptes, fenêtre, auteur et forme écrite de l’autorisation. |
| Security | 2 | Lecture seule des journaux et configurations, corrélation sur fenêtre datée : un signal isolé n’est pas une compromission. |
| Security | 3 | Qualification impact × probabilité avec preuve horodatée et mesure défensive recommandée ; l’exécution reste à l’exploitant. |
| Tech | 1 | Lecture du code et des tests existants, reproduction du comportement constaté avant toute écriture. |
| Tech | 2 | Test rouge d’abord, correctif minimal ensuite, aucune refactorisation hors périmètre. |
| Tech | 3 | Exécution en bac à sable avec commande et sortie jointes ; déploiement préparé (diff, retour arrière) jamais déclenché. |
| Vision | 1 | Droits d’usage et données visibles sensibles vérifiés avant analyse approfondie ou réutilisation. |
| Vision | 2 | Décrire avant d’interpréter ; lecture de texte faillible, caractères incertains marqués, aucun chiffre complété. |
| Vision | 3 | Recoupement des éléments chiffrés sur une seconde zone ; brief de création au lieu d’une génération d’image. |

## 5. Traitement des outils, sans promesse excessive

Chaque identifiant de `declared_tool_ids` est cité avec son niveau d’approbation réel, puis
annoté :

- statut `declared` → « déclaré, non disponible aujourd’hui », avec le contournement autorisé
  (recherche web, lecture d’une page, production d’un document, exécution isolée d’un calcul) ;
- statut `implemented` → « implémenté et disponible aujourd’hui », décrit par son effet et non
  par un identifiant de skill absent de la config ;
- les identifiants d’outils qui ne figurent pas dans `config.yaml` ne sont **pas** nommés,
  pour ne pas créer de capacité parallèle.

Conséquence assumée : 13 agents sur 16 n’ont aujourd’hui aucun outil exécutable. Leur
procédure est donc une doctrine applicable à la main, ce qui est écrit tel quel dans chaque
fichier. Les seuls périmètres réellement outillés sont Research (4/4), Tech (3/4) et, plus
partiellement, Life, Business, Documents, Personal, Sales (1 à 2 outils).

## 6. Limites honnêtes

- **Matière métier absente du package.** Aucun barème, seuil, grille tarifaire, nomenclature
  ni politique d’entreprise n’existe dans `SOUL.md` ou `config.yaml`. La procédure dit donc
  « grille validée », « seuil annoncé », « délai constaté » sans inventer de valeur. C’est le
  manque principal : ces valeurs doivent venir du propriétaire, pas de l’agent.
- **Frontières de métier proches.** Business / Operations d’une part, Sales / Relation de
  l’autre, se recouvrent partiellement. La séparation retenue est méthodologique (pilotage vs
  exécution logistique ; proposition chiffrée vs échange courant), pas une décision du package.
- **Aucune procédure n’a été exécutée.** L’audit est statique : les méthodes sont écrites et
  mesurées, pas éprouvées sur une mission réelle.
- **Concurrence d’écriture constatée.** `SOUL.md` (section `## Langue`) et `config.yaml`
  (bloc `execution.isolation`) ont été modifiés à 13:05 par un autre processus, avant la
  première de mes écritures (13:06). Je n’ai touché que les 16 `AGENT.md` ; les fichiers
  réécrits restent cohérents avec la config telle qu’elle est à présent.
