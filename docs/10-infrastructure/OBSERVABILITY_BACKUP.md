# Observabilité et sauvegarde — Kwes

## 1. Logs

Format structuré recommandé :
- timestamp ;
- level ;
- service ;
- request_id ;
- user_id pseudonymisé si possible ;
- task_id ;
- operation ;
- duration_ms ;
- status ;
- error_code.

Ne pas journaliser le contenu complet des secrets ou données privées par défaut.

## 2. Métriques

- CPU/RAM/disque ;
- latence API ;
- erreurs API ;
- état Redis ;
- taille de queue ;
- durée des missions ;
- taux de succès des skills ;
- erreurs DeepSeek/ElevenLabs ;
- coût fournisseur si mesurable ;
- reconnexions WebSocket.

## 3. Alertes

- disque presque plein ;
- RAM durablement élevée ;
- worker sans heartbeat ;
- queue qui augmente ;
- service fournisseur indisponible ;
- erreurs répétées ;
- sauvegarde échouée.

## 4. Corrélation

Un `request_id` relie une requête HTTP, une conversation, une mission, ses étapes et ses appels outils.

## 5. Sauvegarde

- base de données ;
- fichiers nécessaires ;
- configuration non secrète ;
- manifests de skills ;
- journaux d'audit selon politique.

Les secrets sont sauvegardés séparément et chiffrés.

## 6. Restauration

Procédure testée :
1. provisionner environnement ;
2. restaurer données ;
3. restaurer fichiers ;
4. injecter secrets via gestionnaire sécurisé ;
5. lancer migrations ;
6. vérifier intégrité ;
7. exécuter tests de santé.
