# Kwes — un seul fournisseur : Gemini

**Décision** : DeepSeek et ElevenLabs sont retirés. Tout le raisonnement, les appels
d'outils et la voix passent par Gemini. Il n'existe plus de second fournisseur de
raisonnement ni de repli secret vers un autre modèle.

## Répartition des modèles

| Usage | Modèle | Réflexion | Pourquoi |
|---|---|---|---|
| Conversation vocale rapide | `gemini-3.8-live` | aucune | latence minimale, tour de parole naturel |
| Tâche vocale complexe | `gemini-3.8-live-extended-thinking` | `ThinkingLevel.HIGH` | raisonnement long, activé explicitement |
| Échange écrit simple | `gemini-3.8-flash` | `LOW` | réponse rapide, une seule requête |
| Planification de mission | `gemini-3.8-flash` | `HIGH` | plan multi-étapes vérifiable |

**Règle appliquée** : un message = un modèle = un appel. Les deux modèles ne tournent
jamais en parallèle sur la même phrase. En vocal, la bascule vers le modèle approfondi
est explicite (`{"type":"mode","value":"thinking"}`) et le retour au mode rapide est
automatique après la réponse (`fin_reponse`) : la bascule automatique a été retirée
parce qu'elle annulait la réponse en cours de génération.

## Repli de disponibilité (et non second fournisseur)

Quand un modèle Gemini répond `429` ou `503` (saturation côté Google), le client essaie
le suivant dans la chaîne, pendant au plus 40 s :

1. `gemini-3.8-flash` (+ `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`)

Un modèle en échec est mis au repos **2 minutes** : les messages suivants ne repayent
pas le délai. Le modèle réellement utilisé est journalisé (`Réponse produite par le
modèle de repli …`) et renvoyé dans `LLMResult.model`.

Conséquence assumée : tant que `gemini-3.8-flash` est saturé, la qualité de
raisonnement est celle d'un modèle « lite ». Les plans sont donc encadrés :

- schéma de réponse imposé (`PLAN_SCHEMA`) : le modèle ne peut pas renvoyer un tableau
  nu ni des champs vides ;
- normalisation des confusions de champs (`content`/`value`, `key`/`title`) ;
- retrait des champs que le skill n'accepte pas (`additionalProperties: false`) ;
- si le texte d'un document est une consigne au lieu d'un corps, la synthèse sourcée
  de l'étape amont est utilisée — jamais du texte inventé.

## Ce qui a été supprimé

- `app/agent/deepseek.py` → remplacé par `app/agent/llm.py` (`GeminiTextClient`).
- Clés `DEEPSEEK_*` retirées de `.env`, champs `deepseek_*` retirés de la configuration.
- `providers` de `/health` ne contient plus que `gemini`.
- ElevenLabs : aucune référence (code, configuration, bundle de production).

## Preuves

- `240 passed, 4 skipped` (backend), `134 passed` (frontend), `tsc` propre, build OK.
- Appel d'outil réel en conversation : `web_research` → réponse citant RFI et
  l'ANSSI Côte d'Ivoire, en 11 s.
- Mission complète : 2 recherches + 1 lecture de page + 1 document de 2 535 caractères
  avec section « Sources consultées », statut `completed`.
