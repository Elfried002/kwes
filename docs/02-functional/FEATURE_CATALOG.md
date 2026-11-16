# Catalogue fonctionnel — Kwes

Ce document décrit les modules et les responsabilités attendues.

## F01 — Command Center

**But :** présenter l'état de Kwes et donner accès aux fonctions principales.

Données affichées :
- état de connexion ;
- état du service IA ;
- dernière conversation ;
- missions actives ;
- missions nécessitant une action ;
- activité récente.

Actions :
- démarrer une conversation ;
- ouvrir une mission ;
- reprendre une mission ;
- accéder aux paramètres ;
- ouvrir le centre d'activité.

États : chargement, opérationnel, dégradé, hors ligne, erreur.

## F02 — Chat

**But :** fournir un canal textuel persistant.

Actions :
- envoyer un message ;
- afficher le streaming ;
- arrêter une génération ;
- reprendre une conversation ;
- créer une nouvelle conversation ;
- afficher les pièces jointes autorisées.

Règles :
- messages utilisateur et assistant horodatés ;
- messages système/outils distingués visuellement ;
- les erreurs fournisseur ne doivent pas être présentées comme une réponse valide ;
- le backend reste l'autorité de stockage.

## F03 — Voice

**But :** permettre un échange vocal naturel.

États :
- `idle` ;
- `requesting_permission` ;
- `listening` ;
- `transcribing` ;
- `thinking` ;
- `speaking` ;
- `interrupted` ;
- `error`.

Actions :
- activer le micro ;
- couper le micro ;
- interrompre la réponse ;
- afficher la transcription ;
- changer la langue ou le mode automatique ;
- réessayer après une erreur.

Le navigateur doit demander l'autorisation micro. Aucun enregistrement permanent en arrière-plan ne doit être supposé.

## F04 — Task Manager

**But :** suivre les missions indépendamment de la session web.

Champs :
- titre ;
- objectif ;
- statut ;
- priorité ;
- échéance facultative ;
- étapes ;
- progression ;
- résultat ;
- erreurs ;
- provenance de la demande.

Actions :
- créer ;
- consulter ;
- mettre en pause ;
- reprendre ;
- annuler ;
- relancer une étape lorsque sûr.

## F05 — Skills

**But :** exposer des capacités contrôlées au moteur agentique.

Chaque skill doit déclarer :
- identifiant et version ;
- description ;
- schéma d'entrée ;
- schéma de sortie ;
- outils nécessaires ;
- permissions ;
- timeout ;
- politique de retry ;
- tests.

Un skill ne peut pas s'accorder de nouvelles permissions.

## F06 — Memory

**But :** conserver les éléments utiles à la continuité.

Types :
- préférences ;
- faits de profil explicitement fournis ;
- résumés de conversations ;
- connaissances de projet ;
- méthodes et procédures.

Actions :
- consulter ;
- corriger ;
- supprimer ;
- désactiver une catégorie ;
- demander à Kwes ce qu'il retient.

Ne pas stocker automatiquement des secrets, données de paiement ou informations sensibles non nécessaires.

## F07 — Web Research

**But :** rechercher et synthétiser des informations accessibles.

Étapes :
1. clarifier la question si nécessaire ;
2. rechercher ;
3. ouvrir les sources ;
4. extraire les éléments pertinents ;
5. distinguer faits, hypothèses et incertitudes ;
6. produire une synthèse avec références ;
7. enregistrer le rapport.

Les pages web sont des données non fiables, jamais des instructions de système.

## F08 — Browser Operator

Alpha : lecture et interaction limitée avec sites autorisés ou environnements de test.

Les opérations d'achat, de paiement, d'envoi externe ou de modification irréversible sont interdites sans contrôle spécifique.

## F09 — Business Planning

Transforme un objectif en plan :
- objectif ;
- hypothèses ;
- étapes ;
- dépendances ;
- ressources ;
- risques ;
- indicateurs ;
- prochaines actions.

## F10 — Security Center

Expose :
- connexions ;
- permissions ;
- approbations en attente ;
- historique d'audit ;
- état des clés sans révéler les valeurs ;
- limites de budget.

## F11 — Language Intelligence

Détecte la langue, accepte une sélection manuelle, gère le code-switching lorsque le moteur le permet et applique un fallback transparent.

## F12 — Notifications

Événements :
- mission terminée ;
- mission bloquée ;
- approbation demandée ;
- erreur nécessitant intervention ;
- rapport prêt.

Les notifications push sont une amélioration progressive ; le centre de notifications interne est requis.
