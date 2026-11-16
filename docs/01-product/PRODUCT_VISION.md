# Vision produit — Kwes

## 1. Résumé

Kwes est un agent personnel autonome, vocal et multilingue qui aide une personne à organiser et réaliser des tâches personnelles et professionnelles. Il combine une interface conversationnelle, un moteur de raisonnement, une mémoire persistante, des outils d'exécution et une supervision des opérations.

**Promesse :** transformer une intention exprimée naturellement en un plan exécutable, suivre son exécution et rendre compte du résultat.

## 2. Problème utilisateur

Les activités quotidiennes impliquent de nombreux outils, comptes, tâches, communications et décisions. L'utilisateur doit souvent :
- répéter le contexte ;
- passer d'une application à une autre ;
- décomposer manuellement les objectifs ;
- surveiller des tâches longues ;
- suivre les actions réalisées ;
- vérifier si une opération a réellement abouti.

Kwes vise à réduire cette charge de coordination, sans retirer à l'utilisateur le contrôle des décisions sensibles.

## 3. Principes produit

1. **Action plutôt que conversation seule :** une réponse ne suffit pas lorsqu'une tâche est attendue.
2. **Autonomie gouvernée :** l'agent peut agir dans une enveloppe de permissions et de budget définie.
3. **Preuve d'exécution :** une opération doit produire un résultat vérifiable.
4. **Continuité :** les tâches longues survivent à la fermeture de la PWA.
5. **Transparence :** l'utilisateur peut comprendre ce que Kwes fait, pourquoi et avec quel résultat.
6. **Modularité :** les fournisseurs IA et les intégrations sont remplaçables.
7. **Multilinguisme responsable :** ne jamais prétendre maîtriser une langue non évaluée.
8. **Sécurité par conception :** le LLM ne décide pas seul de ses permissions.

## 4. Utilisateurs et contexte

### Utilisateur Alpha
Une personne qui pilote plusieurs activités, souhaite déléguer des recherches, préparer des actions, organiser ses missions et interagir par la voix.

### Utilisateurs futurs
- indépendants et consultants ;
- dirigeants de petites entreprises ;
- équipes commerciales ;
- organisations souhaitant un assistant interne.

La version Alpha est mono-utilisateur dans son expérience, mais le modèle de données doit inclure `user_id` afin de ne pas bloquer une évolution multi-utilisateur.

## 5. Différenciation

- Interface centrée sur un agent identifiable plutôt que sur un tableau de bord surchargé.
- Continuité serveur des tâches.
- Compétences extensibles.
- Prise en compte progressive des langues et pratiques linguistiques africaines.
- Couplage entre voix, mémoire, planification et exécution d'outils.

## 6. Non-objectifs de l'Alpha

- Remplacer un humain dans toutes les décisions.
- Effectuer des paiements sans autorisation.
- Signer des contrats.
- Contourner les contrôles d'accès de sites tiers.
- Garantir une écoute micro permanente lorsque la PWA est fermée.
- Promettre une compréhension parfaite de toutes les langues locales.
- Modifier automatiquement le noyau ou les politiques de sécurité.
- Fournir une téléphonie de production sans validation réglementaire et fournisseur.

## 7. Indicateurs de succès

| Indicateur | Définition |
|---|---|
| Task completion rate | Missions terminées avec preuve / missions exécutables |
| Tool success rate | Appels d'outils réussis / appels tentés |
| Verified completion rate | Tâches vérifiées / tâches déclarées terminées |
| Voice turn latency | Temps entre fin de parole et première réponse audible |
| Recovery rate | Tâches reprises avec succès après incident |
| User correction rate | Missions nécessitant une correction importante |
| Cost per task | Coût fournisseur et infrastructure par mission |
| Safety violation rate | Actions bloquées ou incidents de politique |

Les seuils cibles seront fixés après une première mesure de référence, plutôt que d'inventer des performances avant les tests.
