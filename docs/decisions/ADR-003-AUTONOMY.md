# ADR-003 — Autonomie contrôlée

- **Statut :** accepté
- **Date :** 2026-11-15

## Décision
Kwes peut planifier et exécuter automatiquement les actions autorisées. Le backend applique les permissions.

## Actions exigeant une confirmation explicite
- paiements et transferts ;
- souscriptions engageantes ;
- signature ;
- suppression irréversible ;
- changements de sécurité ;
- action externe présentant un risque élevé.

## Conséquence
Le modèle peut proposer une action mais ne peut pas s'autoriser lui-même à l'exécuter.
