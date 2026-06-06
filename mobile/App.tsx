import React, { useCallback, useState } from "react";
import { View, StyleSheet } from "react-native";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { NavigationContainer, DarkTheme, Theme } from "@react-navigation/native";
import BootstrapScreen from "./src/screens/BootstrapScreen";
import RootTabs from "./src/navigation/RootTabs";
import { ErrorBanner } from "./src/components/ErrorBanner";
import { ApiError, ApiErrorKind } from "./src/api/client";
import { AuthMode } from "./src/api/auth";
import { colors } from "./src/theme";

const navTheme: Theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: colors.accent,
    background: colors.bg,
    card: colors.bgElev,
    text: colors.text,
    border: colors.border,
    notification: colors.danger,
  },
};

interface AppErr { message: string; kind: ApiErrorKind; }

export default function App() {
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [appErr, setAppErr] = useState<AppErr | null>(null);

  const handleError = useCallback((e: unknown) => {
    if (e instanceof ApiError) setAppErr({ message: e.message, kind: e.kind });
    else if (e instanceof Error) setAppErr({ message: e.message, kind: "server" });
  }, []);

  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      {authMode == null ? (
        <BootstrapScreen onReady={setAuthMode} />
      ) : (
        <NavigationContainer theme={navTheme}>
          <RootTabs authMode={authMode} onError={handleError} />
        </NavigationContainer>
      )}

      {appErr && (
        <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
          <ErrorBanner message={appErr.message} kind={appErr.kind} onDismiss={() => setAppErr(null)} />
        </View>
      )}
    </SafeAreaProvider>
  );
}
