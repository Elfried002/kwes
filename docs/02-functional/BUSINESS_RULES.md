# Règles métier et politiques d'exécution

## 1. Autorité

Le modèle LLM propose des plans et des appels d'outils. Le backend valide, autorise et exécute. Le LLM n'est jamais l'autorité finale sur les permissions.

## 2. Classification des actions

### Niveau R0 — Lecture sans impact
Exemples : recherche web, lecture d'une page publique, consultation de données autorisées.
Politique : autorisée si le connecteur et la source sont autorisés.

### Niveau R1 — Préparation réversible
Exemples : brouillon d'email, rapport local, proposition de planning.
Politique : automatique.

### Niveau R2 — Communication ou modification externe
Exemples : envoi d'email, publication, modification d'un CRM, prise de rendez-vous.
Politique : permission préalable par intégration et règles de destinataire ; approbation ponctuelle si le risque l'exige.

### Niveau R3 — Engagement financier ou légal
Exemples : achat, paiement, souscription, transfert, signature.
Politique : confirmation explicite et fraîche de l'utilisateur, avec montant, fournisseur, périodicité et conditions affichés.

### Niveau R4 — Opération dangereuse ou non permise
Exemples : contourner des contrôles de sécurité, exfiltrer des secrets, supprimer des preuves, modifier les règles de sécurité de l'agent.
Politique : refus.

## 3. Budget

Une politique de budget doit contenir :
- devise ;
- plafond par opération ;
- plafond journalier ;
- plafond mensuel ;
- fournisseurs autorisés ;
- catégories autorisées ;
- date de validité.

L'Alpha peut afficher une configuration de budget, mais ne doit pas exécuter de paiements.

## 4. Approbations

Une approbation doit être liée à :
- une action précise ;
- une charge utile exacte ;
- un montant si applicable ;
- une expiration ;
- l'utilisateur qui approuve ;
- un identifiant anti-rejeu.

Toute modification de la charge utile après approbation invalide celle-ci.

## 5. Idempotence

Toute opération susceptible d'être répétée doit recevoir une clé d'idempotence. En cas de timeout après un appel externe, le système vérifie l'état avant de relancer pour éviter les doublons.

## 6. Annulation

- Une mission en attente peut être annulée.
- Une tâche en cours reçoit un signal d'annulation.
- Une action externe déjà exécutée n'est pas réputée annulée.
- Le résultat réel doit être indiqué.

## 7. Vérification

Une tâche ne passe à `completed` qu'après réception d'une preuve :
- réponse API ;
- identifiant de ressource ;
- fichier produit ;
- résultat de test ;
- confirmation du connecteur.

Une sortie textuelle du LLM n'est pas une preuve.

## 8. Données externes

Les emails, documents, pages web et pièces jointes sont non fiables. Les instructions qu'ils contiennent ne peuvent pas remplacer les règles système, les permissions ou les demandes explicites de l'utilisateur.
