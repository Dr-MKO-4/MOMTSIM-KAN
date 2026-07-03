"""
backend/schemas.py — Modèles Pydantic pour l'API MoMTSim-KAN.
"""

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Config fraude — miroir exact de FRAUD_CONFIG (fraudScenariosConfig.json)
# ---------------------------------------------------------------------------

class GlobalConfig(BaseModel):
    fraud_target_min: float = Field(0.20, ge=0.0, le=1.0)
    fraud_target_max: float = Field(0.26, ge=0.0, le=1.0)
    scenarios_equal_share: bool = True


class ATOConfig(BaseModel):
    B_min: float = Field(50000, ge=0)
    n_min: int = Field(2, ge=1)
    n_max: int = Field(6, ge=1)
    frag_min: float = Field(0.15, ge=0.0, le=1.0)
    frag_max: float = Field(0.35, ge=0.0, le=1.0)
    lambda_ato: float = Field(6.0, gt=0)


class RefundConfig(BaseModel):
    p_refund_threshold: float = Field(0.7, ge=0.0, le=1.0)
    delay_min_hours: int = Field(1, ge=0)
    delay_max_hours: int = Field(48, ge=1)
    k_max: int = Field(4, ge=1)
    ratio_legit: float = Field(0.30, ge=0.0, le=1.0)


class FakeCredentialsConfig(BaseModel):
    dormance_min_days: int = Field(7, ge=0)
    dormance_max_days: int = Field(30, ge=1)
    n_leg_min: int = Field(3, ge=0)
    n_leg_max: int = Field(8, ge=1)
    m_leg_max: float = Field(5000, ge=0)
    m_exp_ratio_min: float = Field(0.5, ge=0.0, le=1.0)


class TariffSlot(BaseModel):
    threshold: float
    commission: float


class SplitDepositConfig(BaseModel):
    epsilon_max: float = Field(500, ge=0)
    T_split_min_sec: int = Field(60, ge=0)
    T_split_max_sec: int = Field(120, ge=1)
    tariff_grid: list[TariffSlot] = Field(default_factory=list)


class SmurfingConfig(BaseModel):
    n_mules_min: int = Field(4, ge=1)
    n_mules_max: int = Field(10, ge=1)
    pct_conscious: float = Field(0.60, ge=0.0, le=1.0)
    pct_unconscious: float = Field(0.40, ge=0.0, le=1.0)
    S_seuil: float = Field(500000, ge=0)
    delta_min: float = Field(0.01, ge=0.0, le=1.0)
    delta_max: float = Field(0.10, ge=0.0, le=1.0)
    delay_mule_min_hours: int = Field(2, ge=0)
    delay_mule_max_hours: int = Field(24, ge=1)
    operation_interval_days: int = Field(30, ge=1)
    n_leg_mule_min: int = Field(5, ge=0)
    n_leg_mule_max: int = Field(15, ge=1)


class FraudConfig(BaseModel):
    global_: GlobalConfig = Field(alias="global", default_factory=GlobalConfig)
    ato: ATOConfig = Field(default_factory=ATOConfig)
    refund: RefundConfig = Field(default_factory=RefundConfig)
    fake_credentials: FakeCredentialsConfig = Field(default_factory=FakeCredentialsConfig)
    split_deposit: SplitDepositConfig = Field(default_factory=SplitDepositConfig)
    smurfing: SmurfingConfig = Field(default_factory=SmurfingConfig)

    model_config = {"populate_by_name": True}

    def to_json_dict(self) -> dict:
        d = self.model_dump(by_alias=True)
        # rename global_ → global in output
        if "global_" in d:
            d["global"] = d.pop("global_")
        return d


# ---------------------------------------------------------------------------
# Paramètres de simulation
# ---------------------------------------------------------------------------

class SimulationParams(BaseModel):
    n_clients: int = Field(2000, ge=100, le=10000)
    n_merchants: int = Field(300, ge=10)
    n_banks: int = Field(20, ge=1)
    n_mules: int = Field(60, ge=0)
    n_steps: int = Field(720, ge=24, le=8760)
    max_slots: int = Field(6, ge=1, le=20)
    seed: int = Field(1000, ge=0)
    fraud_probas: Optional[dict[str, float]] = None


# ---------------------------------------------------------------------------
# Job & résultats pipeline
# ---------------------------------------------------------------------------

class JobStatus(BaseModel):
    job_id: str
    status: str  # "pending" | "running" | "done" | "error"
    progress: int = 0          # 0–100
    message: str = ""
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class SimulationResult(BaseModel):
    n_transactions: int
    fraud_rate: float
    fraud_by_scenario: dict[str, float]
    steps_run: int
    csv_path: str
    charts: dict[str, str] = {}   # nom → HTML Plotly embed


class FeatureResult(BaseModel):
    n_rows: int
    n_features: int
    feature_names: list[str]
    csv_path: str
    charts: dict[str, str] = {}


class KANValidationResult(BaseModel):
    VE2: float
    J_Fisher: float
    D_KS_mean: float
    k_for_VE80: int
    decision: str
    features_needing_transform: list[str]
    features_poor_coverage: list[str]
    ks_per_feature: dict[str, float]
    grid_coverage: dict[str, float]
    charts: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class CalibrationParams(BaseModel):
    n_clients: int = Field(500, ge=50)
    n_merchants: int = Field(100, ge=10)
    n_banks: int = Field(10, ge=1)
    n_mules: int = Field(30, ge=0)
    target_mid: float = Field(0.23, ge=0.1, le=0.5)
    n_steps: int = Field(720, ge=24)
    n_bins: int = Field(30, ge=5)
    n_seeds_per_eval: int = Field(3, ge=1)
    maxiter: int = Field(25, ge=5, le=200)
    lr: float = Field(0.05, gt=0)
    spsa_c: float = Field(0.02, gt=0)


class CalibrationResult(BaseModel):
    probas: dict[str, float]
    sse_final: float
    converged: bool
    history: list[dict[str, Any]]
