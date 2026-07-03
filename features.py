"""
features.py — Ingénierie des caractéristiques transactionnelles
(section 3.2.6 du mémoire), calculées à partir de rawLog.csv.
"""

import numpy as np
import pandas as pd


class FeatureEngineer:
    """
    Calcule, pour chaque transaction du rawLog, l'ensemble des features
    dérivées formalisées en section 3.2.6 :
    ΔBorig, ΔBdest, r1, r2, Flag_anomalie, δ_commission, Var_agent,
    ρ_rupture, ρ_refund, V1h, Flag_nuit, ρ_nouveau.
    """

    def __init__(self, df: pd.DataFrame, eps: float = 1e-6):
        self.df = df.copy().sort_values(["step"]).reset_index(drop=True)
        self.eps = eps

    # ------------------------------------------------------------------
    def compute_all(self) -> pd.DataFrame:
        df = self.df
        df = self._delta_balances(df)
        df = self._ratios_r1_r2(df)
        df = self._flag_anomalie(df)
        df = self._flag_nuit(df)
        df = self._velocity_1h(df)
        df = self._delta_commission_smurfing(df)
        df = self._var_agent_split_deposit(df)
        df = self._rho_rupture_fake_cred(df)
        df = self._rho_refund(df)
        df = self._rho_nouveau(df)
        self.df = df
        return df

    # ------------------------------------------------------------------
    # ΔBorig, ΔBdest — 3.2.6, éq. 3.8 / 3.9
    # ------------------------------------------------------------------
    def _delta_balances(self, df: pd.DataFrame) -> pd.DataFrame:
        df["delta_B_orig"] = df["oldBalanceOrig"] - df["newBalanceOrig"]
        df["delta_B_dest"] = df["newBalanceDest"] - df["oldBalanceDest"]
        return df

    # ------------------------------------------------------------------
    # r1, r2 — éq. 3.10 / 3.11 (feature clé ATO)
    # ------------------------------------------------------------------
    def _ratios_r1_r2(self, df: pd.DataFrame) -> pd.DataFrame:
        df["r1"] = df["amount"] / (df["oldBalanceOrig"] + self.eps)
        df["r2"] = df["amount"] / (df["newBalanceOrig"] + self.eps)
        df["r1_r2_product"] = df["r1"] * df["r2"]  # exploitable par un nœud MultKAN
        return df

    # ------------------------------------------------------------------
    # Flag_anomalie — éq. 3.12, fenêtre glissante des 10 dernières opérations
    # du même compte ET du même type de transaction
    # ------------------------------------------------------------------
    def _flag_anomalie(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values(["nameOrig", "action", "step"]).reset_index(drop=True)
        grp = df.groupby(["nameOrig", "action"])["amount"]
        # rolling sur les 10 dernières tx AVANT la courante (shift pour éviter la fuite)
        rolling_mean = grp.transform(lambda s: s.shift(1).rolling(10, min_periods=2).mean())
        rolling_std = grp.transform(lambda s: s.shift(1).rolling(10, min_periods=2).std())
        threshold = rolling_mean + 2 * rolling_std
        df["flag_anomalie"] = (df["amount"] > threshold).fillna(False)
        return df.sort_values("step").reset_index(drop=True)

    # ------------------------------------------------------------------
    # Flag_nuit — éq. 3.18
    # ------------------------------------------------------------------
    def _flag_nuit(self, df: pd.DataFrame) -> pd.DataFrame:
        hour_of_day = df["step"] % 24
        df["flag_nuit"] = ((hour_of_day >= 22) | (hour_of_day < 6))
        return df

    # ------------------------------------------------------------------
    # V1h — éq. 3.17, nombre de tx du compte émetteur dans la fenêtre glissante 1h
    # (ici : le step précédent inclus, puisque 1 step = 1h dans ce simulateur)
    # ------------------------------------------------------------------
    def _velocity_1h(self, df: pd.DataFrame) -> pd.DataFrame:
        counts_per_step = df.groupby(["nameOrig", "step"]).size().rename("v1h_raw")
        df = df.merge(counts_per_step, on=["nameOrig", "step"], how="left")
        df["v1h"] = df["v1h_raw"]
        df = df.drop(columns=["v1h_raw"])
        return df

    # ------------------------------------------------------------------
    # δ_commission — éq. 3.13, feature Smurfing
    # Appariement transaction TRANSFER entrante la plus récente / sortante
    # la plus proche pour un même compte (candidat mule)
    # ------------------------------------------------------------------
    def _delta_commission_smurfing(self, df: pd.DataFrame) -> pd.DataFrame:
        df["delta_commission"] = np.nan
        df["delta_commission_ratio"] = np.nan
        df["is_mule_candidate"] = False

        transfers = df[df["action"] == "TRANSFER"].copy()
        if transfers.empty:
            return df

        in_tx = transfers[["nameDest", "step", "amount"]].rename(
            columns={"nameDest": "account", "amount": "amount_in", "step": "step_in"})
        out_tx = transfers[["nameOrig", "step", "amount"]].rename(
            columns={"nameOrig": "account", "amount": "amount_out", "step": "step_out"})

        in_tx = in_tx.sort_values(["account", "step_in"])
        out_tx = out_tx.sort_values(["account", "step_out"])

        # appariement asof : pour chaque sortie, la dernière entrée précédente sur le même compte
        merged = pd.merge_asof(
            out_tx.sort_values("step_out"), in_tx.sort_values("step_in"),
            left_on="step_out", right_on="step_in", by="account", direction="backward")
        merged["delta"] = merged["amount_in"] - merged["amount_out"]
        merged["delta_ratio"] = merged["delta"] / (merged["amount_in"] + self.eps)

        # Critère 1 de Zhdanova et al. : 0 < δ ≤ 10% du montant reçu
        merged["is_mule_candidate"] = (merged["delta_ratio"] > 0) & (merged["delta_ratio"] <= 0.10)

        agg = merged.groupby("account").agg(
            delta_commission_ratio=("delta_ratio", "last"),
            is_mule_candidate=("is_mule_candidate", "any")).reset_index()

        df = df.merge(
            agg.rename(columns={"account": "nameOrig"}),
            on="nameOrig", how="left", suffixes=("", "_mule"))
        df["delta_commission_ratio"] = df["delta_commission_ratio_mule"].combine_first(
            df["delta_commission_ratio"])
        df["is_mule_candidate"] = df["is_mule_candidate_mule"].fillna(False)
        df = df.drop(columns=[c for c in df.columns if c.endswith("_mule")])
        return df

    # ------------------------------------------------------------------
    # Var_agent — éq. 3.14, Split Deposit
    # Regroupement des CASH_IN au même step, même agent (orig), même client (dest)
    # -> équivalent de la fenêtre 60-120s puisque le simulateur les génère
    # simultanément au même step (limitation de granularité horaire assumée)
    # ------------------------------------------------------------------
    def _var_agent_split_deposit(self, df: pd.DataFrame) -> pd.DataFrame:
        df["var_agent_split"] = np.nan
        df["k_fragments"] = 0

        cash_in = df[df["action"] == "CASH_IN"].copy()
        if cash_in.empty:
            return df

        grp = cash_in.groupby(["nameOrig", "nameDest", "step"])["amount"]
        stats = grp.agg(
            var_agent_split=lambda x: float(np.var(x)),  # ddof=0 (eq. 3.14), pas ddof=1 pandas
            k_fragments="count"
        ).reset_index()
        stats["var_agent_split"] = stats["var_agent_split"].fillna(0.0)

        df = df.merge(stats, on=["nameOrig", "nameDest", "step"], how="left",
                       suffixes=("", "_new"))
        df["var_agent_split"] = df["var_agent_split_new"].combine_first(df["var_agent_split"])
        df["k_fragments"] = df["k_fragments_new"].fillna(0).astype(int)
        df = df.drop(columns=[c for c in df.columns if c.endswith("_new")])
        return df

    # ------------------------------------------------------------------
    # Helper vectorisé : somme/compte sur fenêtre glissante par borne de step,
    # via cumsum + searchsorted (O(n log n), aucune boucle Python par ligne)
    # ------------------------------------------------------------------
    @staticmethod
    def _windowed_sum_by_group(steps: np.ndarray, values: np.ndarray,
                                lo_bounds: np.ndarray, hi_bounds: np.ndarray) -> np.ndarray:
        """
        steps, values : triés par step, déjà filtrés sur le groupe (ex: un compte).
        lo_bounds, hi_bounds : pour chaque requête i, la fenêtre [lo_bounds[i], hi_bounds[i]).
        Retourne la somme de `values` dont step ∈ [lo, hi) pour chaque requête.
        """
        cumsum = np.concatenate([[0.0], np.cumsum(values)])
        idx_lo = np.searchsorted(steps, lo_bounds, side="left")
        idx_hi = np.searchsorted(steps, hi_bounds, side="left")
        return cumsum[idx_hi] - cumsum[idx_lo]
    
    
    # ------------------------------------------------------------------
    # ρ_rupture — éq. 3.15, Fake Credentials
    # Moyenne historique sur 30j glissants AVANT la transaction courante
    # ------------------------------------------------------------------
    def _rho_rupture_fake_cred(self, df: pd.DataFrame) -> pd.DataFrame:
        window_steps = 30 * 24
        df = df.sort_values(["nameOrig", "step"]).reset_index(drop=True)

        mean_hist = np.full(len(df), np.nan)
        for _, idx in df.groupby("nameOrig").indices.items():
            idx = np.sort(idx)
            steps_g = df["step"].values[idx]
            amounts_g = df["amount"].values[idx]

            lo = steps_g - window_steps
            hi = steps_g  # exclusif : strictement avant la transaction courante

            sums = self._windowed_sum_by_group(steps_g, amounts_g, lo, hi)
            counts = self._windowed_sum_by_group(steps_g, np.ones_like(amounts_g), lo, hi)
            means = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
            mean_hist[idx] = means

        df["mean_historique_30j"] = mean_hist
        df["rho_rupture"] = df["amount"] / (df["mean_historique_30j"].fillna(0) + self.eps)
        return df

    # ------------------------------------------------------------------
    # ρ_refund — éq. 3.16, fenêtre glissante 30j
    # ------------------------------------------------------------------
    def _rho_refund(self, df: pd.DataFrame) -> pd.DataFrame:
        window_steps = 30 * 24
        df = df.sort_values(["nameOrig", "step"]).reset_index(drop=True)

        is_refund = (df["action"].values == "REFUND").astype(float)
        is_payment = (df["action"].values == "PAYMENT").astype(float)
        rho = np.zeros(len(df))

        for _, idx in df.groupby("nameOrig").indices.items():
            idx = np.sort(idx)
            steps_g = df["step"].values[idx]
            refund_g = is_refund[idx]
            payment_g = is_payment[idx]

            lo = steps_g - window_steps
            hi = steps_g + 1  # inclusif : la transaction courante compte

            n_refund = self._windowed_sum_by_group(steps_g, refund_g, lo, hi)
            n_payment = self._windowed_sum_by_group(steps_g, payment_g, lo, hi)
            rho[idx] = n_refund / (n_payment + self.eps)

        df["rho_refund"] = rho
        return df

    # ------------------------------------------------------------------
    # ρ_nouveau — éq. 3.19, ratio de destinataires inconnus sur 30/90j
    # ------------------------------------------------------------------
    def _rho_nouveau(self, df: pd.DataFrame) -> pd.DataFrame:
        window_hist = 90 * 24
        window_recent = 30 * 24
        df = df.sort_values(["nameOrig", "step"]).reset_index(drop=True)

        # étape 1 (vectorisée) : dernier contact avec ce même (nameOrig, nameDest)
        # avant la transaction courante -> is_new_dest = pas de contact dans les 90j précédents
        last_contact_step = df.groupby(["nameOrig", "nameDest"])["step"].shift(1)
        gap = df["step"] - last_contact_step
        is_new_dest = (last_contact_step.isna() | (gap > window_hist)).astype(float).values

        # étape 2 (vectorisée) : moyenne glissante de is_new_dest sur la fenêtre 30j
        # par compte émetteur, via searchsorted/cumsum
        rho = np.zeros(len(df))
        for _, idx in df.groupby("nameOrig").indices.items():
            idx = np.sort(idx)
            steps_g = df["step"].values[idx]
            novelty_g = is_new_dest[idx]

            lo = steps_g - window_recent
            hi = steps_g + 1  # inclusif

            sums = self._windowed_sum_by_group(steps_g, novelty_g, lo, hi)
            counts = self._windowed_sum_by_group(steps_g, np.ones_like(novelty_g), lo, hi)
            rho[idx] = sums / np.maximum(counts, 1)

        df["rho_nouveau"] = rho
        return df
    


if __name__ == "__main__":
    df_raw = pd.read_csv("rawLog_torch.csv")
    engineer = FeatureEngineer(df_raw)
    df_features = engineer.compute_all()
    df_features.to_csv("featuresLog.csv", index=False)

    print(df_features[["step", "action", "amount", "r1", "r2", "flag_anomalie",
                        "flag_nuit", "v1h", "delta_commission_ratio",
                        "is_mule_candidate", "var_agent_split", "rho_rupture",
                        "rho_refund", "rho_nouveau"]].tail(20))