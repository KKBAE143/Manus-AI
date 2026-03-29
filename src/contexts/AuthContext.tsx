import React, { createContext, useContext, useMemo } from 'react';

type LocalUser = {
  uid: string;
  displayName: string;
  email: string;
};

interface AuthContextType {
  user: LocalUser | null;
  loading: boolean;
  signingIn: boolean;
  signIn: () => Promise<void>;
  logOut: () => Promise<void>;
  error: string | null;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const value = useMemo<AuthContextType>(
    () => ({
      user: {
        uid: 'local-user',
        displayName: 'Local Operator',
        email: 'local@manuscript.app',
      },
      loading: false,
      signingIn: false,
      signIn: async () => undefined,
      logOut: async () => undefined,
      error: null,
    }),
    []
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
