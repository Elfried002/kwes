const ETAPES = [
  'Créer un compte Meta for Developers et un portefeuille professionnel (Meta Business Portfolio).',
  'Créer une application de type Business et y ajouter le produit WhatsApp.',
  'Créer ou sélectionner un WhatsApp Business Account (WABA).',
  'Ajouter un numéro professionnel compatible avec les règles Meta et le vérifier.',
  'Créer un utilisateur système et générer un jeton permanent aux permissions minimales.',
  'Déclarer l’URL de webhook HTTPS et valider le challenge de vérification.',
  'S’abonner aux événements de messages, puis tester un envoi vers un numéro autorisé.',
];

export function WhatsAppGuideScreen() {
  return (
    <div className="page stack">
      <header>
        <h1 style={{ fontSize: '1.35rem' }}>WhatsApp Business</h1>
        <p className="muted" style={{ fontSize: '0.875rem' }}>
          Ce que KWES peut faire, ce qu’il ne peut pas faire, et ce qu’il faut préparer côté Meta.
        </p>
      </header>

      <section className="card stack" style={{ gap: 8 }}>
        <strong>Trois choses différentes</strong>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.8125rem' }}>
          <li><strong>WhatsApp personnel</strong> : application grand public. Aucun accès officiel pour un agent. KWES ne s’y connecte pas.</li>
          <li><strong>WhatsApp Business App</strong> : application gratuite pour une petite entreprise, non pilotable par API.</li>
          <li><strong>WhatsApp Business Platform (Cloud API)</strong> : l’API officielle de Meta, celle que KWES utilise — messages d’entreprise, templates, webhooks.</li>
        </ul>
      </section>

      <section className="card stack" style={{ gap: 8 }}>
        <strong>Ce que KWES peut faire une fois connecté</strong>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.8125rem' }}>
          <li>envoyer un message dans la fenêtre de service autorisée par Meta ;</li>
          <li>envoyer un modèle (template) approuvé hors de cette fenêtre ;</li>
          <li>recevoir les messages entrants via webhook et y répondre ;</li>
          <li>consulter le statut de livraison fourni par Meta.</li>
        </ul>
        <p className="muted" style={{ fontSize: '0.75rem', margin: 0 }}>
          Les envois en masse et le démarchage exigent une politique dédiée : ils ne sont pas
          activés dans cette version.
        </p>
      </section>

      <section className="card stack" style={{ gap: 8 }}>
        <strong>Préparer la connexion, étape par étape</strong>
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: '0.8125rem' }}>
          {ETAPES.map((etape) => <li key={etape} style={{ marginBottom: 4 }}>{etape}</li>)}
        </ol>
      </section>

      <section className="card stack" style={{ gap: 8 }}>
        <strong>Statut actuel dans KWES</strong>
        <p className="muted" style={{ fontSize: '0.8125rem', margin: 0 }}>
          L’intégration est <strong>préparée mais non activée</strong> : les outils d’envoi et de
          réception restent marqués « déclarés » jusqu’à ce qu’un compte WABA de test soit fourni
          et qu’un envoi/réception réel soit vérifié. Aucun envoi n’est simulé.
        </p>
      </section>

      <section className="card stack" style={{ gap: 6 }}>
        <strong>Documentation officielle</strong>
        <a href="https://developers.facebook.com/docs/whatsapp/cloud-api/overview" target="_blank" rel="noreferrer noopener" style={{ fontSize: '0.8125rem' }}>
          Meta — WhatsApp Cloud API
        </a>
        <a href="https://developers.facebook.com/docs/whatsapp/embedded-signup" target="_blank" rel="noreferrer noopener" style={{ fontSize: '0.8125rem' }}>
          Meta — Embedded Signup (connexion par les clients)
        </a>
        <a href="https://faq.whatsapp.com/" target="_blank" rel="noreferrer noopener" style={{ fontSize: '0.8125rem' }}>
          Centre d’aide WhatsApp
        </a>
      </section>

      <a className="btn" href="#/connecteurs">Retour aux connecteurs</a>
    </div>
  );
}
