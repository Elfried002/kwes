import type { ReactNode } from 'react';
import { useAuthReady, usePasswordRecovery, useSession } from './lib/auth';
import { useDocumentTitle } from './lib/hooks';
import { useRoute, guestScreen, isInstalledApp, type Route } from './lib/router';
import { KwesProvider } from './state/KwesProvider';
import { AppShell } from './components/AppShell';
import { ErrorBoundary } from './components/ErrorBoundary';
import { UpdateBanner } from './components/UpdateBanner';
import { BootSplash } from './components/BootSplash';
import { LoginScreen, PasswordRecoveryScreen } from './screens/LoginScreen';
import { PublicHome } from './screens/PublicHome';
import { HomeScreen } from './screens/HomeScreen';
import { ChatScreen } from './screens/ChatScreen';
import { ConversationsScreen } from './screens/ConversationsScreen';
import { TasksScreen } from './screens/TasksScreen';
import { TaskDetailScreen } from './screens/TaskDetailScreen';
import { ApprovalsScreen } from './screens/ApprovalsScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { ConnectorsScreen } from './screens/ConnectorsScreen';
import { WhatsAppGuideScreen } from './screens/WhatsAppGuideScreen';
import { AdminScreen } from './screens/AdminScreen';
import { VoiceScreen } from './screens/VoiceScreen';

function titleFor(route: Route): string {
  switch (route.name) {
    case 'home':
      return 'Accueil';
    case 'auth':
      return 'Connexion';
    case 'chat':
      return 'Parler';
    case 'voice':
      return 'Parler';
    case 'conversations':
      return 'Vos échanges';
    case 'tasks':
      return 'Ce qu’il fait';
    case 'task':
      return 'Ce qu’il fait';
    case 'approvals':
      return 'Il attend votre accord';
    case 'settings':
      return 'Réglages';
    case 'connectors':
      return 'Connecteurs';
    case 'whatsapp':
      return 'WhatsApp';
    case 'admin':
      return 'Cockpit';
  }
}

function BootScreen() {
  return (
    <div className="boot" role="status" aria-live="polite">
      <img src="/brand/droid-head.svg" alt="" width={44} height={44} />
      <span className="boot__spinner" aria-hidden="true" />
      <span className="sr-only">Vérification de votre session…</span>
    </div>
  );
}

function RoutedApp() {
  const session = useSession();
  const ready = useAuthReady();
  const recovery = usePasswordRecovery();
  const route = useRoute();
  // Application installée : la page publique a déjà été vue, on entre par la connexion.
  const installed = isInstalledApp();
  useDocumentTitle(
    !ready
      ? 'Chargement'
      : recovery
        ? 'Nouveau mot de passe'
        : session
          ? titleFor(route)
          : guestScreen(route, installed) === 'login'
            ? 'Connexion'
            : null,
  );

  if (!ready) {
    return <BootScreen />;
  }

  if (!session) {
    if (recovery) return <PasswordRecoveryScreen />;
    if (guestScreen(route, installed) === 'login') {
      const mode = route.name === 'auth' ? route.mode : 'signin';
      // Accès direct au mode vocal, ou app installée : on demande la connexion.
      return <LoginScreen key={route.name === 'auth' ? route.mode : 'installed'} initialMode={mode} />;
    }
    return <PublicHome />;
  }

  if (recovery) {
    return <PasswordRecoveryScreen />;
  }

  let screen: ReactNode;
  switch (route.name) {
    case 'home':
    case 'auth':
      screen = <HomeScreen />;
      break;
    case 'chat':
      screen = <ChatScreen conversationId={route.conversationId} />;
      break;
    case 'conversations':
      screen = <ConversationsScreen />;
      break;
    case 'tasks':
      screen = <TasksScreen />;
      break;
    case 'task':
      screen = <TaskDetailScreen id={route.id} key={route.id} />;
      break;
    case 'approvals':
      screen = <ApprovalsScreen />;
      break;
    case 'settings':
      screen = <SettingsScreen />;
      break;
    case 'connectors':
      screen = <ConnectorsScreen />;
      break;
    case 'whatsapp':
      screen = <WhatsAppGuideScreen />;
      break;
    case 'admin':
      screen = <AdminScreen />;
      break;
    case 'voice':
      // Plein écran : ni barre latérale, ni barre du bas, ni carte.
      return <VoiceScreen />;
  }

  return <AppShell route={route}>{screen}</AppShell>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <KwesProvider>
        <RoutedApp />
      </KwesProvider>
      <UpdateBanner />
      <BootSplash />
    </ErrorBoundary>
  );
}
