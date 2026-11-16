"""Preuve navigateur de la voix Gemini : micro simulé, audio réel, aucun mock.

Chromium est lancé avec un faux périphérique d'entrée alimenté par un WAV
(« --use-file-for-fake-audio-capture »). On ouvre l'écran vocal, on active le
micro, et on vérifie que des buffers audio sont réellement programmés à la
lecture — mesure instrumentée sur AudioContext.createBufferSource.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path("/home/babayaga/business/kwes")
WAV = ROOT / ".probe/question-silence-16k.wav"
URL = "http://127.0.0.1:5173/#/parler"


def main() -> int:
    session = json.loads((ROOT / ".sb_session.json").read_text())
    session["expires_at"] = 4102444800

    instrument = """
    window.__kwesVoice = { started: 0, seconds: 0, chunks: 0, errors: [] };
    const originalStart = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function (...args) {
      try {
        if (this.buffer) {
          window.__kwesVoice.started += 1;
          window.__kwesVoice.seconds += this.buffer.duration;
        }
      } catch (e) {}
      return originalStart.apply(this, args);
    };
    const originalSend = WebSocket.prototype.send;
    WebSocket.prototype.send = function (payload) {
      try {
        const data = JSON.parse(payload);
        if (data.type === 'audio') window.__kwesVoice.chunks += 1;
      } catch (e) {}
      return originalSend.call(this, payload);
    };
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={WAV}",
                "--autoplay-policy=no-user-gesture-required",
            ]
        )
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.grant_permissions(["microphone"], origin="http://127.0.0.1:5173")
        context.add_init_script(
            "localStorage.setItem('kwes.auth.supabase', %s);" % json.dumps(json.dumps(session))
        )
        context.add_init_script(instrument)
        page = context.new_page()
        logs: list[str] = []
        page.on("console", lambda message: logs.append(f"{message.type}: {message.text}"))
        page.goto(URL)
        page.wait_for_timeout(2500)
        print("écran :", page.locator("body").inner_text()[:90].replace("\n", " | "))

        # Le micro de l'écran vocal (le dot central ouvre, lui, l'écran lui-même).
        dot = page.locator(".vs-fab").first
        dot.click()
        page.wait_for_timeout(9000)

        stats = page.evaluate("window.__kwesVoice")
        phase = page.get_attribute(".voice-screen", "data-phase")
        print("phrase :", phase, "| stats:", stats)
        page.screenshot(path=str(ROOT / "frontend/.review/voice-gemini-390x844.png"))
        print("capture : frontend/.review/voice-gemini-390x844.png")

        page.wait_for_timeout(4000)
        stats2 = page.evaluate("window.__kwesVoice")
        print("après 4 s de plus :", stats2)
        print("erreurs console :", [line for line in logs if "error" in line.lower()][:3])
        browser.close()

    ok = stats["started"] > 0 and stats["seconds"] > 0.5 and stats["chunks"] > 0
    print("VERDICT :", "audio réel reçu et joué" if ok else "échec (aucun audio joué)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
