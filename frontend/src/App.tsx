import { Routes, Route } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import ConfigPage from "./pages/ConfigPage";
import SimulationPage from "./pages/SimulationPage";
import FeaturesPage from "./pages/FeaturesPage";
import KANPage from "./pages/KANPage";
import CalibrationPage from "./pages/CalibrationPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/config" element={<ConfigPage />} />
      <Route path="/simulation" element={<SimulationPage />} />
      <Route path="/features" element={<FeaturesPage />} />
      <Route path="/kan" element={<KANPage />} />
      <Route path="/calibration" element={<CalibrationPage />} />
    </Routes>
  );
}
