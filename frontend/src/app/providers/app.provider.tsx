import React from 'react';
import { ThemeProvider } from './theme.provider';
import { AuthProvider } from './auth.provider';
import type { AuthStore } from '../stores/auth.store';

export interface AppProviderProps {
  auth: AuthStore;
  children: React.ReactNode;
}

const AppProvider: React.FC<AppProviderProps> = (props) => {
  return (
    <AuthProvider auth={props.auth}>
      <ThemeProvider>{props.children}</ThemeProvider>
    </AuthProvider>
  );
};

export default AppProvider;
