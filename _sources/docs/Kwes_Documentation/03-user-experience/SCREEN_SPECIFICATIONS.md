# Spécifications des écrans — Kwes

## 1. Home / Command Center

### Objectif
Point d'entrée calme et centré sur la conversation.

### Éléments
- logo et nom Kwes ;
- état de connexion ;
- message d'accueil ;
- Hybrid Orb ;
- zone de saisie ;
- bouton microphone ;
- missions actives ;
- navigation.

### Interactions
- cliquer sur Orb : ouvrir ou activer la conversation, selon le mode ;
- saisir un message : démarrer un tour ;
- sélectionner une mission : ouvrir son détail ;
- sélectionner Activity : consulter toutes les missions.

### États
- initial ;
- conversation active ;
- agent occupé ;
- hors ligne ;
- erreur fournisseur.

## 2. Conversation

- en-tête avec titre et statut ;
- fil chronologique ;
- distinction utilisateur / Kwes / outil ;
- zone de saisie ;
- actions copier, arrêter, recommencer ;
- affichage de sources ou pièces jointes lorsque pertinentes.

Ne jamais afficher les traces internes de raisonnement privées. Afficher plutôt un résumé de plan, les actions et leurs résultats.

## 3. Activity

Liste avec :
- nom ;
- statut ;
- date ;
- progression ;
- priorité ;
- résultat ou blocage.

Filtres : toutes, en cours, terminées, en attente, échouées.

## 4. Task Detail

- objectif ;
- statut ;
- étapes ;
- progression ;
- événements ;
- résultats ;
- actions pause/reprise/annulation selon statut.

## 5. Memory

- recherche ;
- catégories ;
- élément mémorisé ;
- source ou date si connue ;
- modifier ;
- supprimer.

## 6. Skills

- nom ;
- description ;
- version ;
- état activé/désactivé ;
- permissions ;
- derniers tests ;
- bouton détail.

Alpha : les skills système ne sont pas modifiables librement depuis l'interface.

## 7. Settings

Sections :
- profil ;
- langue ;
- voix ;
- notifications ;
- intégrations ;
- confidentialité ;
- sécurité.

Les clés API ne sont jamais affichées en clair.

## 8. Responsive

Mobile :
- conversation pleine largeur ;
- navigation compacte ;
- Orb redimensionné ;
- actions accessibles au pouce ;
- aucune information essentielle dépendante du hover.

Desktop :
- navigation discrète ;
- contenu centré ;
- panneau d'activité contextuel facultatif.
