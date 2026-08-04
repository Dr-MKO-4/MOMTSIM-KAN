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

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [simJobId,    setSimJobId]    = useState<string | null>(null);
  const [simResult,   setSimResult]   = useState<SimulationResult | null>(null);
  const [calibJobId,  setCalibJobId]  = useState<string | null>(null);
  const [calibResult, setCalibResult] = useState<CalibrationResult | null>(null);

  return (
    <AppContext.Provider value={{
      simJobId, simResult, calibJobId, calibResult,
      setSimJobId, setSimResult, setCalibJobId, setCalibResult,
    }}>
      {children}
    </AppContext.Provider>
  );
}

export const useAppState = () => useContext(AppContext);
