# Plan de tests — Kwes

## 1. Tests unitaires

- validation des entrées API ;
- transition des statuts ;
- classification des risques ;
- validation des manifests ;
- filtrage des données par utilisateur ;
- génération des événements.

## 2. Tests d'intégration

- FastAPI ↔ Supabase ;
- FastAPI ↔ Redis ;
- worker ↔ queue ;
- backend ↔ DeepSeek ;
- backend ↔ ElevenLabs ;
- frontend ↔ API ;
- frontend ↔ WebSocket.

Les appels fournisseurs doivent aussi être simulables en tests.

## 3. Tests bout en bout

### E2E-001 Chat
L'utilisateur envoie un message et reçoit une réponse réelle.

### E2E-002 Persistance
Fermer puis rouvrir l'application ; la conversation existe toujours.

### E2E-003 Mission
Créer une mission, observer ses étapes, obtenir un résultat enregistré.

### E2E-004 Reprise
Redémarrer un worker ; une tâche récupérable reprend sans doublon.

### E2E-005 Permission
Une action R3 est bloquée tant qu'une approbation valide n'existe pas.

### E2E-006 Voix
Autoriser le micro, parler, recevoir une réponse vocale et interrompre.

### E2E-007 Séparation utilisateur
Un utilisateur ne peut pas consulter les données d'un autre.

## 4. Tests sécurité

- absence de clés dans bundle frontend ;
- CORS ;
- accès API sans authentification ;
- accès à une ressource d'un autre utilisateur ;
- prompt injection dans page web ;
- SSRF vers localhost/IP privée ;
- dépassement de taille ;
- abus de rate limit ;
- replay d'approbation ;
- exécution d'un skill non autorisé.

## 5. Tests PWA

- installation desktop ;
- installation Android compatible ;
- affichage mobile ;
- écran hors ligne ;
- reconnexion ;
- permissions micro ;
- cache et mise à jour du service worker.

## 6. Critères de sortie

Aucun bug bloquant sur le scénario de démonstration. Aucun secret exposé. Les opérations non autorisées sont bloquées. Les échecs fournisseurs sont affichés honnêtement.
