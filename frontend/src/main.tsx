import '@fontsource-variable/sora';
import '@fontsource-variable/instrument-sans';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/app.css';
import './styles/ui-polish.css';
import './styles/home.css';
import './styles/chat.css';
import './styles/login-brand.css';
import './styles/brand.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error("Élément #root introuvable dans index.html");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Service worker : cache de l'app shell en production uniquement (jamais en dev).
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((cause: unknown) => {
      console.warn('[Kwes] Enregistrement du service worker impossible', cause);
    });
  });
}
