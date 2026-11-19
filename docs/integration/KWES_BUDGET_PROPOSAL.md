# KWES — Proposition de budgets (agents)

**Date :** 19 novembre 2026
**Statut :** proposition, **aucun plafond financier fixé**. Les montants en euros restent `null` en attendant ta validation du barème.

---

## 1. Principe : réutiliser les quotas existants, ne rien inventer

Le moteur possède déjà trois mécanismes de limitation, qui doivent rester la seule source de vérité :

| Mécanisme existant | Où | Ce qu'il limite |
|---|---|---|
| Quotas LLM par tour | `max_tool_rounds=2`, `max_tool_calls_per_round=3` | 6 appels d'outil par tour de conversation |
| Budget vocal | `google_live_daily_budget_eur=3,00` + `voice_sessions.estimated_usd` | dépense vocale par utilisateur et par jour |
| Limites de tâche | `timeout_seconds`, `max_retries` | durée et reprises d'une exécution |

Les budgets d'agents s'y **ajoutent** sans les remplacer : un agent ne peut jamais dépenser plus que le quota utilisateur qui l'a déclenché.

---

## 2. Base de calcul : ce que la production mesure déjà

Données réelles du serveur (base `kwes`, 19/11/2026) :

```
missions terminées            78
durée moyenne                 8,8 s
durée maximale observée       132 s
étapes par mission            1,7 en moyenne, 4 au maximum
exécutions enregistrées       122
```

Conséquences :

- un délai de **180 s par tâche** laisse 36 % de marge sur le maximum observé (132 s) ;
- un plafond de **8 étapes par mission** couvre deux fois le maximum observé (4) ;
- 4 agents en parallèle × 180 s = **720 s** de charge théorique ; c'est pourquoi un plafond de mission à **900 s** est proposé (une mission ne peut pas dépasser 15 minutes de calcul cumulé).

---

## 3. Budgets proposés (unités mesurables, pas d'euros)

### 3.1 Par tâche

| Limite | Valeur proposée | Justification |
|---|---|---|
| Durée d'exécution | 180 s | 36 % au-dessus du maximum observé ; sous la borne dure de 600 s du schéma |
| Appels d'outil | 12 | 2 × la limite actuelle d'un tour (6) : permet 4 tours de 3 appels |
| Tours LLM | 4 | un tour pour comprendre, deux pour agir, un pour conclure |
| Tentatives | 2 | identique au moteur actuel, uniquement sur erreur non ambiguë |

### 3.2 Par agent

| Limite | Valeur proposée | Justification |
|---|---|---|
| Appels d'outil simultanés | 1 | un agent travaille en séquence ; le parallélisme est décidé par Core |
| Durée cumulée par mission | 900 s | 5 × 180 s, couvre les reprises |
| Messages émis vers d'autres agents | 3 | via Core uniquement, jamais en direct |

### 3.3 Par mission

| Limite | Valeur proposée | Justification |
|---|---|---|
| Agents en parallèle | 4 | valeur déjà présente dans `core/config.yaml` (`max_parallel_agents: 4`) |
| Étapes | 8 | 2 × le maximum observé |
| Appels d'outil cumulés | 60 | 5 agents × 12 appels |
| Durée cumulée | 900 s | cohérent avec le plafond par agent |
| Confirmations humaines | sans limite | une action A3/A4 n'est jamais bloquée par un budget |

---

## 4. Coût : ce qui manque pour fixer un plafond en euros

**Le moteur ne journalise pas aujourd'hui les tokens consommés par appel.** Il enregistre la durée, les tours et le coût vocal, pas les tokens texte. Fixer maintenant un plafond en euros reviendrait à inventer une base de calcul.

Deux mesures sont donc nécessaires avant tout plafond financier :

1. **Instrumenter** : `agent_runs.input_tokens`, `output_tokens` et `cost_eur` existent déjà dans la migration `0016` (préparée, non appliquée). Il suffit de les alimenter à chaque appel.
2. **Établir le barème** : le prix par million de tokens d'entrée et de sortie, et le prix par minute vocale (déjà connu : 0,005 $/min entrant, 0,018 $/min sortant, conversion 0,92).

La formule à appliquer ensuite, une fois le barème connu :

```
coût_tâche = (tokens_entrée / 1 000 000 × prix_entrée)
           + (tokens_sortie / 1 000 000 × prix_sortie)
           + (minutes_vocales_entrantes  × 0,005 × 0,92)
           + (minutes_vocales_sortantes × 0,018 × 0,92)
```

Tant que `max_cost_eur_per_task` vaut `null`, le moteur applique le quota utilisateur existant et journalise le coût estimé sans le plafonner : aucune dépense ne peut donc dépasser ce que l'utilisateur peut déjà consommer aujourd'hui.

---

## 5. Exemple de calcul, à titre indicatif (à valider)

Hypothèse de travail, à remplacer par le barème réel : 0,10 € par million de tokens d'entrée, 0,40 € par million de sortie (ordre de grandeur des modèles « flash »).

Une tâche d'agent typique, mesurée sur les missions actuelles :

```
2 tours LLM × (2 000 tokens entrée + 300 tokens sortie)
= 4 000 entrée, 600 sortie
= 4 000/1e6 × 0,10 + 600/1e6 × 0,40
= 0,0004 + 0,00024 = 0,00064 €  (≈ 0,0006 €)
```

Une mission de 5 tâches coûterait donc environ **0,003 €**, et 1 000 missions environ **3 €**.

**Ce calcul n'est qu'une projection** : il dépend du barème réel et du nombre de tours effectifs. Il montre seulement que les budgets proposés (§3) sont dimensionnés bien au-dessus du besoin réel, ce qui est voulu pour éviter de bloquer une mission légitime.

---

## 6. Ce que je te demande de valider

1. Les limites en unités mesurables du §3 (180 s, 12 appels, 4 tours, 900 s, 8 étapes, 4 agents).
2. Le principe de ne fixer un plafond en euros **qu'après** instrumentation et communication du barème.
3. Le barème à appliquer (prix par million de tokens, entrée et sortie).
4. Le mode de dépassement : refus net, ou poursuite avec alerte puis arrêt en fin de mission ? (je recommande le refus net pour une tâche, l'alerte pour une mission).
