# Conception des composants — Kwes

## Backend

```text
backend/
  app/
    main.py
    config.py
    api/
      routes/
      dependencies/
    core/
      orchestrator.py
      planner.py
      tool_router.py
      task_manager.py
    providers/
      llm/
      voice/
    agents/
    skills/
      registry.py
      runner.py
      manifests/
    memory/
      service.py
      retrieval.py
    tasks/
      models.py
      queue.py
      worker.py
    security/
      policy_engine.py
      approval_service.py
      secrets.py
    integrations/
    observability/
```

## Frontend

```text
apps/web/src/
  app/
  components/
    orb/
    chat/
    tasks/
    navigation/
  features/
    conversation/
    voice/
    activity/
    memory/
    skills/
    settings/
  services/
    api.ts
    websocket.ts
  hooks/
  styles/
```

## Interfaces clés

### LLMProvider
- `generate(messages, tools, options)`
- `stream(messages, tools, options)`
- `health_check()`

### VoiceProvider
- `create_session(context)`
- `send_audio(session, chunk)`
- `receive_events(session)`
- `close_session(session)`

Les méthodes exactes doivent être adaptées au SDK/API officiel choisi.

### SkillRunner
- charger manifeste ;
- valider entrée ;
- vérifier permissions ;
- exécuter dans le contexte isolé ;
- valider sortie ;
- enregistrer le résultat.

### PolicyEngine
- classifier action ;
- vérifier permissions ;
- vérifier budget ;
- vérifier domaine/canal ;
- demander approbation ;
- émettre une décision traçable.

## Dépendances

Les domaines métier ne doivent pas importer directement les SDK DeepSeek ou ElevenLabs. Ils utilisent les interfaces de providers. Cela facilite le remplacement des fournisseurs et les tests.
