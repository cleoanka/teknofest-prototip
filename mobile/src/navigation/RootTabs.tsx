import React from "react";
import { Text } from "react-native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import LiveScreen from "../screens/live/LiveScreen";
import EventsScreen from "../screens/events/EventsScreen";
import EventDetailScreen from "../screens/events/EventDetailScreen";
import AnalyticsScreen from "../screens/analytics/AnalyticsScreen";
import SystemScreen from "../screens/system/SystemScreen";
import { colors, font } from "../theme";
import type { AuthMode } from "../api/auth";

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

const screenHeaderStyle = {
  headerStyle: { backgroundColor: colors.bgElev },
  headerTitleStyle: { color: colors.text, fontWeight: font.bold as any },
  headerTintColor: colors.accent,
  contentStyle: { backgroundColor: colors.bg },
};

function TabIcon({ icon, focused }: { icon: string; focused: boolean }) {
  return <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.45 }}>{icon}</Text>;
}

function EventsStack({ onError }: { onError: (e: unknown) => void }) {
  return (
    <Stack.Navigator screenOptions={screenHeaderStyle}>
      <Stack.Screen name="EventsList" options={{ title: "Olaylar" }}>
        {(props) => <EventsScreen {...props} onError={onError} />}
      </Stack.Screen>
      <Stack.Screen name="EventDetail" component={EventDetailScreen} options={{ title: "Olay Detayı" }} />
    </Stack.Navigator>
  );
}

export default function RootTabs({ authMode, onError }: { authMode: AuthMode; onError: (e: unknown) => void }) {
  return (
    <Tab.Navigator
      screenOptions={{
        ...screenHeaderStyle,
        tabBarStyle: { backgroundColor: colors.bgElev, borderTopColor: colors.border, borderTopWidth: 1, height: 60, paddingBottom: 6, paddingTop: 6 },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
      }}
    >
      <Tab.Screen
        name="Canlı"
        options={{ tabBarIcon: ({ focused }) => <TabIcon icon="📹" focused={focused} /> }}
      >
        {() => <LiveScreen />}
      </Tab.Screen>

      <Tab.Screen
        name="Olaylar"
        options={{ headerShown: false, tabBarIcon: ({ focused }) => <TabIcon icon="📋" focused={focused} /> }}
      >
        {() => <EventsStack onError={onError} />}
      </Tab.Screen>

      <Tab.Screen
        name="Analitik"
        options={{ tabBarIcon: ({ focused }) => <TabIcon icon="📊" focused={focused} /> }}
      >
        {() => <AnalyticsScreen onError={onError} />}
      </Tab.Screen>

      <Tab.Screen
        name="Sistem"
        options={{ tabBarIcon: ({ focused }) => <TabIcon icon="⚙️" focused={focused} /> }}
      >
        {() => <SystemScreen authMode={authMode} onError={onError} />}
      </Tab.Screen>
    </Tab.Navigator>
  );
}
