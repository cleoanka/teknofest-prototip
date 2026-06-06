import React, { useEffect, useRef } from "react";
import { Animated, View, StyleSheet } from "react-native";
import { colors, radius } from "../theme";

/** 0–100 değerini animasyonlu dolan çubukla gösterir. */
export function ProgressBar({ value, color = colors.accent, height = 10, track = colors.bgElev }: {
  value: number; color?: string; height?: number; track?: string;
}) {
  const anim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(anim, {
      toValue: Math.max(0, Math.min(100, value)),
      duration: 450,
      useNativeDriver: false,
    }).start();
  }, [value]);

  const width = anim.interpolate({ inputRange: [0, 100], outputRange: ["0%", "100%"] });

  return (
    <View style={[s.track, { height, backgroundColor: track, borderRadius: height }]}>
      <Animated.View style={[s.fill, { width, backgroundColor: color, borderRadius: height }]} />
    </View>
  );
}

const s = StyleSheet.create({
  track: { width: "100%", overflow: "hidden" },
  fill: { height: "100%" },
});
