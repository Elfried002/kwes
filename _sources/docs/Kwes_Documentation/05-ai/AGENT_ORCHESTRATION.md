# Orchestration agentique — Kwes

## 1. Rôle du noyau

Le noyau coordonne les étapes d'une mission. Il ne doit pas être un simple prompt monolithique.

Responsabilités :
- classifier l'intention ;
- déterminer si une réponse directe suffit ;
- décider si une mission doit être créée ;
- produire un plan structuré ;
- sélectionner les skills disponibles ;
- vérifier les préconditions ;
- exécuter ;
- observer les résultats ;
- réviser le plan si nécessaire ;
- produire un compte rendu.

## 2. Cycle ReAct contrôlé

1. Observe : lire la demande et le contexte.
2. Plan : produire un plan structuré.
3. Authorize : contrôler chaque action.
4. Act : appeler un outil autorisé.
5. Verify : vérifier la sortie.
6. Reflect : déterminer la prochaine étape.
7. Report : présenter le résultat.

La réflexion privée du modèle n'est pas exposée. L'utilisateur voit le plan utile, les actions et les résultats.

## 3. Plan structuré

Exemple de représentation interne :

```json
{
  "goal": "Préparer une étude concurrentielle",
  "steps": [
    {
      "id": "step_1",
      "skill": "web_research",
      "input": {"query": "marché et concurrents"},
      "risk": "R0",
      "depends_on": []
    },
    {
      "id": "step_2",
      "skill": "business_planning",
      "input": {"source_step": "step_1"},
      "risk": "R1",
      "depends_on": ["step_1"]
    }
  ]
}
```

Le JSON doit être validé par un schéma strict avant exécution.

## 4. Tool calling

- Le modèle peut proposer un outil uniquement dans la liste fournie.
- Le backend valide le nom et les arguments.
- Les arguments sont validés par Pydantic/JSON Schema.
- Le moteur de politique décide si l'appel est permis.
- Les résultats d'outils sont traités comme des données non fiables.
- Un outil ne peut pas appeler directement un autre outil sans passer par le runtime.

## 5. Limites d'exécution

Paramètres à configurer :
- nombre maximal d'étapes ;
- nombre maximal d'appels outils ;
- budget tokens/coût ;
- durée maximale ;
- profondeur d'orchestration ;
- nombre de retries ;
- concurrence maximale.

Ces limites doivent être configurables côté serveur.

## 6. Gestion des erreurs

Catégories :
- validation ;
- permission ;
- fournisseur ;
- timeout ;
- réseau ;
- ressource absente ;
- sortie invalide ;
- erreur de skill.

Ne pas réessayer les erreurs permanentes ou les actions non idempotentes sans vérifier l'état externe.

## 7. Résultat final

Le rapport final inclut :
- objectif ;
- étapes réalisées ;
- résultats vérifiés ;
- sources ou preuves ;
- éléments non terminés ;
- erreurs ;
- actions restantes ;
- coût si disponible.

## 8. Multi-agent

Alpha : rôles spécialisés utilisant le même runtime et éventuellement le même modèle.

Évolution : agents séparés si des besoins d'isolation, de contexte, de coût ou de parallélisme sont démontrés.

Aucun agent spécialisé ne peut étendre ses propres permissions.
