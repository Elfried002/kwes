# Spécification des skills — Kwes

## 1. Définition

Un skill est une capacité versionnée que le moteur peut sélectionner pour effectuer une tâche délimitée.

Un skill n'est pas un prompt libre ayant accès à tout le système. Il possède un manifeste, des entrées/sorties, des permissions et des tests.

## 2. Structure

```text
skills/
  web_research/
    manifest.yaml
    instructions.md
    schemas/
      input.json
      output.json
    tests/
      test_basic.py
      fixtures/
```

## 3. Manifeste

```yaml
name: web_research
version: 1.0.0
description: Recherche et synthèse de sources web accessibles
entrypoint: skill.py
permissions:
  - web.search
  - web.read
risk_level: R0
network:
  mode: allowlist
  domains: []
resources:
  timeout_seconds: 180
  memory_mb: 512
  cpu_limit: 1
approval:
  required_for:
    - external_publish
```

Les domaines autorisés sont configurés par environnement, pas générés arbitrairement par le modèle.

## 4. Cycle d'exécution

1. Le planner sélectionne un skill.
2. Le registry vérifie que la version est active.
3. Le schéma valide l'entrée.
4. Le Policy Engine vérifie les permissions.
5. Le runner crée un contexte isolé.
6. Le skill s'exécute.
7. La sortie est validée.
8. Les résultats et logs expurgés sont persistés.
9. Le planner reçoit le résultat structuré.

## 5. Skills Alpha

### web_research
Entrée : question, périmètre, profondeur.
Sortie : sources, faits, synthèse, limites.
Permissions : recherche et lecture web.

### business_planning
Entrée : objectif, contexte, contraintes.
Sortie : étapes, dépendances, risques, KPI.
Permissions : aucune action externe.

### browser_readonly
Entrée : URL autorisée et objectif de lecture.
Sortie : titre, contenu extrait, liens pertinents.
Permissions : navigateur en lecture seule sur domaines autorisés.

## 6. Tests obligatoires

- schéma d'entrée ;
- schéma de sortie ;
- comportement nominal ;
- timeout ;
- données malformées ;
- tentative d'accès non autorisé ;
- injection dans le contenu consulté ;
- limite de ressources ;
- résultat reproductible lorsque possible.

## 7. Évolution autonome

Kwes pourra proposer un skill et générer une branche de travail. La publication exige :
- validation statique ;
- tests ;
- analyse des dépendances ;
- scan de sécurité ;
- revue de permissions ;
- approbation selon la politique.

Un skill généré ne peut jamais modifier le policy engine, les secrets, les contrôles d'accès ou ses propres permissions.
