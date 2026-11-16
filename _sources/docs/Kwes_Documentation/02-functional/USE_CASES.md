# Cas d'utilisation — Kwes

## UC-001 — Poser une question

**Acteur :** utilisateur  
**Précondition :** session authentifiée et backend disponible.

Flux nominal :
1. L'utilisateur ouvre une conversation.
2. Il saisit une question.
3. Le frontend envoie le message au backend.
4. Le backend charge le contexte pertinent.
5. DeepSeek génère une réponse.
6. Le backend enregistre la réponse.
7. Le frontend affiche le résultat.

Exceptions :
- fournisseur indisponible : afficher une erreur réessayable ;
- session expirée : demander une reconnexion ;
- dépassement de limite : informer l'utilisateur.

Critère : la conversation est retrouvable après reconnexion.

## UC-002 — Déléguer une mission

1. L'utilisateur formule un objectif.
2. Kwes identifie qu'il s'agit d'une mission multi-étapes.
3. Le plan est généré.
4. Le backend vérifie les outils et permissions.
5. La mission est persistée.
6. Les étapes sont mises en file.
7. Le worker exécute les étapes.
8. Les événements sont diffusés.
9. Les résultats sont vérifiés.
10. Un rapport final est enregistré.

Variantes :
- clarification nécessaire ;
- approbation requise ;
- outil indisponible ;
- mission annulée ;
- résultat partiel.

## UC-003 — Conversation vocale

1. L'utilisateur active le microphone.
2. Le navigateur demande l'autorisation si nécessaire.
3. Le composant vocal établit la session.
4. L'audio est transmis selon le protocole ElevenLabs retenu.
5. La transcription ou le texte reconnu est associé à la conversation.
6. Le backend appelle DeepSeek.
7. La réponse est renvoyée au moteur vocal.
8. L'audio de réponse est joué.
9. L'utilisateur peut interrompre la réponse.

Critère : l'utilisateur peut revenir au chat texte sans perdre le contexte.

## UC-004 — Recherche web

1. L'utilisateur demande une recherche.
2. Kwes choisit le skill `web_research`.
3. Le backend valide les paramètres.
4. Le skill consulte les sources autorisées.
5. Les extraits sont conservés avec leurs URL et dates lorsque disponibles.
6. Le skill synthétise les informations.
7. Kwes distingue les faits des inférences.
8. Le rapport est enregistré.

## UC-005 — Consulter une mission

1. L'utilisateur ouvre le centre d'activité.
2. Le frontend demande les missions de l'utilisateur.
3. Le backend applique le contrôle d'accès.
4. L'interface affiche statut, progression, étapes et événements.
5. L'utilisateur ouvre une étape pour consulter ses détails.

## UC-006 — Annuler une mission

1. L'utilisateur sélectionne Annuler.
2. Le frontend demande confirmation.
3. Le backend vérifie le propriétaire et le statut.
4. Un signal d'annulation est envoyé au worker.
5. Les étapes non démarrées sont annulées.
6. Les opérations déjà réalisées sont conservées dans l'audit.
7. Le statut final reflète l'état réel.

## UC-007 — Consulter et supprimer une mémoire

1. L'utilisateur ouvre Memory.
2. Kwes liste les éléments accessibles.
3. L'utilisateur sélectionne un élément.
4. Il peut le corriger ou le supprimer.
5. Le backend applique l'opération et journalise la modification.
6. Les index vectoriels associés sont mis à jour ou supprimés.

## UC-008 — Demander une opération sensible

1. Kwes prépare l'opération.
2. Le moteur de politique la classe.
3. Le backend crée une demande d'approbation contenant le détail exact.
4. L'utilisateur consulte le fournisseur, l'objet, le montant et les conditions.
5. L'utilisateur approuve ou refuse.
6. L'approbation est liée à la charge utile.
7. L'exécution n'a lieu qu'après validation.

Ce cas est documenté pour les versions futures. Les paiements ne font pas partie de l'Alpha.
