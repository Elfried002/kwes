# SUBAGENT_TASKS — Kwes

| ID | Rôle | Responsable | Dépendances | Statut | Livrable |
|---|---|---|---|---|---|
| A | Backend & API | sous-agent A (backend/) | Contrats | IN_PROGRESS | FastAPI complet + tests |
| B | Frontend & Orb | sous-agent B (frontend/) | Contrats | IN_PROGRESS | App React/TS + build |
| C | Données & Infra | sous-agent C (supabase/, infra/, .github/) | Contrats | IN_PROGRESS | SQL, Docker, CI |
| D | IA & Skills | inclus dans lot A | A | IN_PROGRESS | Orchestrateur + 3 skills |
| E | QA & Revue | agent principal (moi) | A, B, C | À FAIRE | Rapport de tests |
| F | Intégration & corrections | agent principal | A, B, C | À FAIRE | Correctifs + preuves |

Règles : un seul propriétaire par répertoire ; contrats figés dans `CONTRACTS.md` ; aucune fusion sans relecture ; tout rapport doit contenir des commandes et sorties réelles.
