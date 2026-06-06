import { StoredEvent } from "../types";

const now = Date.now() / 1000;
const min = (n: number) => now - n * 60;

/** EventListScreen'i doldurmak için 10 örnek olay */
export const MOCK_EVENTS: StoredEvent[] = [
  {
    plate: "35 KLM 44", vtype: "sedan", speed_kmh: 119,
    risk_score: 96, risk_level: "CRITICAL",
    factors: "fatigue,phone_use,speeding,no_seatbelt",
    mode: "CRITICAL", ts: min(2),
  },
  {
    plate: "34 ABC 123", vtype: "sedan", speed_kmh: 87,
    risk_score: 72, risk_level: "HIGH",
    factors: "phone_use,speeding",
    mode: "NORMAL", ts: min(8),
  },
  {
    plate: "06 XY 987", vtype: "SUV", speed_kmh: 98,
    risk_score: 41, risk_level: "MEDIUM",
    factors: "speeding",
    mode: "NORMAL", ts: min(15),
  },
  {
    plate: "16 DEF 55", vtype: "kamyonet", speed_kmh: 115,
    risk_score: 88, risk_level: "CRITICAL",
    factors: "fatigue,no_seatbelt,speeding",
    mode: "CRITICAL", ts: min(23),
  },
  {
    plate: "34 XZT 01", vtype: "sedan", speed_kmh: 68,
    risk_score: 18, risk_level: "LOW",
    factors: "",
    mode: "NORMAL", ts: min(40),
  },
  {
    plate: "07 GHI 77", vtype: "SUV", speed_kmh: 92,
    risk_score: 55, risk_level: "MEDIUM",
    factors: "headphone,speeding",
    mode: "NORMAL", ts: min(58),
  },
  {
    plate: "33 PQR 99", vtype: "sedan", speed_kmh: 103,
    risk_score: 79, risk_level: "HIGH",
    factors: "phone_use,fatigue",
    mode: "NORMAL", ts: min(75),
  },
  {
    plate: "34 STU 22", vtype: "hatchback", speed_kmh: 61,
    risk_score: 9, risk_level: "LOW",
    factors: "",
    mode: "NORMAL", ts: min(90),
  },
  {
    plate: "41 VWX 33", vtype: "sedan", speed_kmh: 134,
    risk_score: 93, risk_level: "CRITICAL",
    factors: "speeding,fatigue,no_seatbelt",
    mode: "CRITICAL", ts: min(112),
  },
  {
    plate: null, vtype: "kamyon", speed_kmh: 88,
    risk_score: 31, risk_level: "MEDIUM",
    factors: "speeding",
    mode: "NORMAL", ts: min(130),
  },
];
