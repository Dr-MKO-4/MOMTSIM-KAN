import { createContext, useContext, useState } from "react";
import type { SimulationResult, CalibrationResult } from "../types/api";

interface AppState {
  simJobId:      string | null;
  simResult:     SimulationResult | null;
  calibJobId:    string | null;
  calibResult:   CalibrationResult | null;
  setSimJobId:   (id: string | null) => void;
  setSimResult:  (r: SimulationResult | null) => void;
  setCalibJobId: (id: string | null) => void;
  setCalibResult:(r: CalibrationResult | null) => void;
}

const AppContext = createContext<AppState>(null!);

function loadLS<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch { return null; }
}

function saveLS(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch { /* quota exceeded  ignore */ }
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [simJobId,    setSimJobIdRaw]    = useState<string | null>(null);
  const [calibJobId,  setCalibJobIdRaw]  = useState<string | null>(null);
  const [simResult,   setSimResultRaw]   = useState<SimulationResult | null>(
    () => loadLS<SimulationResult>("momtsim_sim_result")
  );
  const [calibResult, setCalibResultRaw] = useState<CalibrationResult | null>(
    () => loadLS<CalibrationResult>("momtsim_calib_result")
  );

  const setSimResult = (r: SimulationResult | null) => {
    saveLS("momtsim_sim_result", r);
    setSimResultRaw(r);
  };
  const setCalibResult = (r: CalibrationResult | null) => {
    saveLS("momtsim_calib_result", r);
    setCalibResultRaw(r);
  };

  return (
    <AppContext.Provider value={{
      simJobId, simResult, calibJobId, calibResult,
      setSimJobId: setSimJobIdRaw,
      setSimResult,
      setCalibJobId: setCalibJobIdRaw,
      setCalibResult,
    }}>
      {children}
    </AppContext.Provider>
  );
}

export const useAppState = () => useContext(AppContext);
