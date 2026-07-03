"""
viz.py — Visualisation et validation topologique KAN (sections 4.1 & 10 du mémoire).
Extrait des cellules 20 et 23 du notebook momtsim_kan_pipeline.ipynb.
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

FEATURES_12 = [
    "r1", "r2", "delta_B_orig", "delta_B_dest", "delta_commission_ratio",
    "var_agent_split", "rho_rupture", "rho_refund", "v1h",
    "flag_nuit", "rho_nouveau", "flag_anomalie",
]


class TopologyValidator:
    def __init__(self, df_features: pd.DataFrame, features: list = None, eps: float = 1e-6):
        self.features = features or FEATURES_12
        self.eps = eps
        self.df = df_features.copy()
        for f in self.features:
            self.df[f] = self.df[f].astype(float)
        self.df[self.features] = self.df[self.features].fillna(0.0)
        self.y = self.df["isFraud"].astype(int).values

        self.mu = None
        self.sigma = None
        self.X_norm = None
        self.V = None
        self.singular_values = None
        self.Z = None
        self.report = {}

    # eq. 4.1
    def normalize(self) -> np.ndarray:
        X = self.df[self.features].values
        self.mu = X.mean(axis=0)
        self.sigma = X.std(axis=0)
        self.X_norm = (X - self.mu) / (self.sigma + self.eps)
        return self.X_norm

    # eq. 4.2 / 4.3
    def pca(self, k_max: int = None):
        if self.X_norm is None:
            self.normalize()
        Xc = self.X_norm - self.X_norm.mean(axis=0)
        U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        self.V = Vt.T
        self.singular_values = S

        total_var = np.sum(S ** 2)
        ve2 = (S[0] ** 2 + S[1] ** 2) / total_var
        self.report["VE2"] = float(ve2)

        cum_var = np.cumsum(S ** 2) / total_var
        k80 = int(np.searchsorted(cum_var, 0.80) + 1)
        self.report["k_for_VE80"] = k80

        k = k_max or max(2, k80 if ve2 < 0.40 else 2)
        self.Z = Xc @ self.V[:, :k]
        self.report["k_used"] = k
        return self.Z

    # eq. 4.4
    def fisher_index(self, Z: np.ndarray = None) -> float:
        Z = Z if Z is not None else self.Z
        if Z is None:
            self.pca()
            Z = self.Z

        Z0 = Z[self.y == 0]
        Z1 = Z[self.y == 1]
        if len(Z0) == 0 or len(Z1) == 0:
            self.report["J_Fisher"] = float("nan")
            return float("nan")

        mu0, mu1 = Z0.mean(axis=0), Z1.mean(axis=0)
        S0 = (Z0 - mu0).T @ (Z0 - mu0)
        S1 = (Z1 - mu1).T @ (Z1 - mu1)
        Sw = S0 + S1

        Sw_inv = np.linalg.pinv(Sw)
        diff = (mu1 - mu0).reshape(-1, 1)
        numerator = float((diff.T @ Sw_inv @ diff).item())
        denominator = float(np.trace(Sw))
        j_fisher = numerator / (denominator + self.eps)

        self.report["J_Fisher"] = j_fisher
        return j_fisher

    # eq. 4.5 — test KS vs loi normale de référence
    @staticmethod
    def _ks_statistic_vs_normal(x: np.ndarray) -> float:
        x_sorted = np.sort(x)
        n = len(x_sorted)
        ecdf = np.arange(1, n + 1) / n
        cdf_normal = 0.5 * (1 + np.vectorize(math.erf)(x_sorted / np.sqrt(2)))
        d_stat = np.max(np.abs(ecdf - cdf_normal))
        return float(d_stat)

    def ks_per_feature(self) -> dict:
        if self.X_norm is None:
            self.normalize()
        ks_results = {}
        for j, feat in enumerate(self.features):
            col = self.X_norm[:, j]
            sample = col if len(col) <= 5000 else np.random.choice(col, 5000, replace=False)
            ks_results[feat] = self._ks_statistic_vs_normal(sample)
        self.report["ks_per_feature"] = ks_results
        self.report["ks_mean"] = float(np.mean(list(ks_results.values())))
        self.report["features_needing_transform"] = [f for f, d in ks_results.items() if d >= 0.15]
        return ks_results

    # eq. 4.6 — couverture de la grille sur [-3, 3]
    def grid_coverage(self, grid_min: float = -3.0, grid_max: float = 3.0) -> dict:
        if self.X_norm is None:
            self.normalize()
        coverage = {}
        for j, feat in enumerate(self.features):
            col = self.X_norm[:, j]
            x_min, x_max = col.min(), col.max()
            rho = (x_max - x_min) / (grid_max - grid_min + self.eps)
            coverage[feat] = float(rho)
        self.report["grid_coverage"] = coverage
        self.report["features_poor_coverage"] = [
            f for f, r in coverage.items() if not (0.8 <= r <= 1.0)]
        return coverage

    # eq. 4.7 — règle de décision
    def decide(self) -> str:
        j_fisher = self.report.get("J_Fisher")
        ve2 = self.report.get("VE2")
        ks_mean = self.report.get("ks_mean")
        needs_transform = len(self.report.get("features_needing_transform", [])) > 0

        if j_fisher is None or ve2 is None or ks_mean is None:
            raise RuntimeError("Exécuter pca(), fisher_index() et ks_per_feature() avant decide().")

        if j_fisher > 1 and ve2 >= 0.40 and ks_mean < 0.15:
            decision = "KAN valide"
        elif j_fisher > 1 and needs_transform:
            decision = "Transformations requises"
        else:
            decision = "Architecture alternative"

        self.report["decision"] = decision
        return decision

    def run_full_validation(self) -> dict:
        self.normalize()
        self.pca()
        self.fisher_index()
        self.ks_per_feature()
        self.grid_coverage()
        self.decide()
        return self.report

    def apply_recommended_transforms(self) -> pd.DataFrame:
        """log(1+x) sur les features signalées par le test KS."""
        to_transform = self.report.get("features_needing_transform", [])
        df_t = self.df.copy()
        for feat in to_transform:
            col = df_t[feat].values
            shifted = col - col.min() if col.min() < 0 else col
            df_t[feat] = np.log1p(shifted)
        return df_t

    def plot_pca_projection(self) -> go.Figure:
        if self.Z is None or self.Z.shape[1] < 2:
            self.pca(k_max=2)
        fig = go.Figure()
        for cls, color, label in [(0, "#636EFA", "Légitime"), (1, "#EF553B", "Fraude")]:
            mask = self.y == cls
            fig.add_trace(go.Scatter(
                x=self.Z[mask, 0], y=self.Z[mask, 1], mode="markers", name=label,
                marker=dict(size=4, color=color, opacity=0.5)))
        fig.update_layout(
            title=f"Projection PCA — VE2={self.report.get('VE2', 0):.3f}, "
                  f"J_Fisher={self.report.get('J_Fisher', 0):.3f}",
            xaxis_title="Composante principale 1", yaxis_title="Composante principale 2",
            template="plotly_dark", height=550,
            paper_bgcolor="#0F1117", plot_bgcolor="#0F1117",
            font=dict(color="#E2E8F0"))
        return fig

    def plot_ks_summary(self) -> go.Figure:
        ks = self.report.get("ks_per_feature", {})
        if not ks:
            self.ks_per_feature()
            ks = self.report["ks_per_feature"]
        feats = list(ks.keys())
        vals = list(ks.values())
        colors = ["#EF4444" if v >= 0.15 else "#22C55E" for v in vals]
        fig = go.Figure(data=[go.Bar(x=feats, y=vals, marker_color=colors)])
        fig.add_hline(y=0.15, line_dash="dash", line_color="#EF4444",
                      annotation_text="seuil D_KS = 0.15", annotation_font_color="#EF4444")
        fig.update_layout(
            title="Statistique KS par feature (régularité des distributions)",
            xaxis_title="Feature", yaxis_title="D_KS",
            template="plotly_dark", height=450,
            paper_bgcolor="#0F1117", plot_bgcolor="#0F1117",
            font=dict(color="#E2E8F0"))
        return fig


class MoMTSimVisualizer:
    def __init__(self, df_features: pd.DataFrame, df_target_agg: pd.DataFrame = None):
        self.df = df_features
        self.df_target = df_target_agg

    def _dark_layout(self, **kwargs) -> dict:
        base = dict(template="plotly_dark", paper_bgcolor="#0F1117",
                    plot_bgcolor="#0F1117", font=dict(color="#E2E8F0"))
        base.update(kwargs)
        return base

    def plot_volume_per_action(self) -> go.Figure:
        counts = self.df.groupby(["step", "action"]).size().reset_index(name="count")
        fig = go.Figure()
        palette = ["#3B82F6", "#22C55E", "#F59E0B", "#A78BFA", "#EC4899", "#06B6D4"]
        for i, action in enumerate(counts["action"].unique()):
            sub = counts[counts["action"] == action]
            fig.add_trace(go.Scatter(
                x=sub["step"], y=sub["count"], mode="lines", name=action,
                line=dict(width=1.5, color=palette[i % len(palette)])))
        fig.update_layout(title="Volume de transactions par step et par action",
                          xaxis_title="Step (heure)", yaxis_title="Nombre de transactions",
                          height=450, **self._dark_layout())
        return fig

    def plot_nrmse_comparison(self, action: str) -> go.Figure:
        if self.df_target is None:
            raise ValueError("df_target_agg requis pour cette visualisation")

        sim_counts = self.df[self.df["action"] == action].groupby("step").size()
        sim_counts = sim_counts.reindex(range(720), fill_value=0)

        target = self.df_target[self.df_target["action"] == action].set_index("step")["count"]
        target = target.reindex(range(720), fill_value=0)

        rmse = np.sqrt(np.mean((sim_counts.values - target.values) ** 2))
        span = target.values.max() - target.values.min()
        nrmse = rmse / span if span > 0 else float("nan")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=list(range(720)), y=target.values, mode="lines",
                                 name="Cible (réel)", line=dict(color="#EF4444", width=1.5)))
        fig.add_trace(go.Scatter(x=list(range(720)), y=sim_counts.values, mode="lines",
                                 name="Simulé", line=dict(color="#3B82F6", width=1.5, dash="dot")))
        fig.update_layout(
            title=f"Validation SSE — {action} (NRMSE = {nrmse:.4f})",
            xaxis_title="Step (heure)", yaxis_title="Nombre de transactions",
            height=450, **self._dark_layout())
        return fig

    def plot_fraud_scenario_distribution(self) -> go.Figure:
        fraud_df = self.df[self.df["isFraud"]]
        counts = fraud_df["fraudScenario"].value_counts()
        colors = ["#EF4444", "#3B82F6", "#22C55E", "#A78BFA", "#F59E0B"]
        fig = go.Figure(data=[go.Bar(
            x=counts.index, y=counts.values,
            marker_color=colors[:len(counts)])])
        fig.update_layout(
            title="Répartition des transactions frauduleuses par scénario",
            xaxis_title="Scénario", yaxis_title="Nombre de transactions",
            height=400, **self._dark_layout())
        return fig

    def plot_fraud_timeline(self) -> go.Figure:
        fraud_df = self.df[self.df["isFraud"]]
        counts = fraud_df.groupby(["step", "fraudScenario"]).size().reset_index(name="count")
        colors = {"ATO": "#EF4444", "REFUND": "#3B82F6", "FAKE_CRED": "#22C55E",
                  "SPLIT_DEP": "#A78BFA", "SMURFING": "#F59E0B"}
        fig = go.Figure()
        for scenario in counts["fraudScenario"].unique():
            sub = counts[counts["fraudScenario"] == scenario]
            fig.add_trace(go.Scatter(
                x=sub["step"], y=sub["count"], mode="markers+lines", name=scenario,
                marker=dict(size=4), line=dict(color=colors.get(scenario, "#94A3B8"), width=1)))
        fig.update_layout(
            title="Timeline des scénarios de fraude (720 steps = 30 jours)",
            xaxis_title="Step (heure)", yaxis_title="Nombre de tx frauduleuses",
            height=450, **self._dark_layout())
        return fig

    def plot_r1_r2_scatter(self) -> go.Figure:
        sample = self.df.sample(min(5000, len(self.df)), random_state=42)
        fig = go.Figure()
        for is_fraud, color, label in [(False, "#3B82F6", "Légitime"), (True, "#EF4444", "Fraude")]:
            sub = sample[sample["isFraud"] == is_fraud]
            fig.add_trace(go.Scatter(
                x=sub["r1"], y=sub["r2"], mode="markers", name=label,
                marker=dict(size=4, color=color, opacity=0.5)))
        fig.update_layout(
            title="r1 (montant/solde initial) vs r2 (montant/solde final)",
            xaxis_title="r1", yaxis_title="r2", height=500, **self._dark_layout())
        return fig

    def plot_feature_distributions(self, features: list = None) -> go.Figure:
        if features is None:
            features = ["r1", "r2", "rho_rupture", "rho_refund", "v1h", "rho_nouveau"]
        n = len(features)
        fig = make_subplots(rows=(n + 1) // 2, cols=2, subplot_titles=features)
        for i, feat in enumerate(features):
            row, col = i // 2 + 1, i % 2 + 1
            legit = self.df.loc[~self.df["isFraud"], feat].dropna()
            fraud = self.df.loc[self.df["isFraud"], feat].dropna()
            fig.add_trace(go.Histogram(x=legit, name="Légitime", marker_color="#3B82F6",
                                       opacity=0.6, histnorm="probability density",
                                       showlegend=(i == 0)), row=row, col=col)
            fig.add_trace(go.Histogram(x=fraud, name="Fraude", marker_color="#EF4444",
                                       opacity=0.6, histnorm="probability density",
                                       showlegend=(i == 0)), row=row, col=col)
        fig.update_layout(
            title="Distributions des features clés — légitime vs fraude",
            template="plotly_dark", height=300 * ((n + 1) // 2), barmode="overlay",
            paper_bgcolor="#0F1117", plot_bgcolor="#0F1117", font=dict(color="#E2E8F0"))
        return fig

    def plot_smurfing_network_delta(self) -> go.Figure:
        # delta_commission_ratio est calculé par compte nameOrig via merge_asof.
        # Il faut filtrer sur is_mule_candidate (comptes détectés comme mules)
        # plutôt que fraudScenario == "SMURFING" (qui inclut les transactions entrantes
        # fraudster→mule dont nameOrig n'est pas la mule, donc ratio = NaN).
        has_mule_col = "is_mule_candidate" in self.df.columns
        has_ratio_col = "delta_commission_ratio" in self.df.columns

        if has_mule_col and has_ratio_col:
            mule_mask = self.df["is_mule_candidate"].astype(bool)
            ratio_src = self.df.loc[mule_mask, "delta_commission_ratio"].dropna()
        elif has_ratio_col:
            # fallback : tous les comptes avec un ratio calculé
            ratio_src = self.df["delta_commission_ratio"].dropna()
        else:
            ratio_src = pd.Series([], dtype=float)

        # Séparer mules vrais SMURFING vs mules candidates non-étiquetées
        fig = go.Figure()
        if has_mule_col and "fraudScenario" in self.df.columns and has_ratio_col:
            mule_mask = self.df["is_mule_candidate"].astype(bool)
            smurfing_mule = self.df[mule_mask & (self.df["fraudScenario"] == "SMURFING")]
            other_mule    = self.df[mule_mask & (self.df["fraudScenario"] != "SMURFING")]

            ratios_s = smurfing_mule["delta_commission_ratio"].dropna()
            ratios_o = other_mule["delta_commission_ratio"].dropna()

            if len(ratios_s) > 0:
                fig.add_trace(go.Histogram(
                    x=ratios_s, nbinsx=40, name="Mule SMURFING",
                    marker_color="#F59E0B", opacity=0.85))
            if len(ratios_o) > 0:
                fig.add_trace(go.Histogram(
                    x=ratios_o, nbinsx=40, name="Mule candidate (légitime apparent)",
                    marker_color="#3B82F6", opacity=0.6))
        else:
            if len(ratio_src) > 0:
                fig.add_trace(go.Histogram(x=ratio_src, nbinsx=40, marker_color="#F59E0B"))

        if len(ratio_src) == 0:
            fig.add_annotation(
                text="Aucun compte mule détecté (delta_commission_ratio non calculé)",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(color="#94A3B8", size=13))

        fig.add_vline(x=0.10, line_dash="dash", line_color="#EF4444",
                      annotation_text="seuil 10% (Zhdanova et al.)",
                      annotation_font_color="#EF4444")
        fig.update_layout(
            title="Distribution de la commission mule observée (Smurfing — critère Zhdanova et al.)",
            xaxis_title="δ = (montant_reçu − montant_envoyé) / montant_reçu",
            yaxis_title="Fréquence",
            barmode="overlay",
            height=420, **self._dark_layout())
        return fig
