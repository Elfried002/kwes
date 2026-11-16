# Contrats API — Kwes

Base URL : `https://api.<domain>/api/v1`

Tous les endpoints privés exigent une session authentifiée. Les exemples sont illustratifs et doivent être validés avec les schémas Pydantic définitifs.

## 1. Health

`GET /health`

Réponse :
```json
{
  "status": "ok",
  "version": "0.1.0",
  "dependencies": {
    "database": "ok",
    "redis": "ok",
    "llm": "degraded"
  }
}
```

Ne pas exposer de secrets, stack traces ou détails internes.

## 2. Chat

`POST /chat`

Requête :
```json
{
  "conversation_id": null,
  "message": "Prépare une étude de marché",
  "language": "fr",
  "mode": "auto"
}
```

Réponse :
```json
{
  "conversation_id": "uuid",
  "message_id": "uuid",
  "response": "Je vais commencer par...",
  "task_id": "uuid",
  "status": "planning"
}
```

Le champ `task_id` est absent si aucune mission n'est créée.

## 3. Conversations

- `GET /conversations`
- `POST /conversations`
- `GET /conversations/{conversation_id}`
- `DELETE /conversations/{conversation_id}`

La suppression doit appliquer la politique de rétention et supprimer les données dérivées définies.

## 4. Tasks

- `POST /tasks`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `POST /tasks/{task_id}/cancel`
- `POST /tasks/{task_id}/pause`
- `POST /tasks/{task_id}/resume`

La propriété de la mission est vérifiée côté serveur pour chaque route.

## 5. Skills

- `GET /skills`
- `GET /skills/{skill_id}`

L'activation/désactivation administrative doit être séparée des routes utilisateur ordinaires.

## 6. Memory

- `GET /memory`
- `PATCH /memory/{memory_id}`
- `DELETE /memory/{memory_id}`

Toutes les opérations filtrent par utilisateur propriétaire.

## 7. Approvals

- `GET /approvals`
- `POST /approvals/{approval_id}/approve`
- `POST /approvals/{approval_id}/reject`

L'approbation est expirante et liée à un hash de charge utile.

## 8. WebSocket

`wss://api.<domain>/api/v1/ws`

Événements serveur :
- `conversation.delta`
- `conversation.completed`
- `task.created`
- `task.updated`
- `task.step.started`
- `task.step.completed`
- `task.awaiting_approval`
- `task.failed`
- `notification.created`
- `system.status`

Format :
```json
{
  "event": "task.updated",
  "event_id": "uuid",
  "timestamp": "2026-11-15T18:00:00Z",
  "data": {
    "task_id": "uuid",
    "status": "running",
    "progress": 45
  }
}
```

Prévoir heartbeat, reconnexion et récupération par REST après reconnexion. Ne pas supposer que le WebSocket est une source de vérité.

## 9. Erreurs

Format :
```json
{
  "error": {
    "code": "PROVIDER_UNAVAILABLE",
    "message": "Le service est temporairement indisponible.",
    "request_id": "uuid",
    "retryable": true
  }
}
```

Ne pas renvoyer les messages internes du fournisseur ou les secrets.

## 10. Sécurité API

- CORS strict ;
- authentification et autorisation ;
- rate limiting ;
- validation de payload ;
- taille maximale des requêtes ;
- protection contre replay pour les approbations ;
- logs expurgés ;
- versionnement `/api/v1`.
