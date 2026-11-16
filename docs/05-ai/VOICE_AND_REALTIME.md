# Voice Engine et temps réel — Kwes

## 1. Décision

Voie initiale : ElevenLabs Speech Engine avec DeepSeek comme cerveau externe, sous réserve de confirmer le produit/API et le protocole exacts disponibles au moment de l'intégration.

Ne pas confondre :
- Speech Engine ;
- ElevenAgents avec LLM externe ;
- modèles Eleven Realtime autonomes.

Les capacités et contraintes ne sont pas interchangeables. L'intégration doit suivre la documentation officielle correspondant au produit effectivement souscrit.

## 2. Responsabilités

### Frontend
- demander l'autorisation micro ;
- capturer l'audio ;
- afficher l'état ;
- jouer l'audio de réponse ;
- permettre l'interruption ;
- afficher la transcription lorsque disponible.

### Backend
- créer/valider la session ;
- gérer les jetons éphémères si le fournisseur le prévoit ;
- associer le tour vocal à une conversation ;
- appeler DeepSeek ;
- appliquer les politiques ;
- journaliser les événements sans stocker inutilement l'audio brut.

### ElevenLabs
- reconnaissance et/ou traitement vocal selon le mode ;
- synthèse vocale ;
- streaming audio ;
- configuration de la voix.

## 3. États UI

`idle → requesting_permission → connecting → listening → transcribing → thinking → speaking → idle`

États alternatifs :
- `interrupted`
- `reconnecting`
- `error`

## 4. Latence

Mesurer séparément :
- temps de connexion ;
- fin de parole → transcription ;
- transcription → premier token LLM ;
- premier token → premier audio ;
- durée totale du tour.

Optimisations :
- streaming ;
- réponses courtes au début ;
- limiter le contexte inutile ;
- précharger les métadonnées de session ;
- éviter les appels séquentiels non nécessaires.

## 5. Interruption

L'utilisateur doit pouvoir couper la sortie vocale immédiatement. L'interruption audio ne doit pas annuler automatiquement une mission serveur déjà créée.

## 6. Vie privée

- micro activé uniquement après action utilisateur ;
- indicateur visuel persistant ;
- ne pas enregistrer l'audio brut par défaut ;
- politique de conservation explicite ;
- possibilité de supprimer transcriptions et conversations ;
- ne pas exposer les identifiants de session fournisseur.

## 7. Voix masculine

Choisir une voix autorisée dans le compte ElevenLabs, tester le français et l'anglais, puis stocker son identifiant dans une variable serveur. Ne pas coder un ID supposé.

## 8. Mode dégradé

Si le service vocal échoue :
- proposer de continuer en texte ;
- conserver le message si la transcription est disponible ;
- ne pas perdre la conversation ;
- afficher l'erreur réelle.
