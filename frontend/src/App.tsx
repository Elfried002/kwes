import type { ReactNode } from 'react';
import { useSession } from './lib/auth';
import { useDocumentTitle } from './lib/hooks';
import { useRoute, type Route } from './lib/router';
import { KwesProvider } from './state/KwesProvider';
import { AppShell } from './components/AppShell';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LoginScreen } from './screens/LoginScreen';
import { HomeScreen } from './screens/HomeScreen';
import { ChatScreen } from './screens/ChatScreen';
import { ConversationsScreen } from './screens/ConversationsScreen';
import { TasksScreen } from './screens/TasksScreen';
import { TaskDetailScreen } from './screens/TaskDetailScreen';
import { ApprovalsScreen } from './screens/ApprovalsScreen';
import { SettingsScreen } from './screens/SettingsScreen';

function titleFor(route: Route): string {
  switch (route.name) {
    case 'home':
      return 'Accueil';
    case 'chat':
      return 'Chat';
    case 'conversations':
      return 'Conversations';
    case 'tasks':
      return 'Activités';
    case 'task':
      return 'Mission';
    case 'approvals':
      return 'Validations';
    case 'settings':
      return 'Réglages';
  }
}

function RoutedApp() {
  const session = useSession();
  const route = useRoute();
  useDocumentTitle(session ? titleFor(route) : 'Connexion');

  if (!session) {
    return <LoginScreen />;
  }

  let screen: ReactNode;
  switch (route.name) {
    case 'home':
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
  }

  return <AppShell route={route}>{screen}</AppShell>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <KwesProvider>
        <RoutedApp />
      </KwesProvider>
    </ErrorBoundary>
  );
}
