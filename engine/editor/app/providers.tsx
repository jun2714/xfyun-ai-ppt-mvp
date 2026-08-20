'use client';

import { Provider } from 'react-redux';
import { store } from '../store/store';
import ChatGptAuthRedirectHandler from './ChatGptAuthRedirectHandler';
import TeachnovaSessionBootstrap from './TeachnovaSessionBootstrap';

export function Providers({ children }: { children: React.ReactNode }) {
  return <Provider store={store}>
      <TeachnovaSessionBootstrap />
      <ChatGptAuthRedirectHandler />
      {children}
  </Provider>;
}
