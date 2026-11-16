# Parcours utilisateurs — Kwes

## Parcours A — Première connexion

1. L'utilisateur ouvre `kwes.<domain>`.
2. L'application affiche l'identité Kwes.
3. L'utilisateur s'authentifie.
4. Un écran d'accueil explique les capacités et limites.
5. L'utilisateur choisit ses préférences de langue.
6. Il peut tester le chat.
7. Il peut accorder l'accès microphone séparément.
8. Il arrive au Command Center.

**Règle UX :** ne pas demander l'accès microphone avant que l'utilisateur active une fonction vocale.

## Parcours B — Conversation texte

1. Cliquer dans la zone de saisie.
2. Écrire le message.
3. Envoyer avec le bouton ou Entrée.
4. Voir un état de réflexion.
5. Voir la réponse progressive si le streaming est activé.
6. Copier ou poursuivre la conversation.

États d'erreur : connexion perdue, réponse interrompue, fournisseur indisponible, session expirée.

## Parcours C — Conversation vocale

1. Cliquer sur le bouton micro.
2. Autoriser le microphone.
3. Voir l'Orb passer à `Listening`.
4. Parler.
5. Voir éventuellement la transcription.
6. Voir l'Orb passer à `Thinking`.
7. Entendre la réponse.
8. Interrompre à tout moment.
9. Reprendre ou basculer en texte.

L'interface doit afficher un indicateur clair lorsque le micro est actif.

## Parcours D — Délégation d'une mission

1. Formuler un objectif.
2. Kwes confirme brièvement sa compréhension.
3. Le plan et les étapes apparaissent.
4. Les opérations autorisées démarrent.
5. La progression est visible.
6. Une demande de validation apparaît si nécessaire.
7. Le résultat final est présenté.
8. L'utilisateur peut demander une correction.

## Parcours E — Consultation d'une mission en cours

1. Ouvrir Activity.
2. Filtrer `En cours`.
3. Sélectionner une mission.
4. Consulter étapes, logs résumés et résultats.
5. Reprendre la conversation liée à la mission.

## Parcours F — Mode dégradé

Si le VPS ou un fournisseur est indisponible :
- afficher un statut dégradé ;
- préserver le brouillon local lorsque possible ;
- ne pas déclarer l'action effectuée ;
- proposer une nouvelle tentative ;
- ne pas multiplier les retries côté navigateur.

## Navigation principale

- Home
- Activity
- Memory
- Skills
- Settings

La navigation peut être latérale sur desktop et compacte sur mobile. La conversation reste l'action dominante.
