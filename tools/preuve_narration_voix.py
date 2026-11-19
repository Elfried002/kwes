"""Preuve de la narration vocale, exécutée sur le serveur."""

import asyncio
import time

from app.agent.gemini_live import GeminiLiveSession
from app.agent.tools import tool_definitions
from app.core.config import Settings
from app.skills.registry import SkillRegistry

settings = Settings()
registry = SkillRegistry("/opt/kwes/backend/app/skills", settings)
registry.load()


async def executor(name, arguments):
    await asyncio.sleep(5)
    return {"status": "ok", "summary": "prix 1200 FCFA", "output": {}}


async def main():
    session = GeminiLiveSession(
        settings,
        definitions=tool_definitions(registry),
        memories=[],
        executor=executor,
        language="fr",
        mode="fast",
    )
    print("connexion...", flush=True)
    await session.start()
    print("connecté", flush=True)
    await session.send_text("Cherche le prix du cacao en Côte d Ivoire.")
    print("question envoyée", flush=True)
    depart = time.time()
    async for event in session.events():
        ecoule = time.time() - depart
        if event.type == "transcript":
            role = event.data.get("role")
            texte = str(event.data.get("text") or "")[:130]
            print(f"+{ecoule:.1f}s {role}: {texte}", flush=True)
        elif event.type == "tool":
            print(f"+{ecoule:.1f}s outil {event.data.get('name')} -> {event.data.get('status')}", flush=True)
        if ecoule > 45:
            break
    await session.close()


asyncio.run(main())
