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

# Indicatrices binaires (valeurs {0, 1}) exclues du test KS et du calcul de couverture
# de grille B-spline. Une variable à deux points de masse ne peut pas ressembler à une
# loi normale continue : D_KS serait systématiquement élevé par construction, ce qui
# fausserait ks_mean (critère de la règle éq. 4.7) et features_needing_transform.
# log1p n'a pas de sens sur un booléen — ces features sont transmises telles quelles
# au pipeline KAN (section 4.1.4 du mémoire).
BINARY_FEATURES = ["flag_nuit", "flag_anomalie"]


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
            # Les indicatrices binaires sont exclues : D_KS serait artificiellement élevé
            # (deux points de masse, pas de distribution continue approximable par B-splines).
            if feat in BINARY_FEATURES:
                continue
            col = self.X_norm[:, j]
            sample = col if len(col) <= 5000 else np.random.choice(col, 5000, replace=False)
            ks_results[feat] = self._ks_statistic_vs_normal(sample)
        self.report["ks_per_feature"] = ks_results
        # ks_mean calculé sur les features continues uniquement (éq. 4.7 du mémoire)
        self.report["ks_mean"] = float(np.mean(list(ks_results.values()))) if ks_results else 0.0
        self.report["features_needing_transform"] = [f for f, d in ks_results.items() if d >= 0.15]
        return ks_results

    # eq. 4.6 — couverture de la grille sur [-3, 3]
    # HYPOTHÈSE PROVISOIRE : les bornes [-3, 3] supposent une normalisation z-score standard
    # (convention post-normalisation éq. 4.1, ~99,7 % de la masse gaussienne théorique).
    # Ces valeurs seront à réviser une fois l'architecture MKAN réellement définie
    # (section 4.2 du mémoire, hors périmètre Phase 1 — ne pas modifier avant cette étape).
    def grid_coverage(self, grid_min: float = -3.0, grid_max: float = 3.0) -> dict:
        if self.X_norm is None:
            self.normalize()
        coverage = {}
        for j, feat in enumerate(self.features):
            # Les indicatrices binaires sont exclues : une grille B-spline sur [-3, 3]
            # n'a pas de sens pour une variable à deux points de masse {0, 1}.
            if feat in BINARY_FEATURES:
                continue
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

    def run_full_validation_with_retry(self, max_retries: int = 1) -> dict:
        """
        Exécute run_full_validation() et, si la décision est "Transformations requises"
        (éq. 4.7), applique apply_recommended_transforms(), reconstruit un TopologyValidator
        sur les données transformées et relance la validation complète (section 4.1.5).
        Borné à max_retries pour éviter une boucle infinie si D_KS reste positif après
        transformation. L'état interne de self est mis à jour pour refléter le run final,
        ce qui permet d'appeler plot_pca_projection() / plot_ks_summary() après.
        """
        report = self.run_full_validation()
        transform_applied = None
        retries = 0

        while report.get("decision") == "Transformations requises" and retries < max_retries:
            df_transformed = self.apply_recommended_transforms()
            transform_applied = list(report.get("features_needing_transform", []))
            retry_val = TopologyValidator(df_transformed, features=self.features, eps=self.eps)
            report = retry_val.run_full_validation()
            # Mettre à jour self pour que plot_*() reflète l'état post-transformation
            self.df = retry_val.df
            self.mu = retry_val.mu
            self.sigma = retry_val.sigma
            self.X_norm = retry_val.X_norm
            self.V = retry_val.V
            self.singular_values = retry_val.singular_values
            self.Z = retry_val.Z
            self.report = retry_val.report
            retries += 1

        report["transform_applied"] = transform_applied
        if retries >= max_retries and report.get("decision") == "Transformations requises":
            report["transform_warning"] = (
                f"Après {max_retries} transformation(s), le test KS reste positif. "
                "Décision retournée en l'état — vérification manuelle requise avant "
                "transmission au pipeline KAN."
            )
        self.report = report
        return report

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
    def __init__(self, df_features: pd.DataFrame, df_target_agg: pd.DataFrame = None,
                 injector_tracking: dict = None):
        self.df = df_features
        self.df_target = df_target_agg
        self.tracking = injector_tracking or {}

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

    # ── A1 : NRMSE heatmap ──────────────────────────────────────────────────
    def plot_nrmse_heatmap(self) -> go.Figure:
        """Heatmap NRMSE pour toutes les actions × estimateurs (count, avg, std)."""
        if self.df_target is None:
            raise ValueError("df_target_agg requis pour le NRMSE heatmap")

        actions = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER", "DEPOSIT"]
        estimators = ["count", "avg_amount", "std_amount"]
        z = np.full((len(estimators), len(actions)), float("nan"))

        for j, action in enumerate(actions):
            sim_sub  = self.df[self.df["action"] == action]
            tgt_sub  = self.df_target[self.df_target["action"] == action]

            # count par step
            sim_cnt = sim_sub.groupby("step").size().reindex(range(720), fill_value=0).values
            tgt_cnt = tgt_sub.set_index("step")["count"].reindex(range(720), fill_value=0).values if "count" in tgt_sub.columns else np.zeros(720)

            for i, est in enumerate(estimators):
                if est == "count":
                    sim_v, tgt_v = sim_cnt, tgt_cnt
                elif est == "avg_amount":
                    sim_v = sim_sub.groupby("step")["amount"].mean().reindex(range(720), fill_value=0).values
                    tgt_v = tgt_sub.set_index("step")["avg_amount"].reindex(range(720), fill_value=0).values if "avg_amount" in tgt_sub.columns else np.zeros(720)
                else:  # std_amount
                    sim_v = sim_sub.groupby("step")["amount"].std().reindex(range(720), fill_value=0).fillna(0).values
                    tgt_v = tgt_sub.set_index("step")["std_amount"].reindex(range(720), fill_value=0).values if "std_amount" in tgt_sub.columns else np.zeros(720)

                rmse = np.sqrt(np.mean((sim_v - tgt_v) ** 2))
                span = tgt_v.max() - tgt_v.min()
                z[i, j] = rmse / span if span > 1e-9 else 0.0

        fig = go.Figure(data=go.Heatmap(
            z=z, x=actions, y=estimators,
            colorscale="RdYlGn_r",
            zmin=0, zmax=1,
            text=[[f"{v:.3f}" for v in row] for row in z],
            texttemplate="%{text}",
            colorbar=dict(title="NRMSE")))
        fig.update_layout(
            title="NRMSE par action × estimateur — validation SSE (section 3.1.3)",
            xaxis_title="Action", yaxis_title="Estimateur",
            height=320, **self._dark_layout())
        return fig

    # ── A2 : Conformité par scénario ────────────────────────────────────────

    def plot_ato_exfiltration_window(self) -> go.Figure:
        """Montant exfiltré par step — fenêtre d'exfiltration ATO (§3.2.1)."""
        ato = self.df[(self.df.get("fraudScenario", pd.Series()) == "ATO") &
                      (self.df["action"] == "TRANSFER")] if "fraudScenario" in self.df.columns else pd.DataFrame()

        # Fallback: use tracking
        tracking_ato = self.tracking.get("ato", [])

        fig = go.Figure()
        if len(ato) > 0:
            by_step = ato.groupby("step")["amount"].sum().reset_index()
            fig.add_trace(go.Bar(
                x=by_step["step"], y=by_step["amount"],
                name="Montant exfiltré", marker_color="#EF4444", opacity=0.8))
        elif tracking_ato:
            steps   = [e["step"] for e in tracking_ato]
            amounts = [e["total_amount"] for e in tracking_ato]
            fig.add_trace(go.Bar(x=steps, y=amounts, name="Montant exfiltré",
                                 marker_color="#EF4444", opacity=0.8))
        else:
            fig.add_annotation(text="Aucune opération ATO détectée",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))

        fig.update_layout(
            title="Fenêtre d'exfiltration ATO — montants TRANSFER par step (§3.2.1)",
            xaxis_title="Step (heure)", yaxis_title="Montant exfiltré (FCFA)",
            height=380, **self._dark_layout())
        return fig

    def plot_refund_delay_distribution(self) -> go.Figure:
        """Distribution des délais PAYMENT→REFUND en heures (§3.2.2)."""
        delays = [e["delay_hours"] for e in self.tracking.get("refund", [])]

        fig = go.Figure()
        if delays:
            fig.add_trace(go.Histogram(
                x=delays, nbinsx=30, marker_color="#3B82F6", opacity=0.85,
                name="Délai (h)"))
            mean_d = float(np.mean(delays))
            fig.add_vline(x=mean_d, line_dash="dash", line_color="#F59E0B",
                          annotation_text=f"μ = {mean_d:.1f} h",
                          annotation_font_color="#F59E0B")
        else:
            fig.add_annotation(text="Aucune opération REFUND tracée",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))

        fig.update_layout(
            title="Distribution des délais PAYMENT → REFUND — Δt ~ U(delay_min, delay_max) (§3.2.2)",
            xaxis_title="Délai (heures)", yaxis_title="Fréquence",
            height=380, **self._dark_layout())
        return fig

    def plot_fake_credentials_dormance(self) -> go.Figure:
        """Distribution des périodes de dormance FAKE_CRED (§3.2.3)."""
        dormances = [e["dormance_hours"] for e in self.tracking.get("fake_credentials", [])]

        fig = go.Figure()
        if dormances:
            fig.add_trace(go.Histogram(
                x=dormances, nbinsx=20, marker_color="#22C55E", opacity=0.85,
                name="Dormance (h)"))
        else:
            fig.add_annotation(text="Aucun agent FAKE_CRED activé",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))

        fig.update_layout(
            title="Périodes de dormance — Fake Credentials (§3.2.3, dormance ∈ [min, max] jours)",
            xaxis_title="Dormance (heures)", yaxis_title="Fréquence",
            height=380, **self._dark_layout())
        return fig

    def plot_split_deposit_variance(self) -> go.Figure:
        """Variance intra-opération des fragments SPLIT_DEP (§3.2.4, éq. 3.14)."""
        events = self.tracking.get("split_deposit", [])
        variances = []
        for ev in events:
            frags = ev.get("fragments", [])
            if len(frags) >= 2:
                variances.append(float(np.var(frags)))

        if not variances:
            # Fallback: compute from rawLog
            if "fraudScenario" in self.df.columns:
                split_df = self.df[(self.df["fraudScenario"] == "SPLIT_DEP") &
                                   (self.df["action"] == "CASH_IN")]
                if len(split_df) > 0:
                    variances = split_df.groupby(["step", "nameOrig"])["amount"].var().dropna().tolist()

        fig = go.Figure()
        if variances:
            fig.add_trace(go.Histogram(
                x=variances, nbinsx=25, marker_color="#A78BFA", opacity=0.85,
                name="Variance fragments"))
        else:
            fig.add_annotation(text="Aucune opération Split Deposit détectée",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))

        fig.update_layout(
            title="Variance intra-opération des fragments — Split Deposit (§3.2.4, éq. 3.14)",
            xaxis_title="Variance des montants par opération", yaxis_title="Fréquence",
            height=380, **self._dark_layout())
        return fig

    def plot_smurfing_periodicity(self) -> go.Figure:
        """Distribution des intervalles inter-opérations Smurfing (§3.2.5)."""
        events = self.tracking.get("smurfing", [])

        fig = go.Figure()
        if len(events) >= 2:
            by_emitter: dict = {}
            for ev in events:
                by_emitter.setdefault(ev["emitter"], []).append(ev["step"])
            intervals = []
            for steps in by_emitter.values():
                steps_sorted = sorted(steps)
                for i in range(1, len(steps_sorted)):
                    intervals.append(steps_sorted[i] - steps_sorted[i - 1])

            if intervals:
                fig.add_trace(go.Histogram(
                    x=intervals, nbinsx=20, marker_color="#F59E0B", opacity=0.85,
                    name="Intervalle (steps)"))
                mean_i = float(np.mean(intervals))
                fig.add_vline(x=mean_i, line_dash="dash", line_color="#EF4444",
                              annotation_text=f"μ = {mean_i:.0f} h",
                              annotation_font_color="#EF4444")
            else:
                fig.add_annotation(text="Un seul event par émetteur — pas d'intervalle calculable",
                                   xref="paper", yref="paper", x=0.5, y=0.5,
                                   showarrow=False, font=dict(color="#94A3B8"))
        else:
            fig.add_annotation(text="Moins de 2 opérations Smurfing — intervalles non calculables",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))

        fig.update_layout(
            title="Périodicité des opérations Smurfing — intervalles inter-op (§3.2.5)",
            xaxis_title="Intervalle (heures/steps)", yaxis_title="Fréquence",
            height=380, **self._dark_layout())
        return fig

    # ── A3 : Smurfing Sankey ────────────────────────────────────────────────

    def plot_smurfing_sankey(self) -> go.Figure:
        """Réseau Smurfing sous forme de Sankey (émetteur→mule→récepteur)."""
        if "fraudScenario" not in self.df.columns:
            fig = go.Figure()
            fig.add_annotation(text="fraudScenario absent du dataset",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))
            return fig

        s_df = self.df[self.df["fraudScenario"] == "SMURFING"]
        if s_df.empty:
            fig = go.Figure()
            fig.add_annotation(text="Aucune transaction SMURFING dans le dataset",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))
            return fig

        # Déterminer qui sont les mules (nameOrig apparaît aussi comme nameDest dans SMURFING)
        orig_set = set(s_df["nameOrig"].unique())
        dest_set = set(s_df["nameDest"].unique())
        mule_ids = orig_set & dest_set   # mules = reçoivent ET envoient
        emitter_ids = orig_set - mule_ids
        receiver_ids = dest_set - mule_ids

        # Limiter à 8 emitters, 20 mules, 8 receivers pour la lisibilité
        emitters  = sorted(emitter_ids)[:8]
        mules     = sorted(mule_ids)[:20]
        receivers = sorted(receiver_ids)[:8]

        all_nodes  = emitters + mules + receivers
        node_index = {n: i for i, n in enumerate(all_nodes)}
        node_colors = (
            ["#EF4444"] * len(emitters) +
            ["#F59E0B"] * len(mules) +
            ["#22C55E"] * len(receivers)
        )

        sources, targets, values = [], [], []

        # Émetteur → mule
        em_flows = s_df[s_df["nameOrig"].isin(emitters) & s_df["nameDest"].isin(mules)]
        for _, row in em_flows.iterrows():
            if row["nameOrig"] in node_index and row["nameDest"] in node_index:
                sources.append(node_index[row["nameOrig"]])
                targets.append(node_index[row["nameDest"]])
                values.append(float(row["amount"]))

        # Mule → récepteur
        mr_flows = s_df[s_df["nameOrig"].isin(mules) & s_df["nameDest"].isin(receivers)]
        for _, row in mr_flows.iterrows():
            if row["nameOrig"] in node_index and row["nameDest"] in node_index:
                sources.append(node_index[row["nameOrig"]])
                targets.append(node_index[row["nameDest"]])
                values.append(float(row["amount"]))

        if not sources:
            fig = go.Figure()
            fig.add_annotation(text="Pas assez de flux SMURFING à afficher",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))
            return fig

        fig = go.Figure(data=[go.Sankey(
            arrangement="snap",
            node=dict(
                label=[f"E-{n}" if n in emitters else
                       f"M-{n}" if n in mules else
                       f"R-{n}" for n in all_nodes],
                color=node_colors,
                pad=15, thickness=20,
            ),
            link=dict(
                source=sources, target=targets, value=values,
                color="rgba(245,158,11,0.3)",
            )
        )])
        fig.update_layout(
            title="Réseau Smurfing — flux émetteur→mule→récepteur (§3.2.5, Zhdanova et al.)",
            height=500, **self._dark_layout())
        return fig

    # ── B3 : Fraudster summary ──────────────────────────────────────────────

    def plot_fraudster_summary(self) -> go.Figure:
        """Vue synthétique du nombre d'opérations et montants totaux par scénario."""
        scenario_col = "fraudScenario" if "fraudScenario" in self.df.columns else None
        if scenario_col is None:
            fig = go.Figure()
            fig.add_annotation(text="fraudScenario absent du dataset",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))
            return fig

        fraud_df = self.df[self.df["isFraud"].astype(bool)]
        if fraud_df.empty:
            fig = go.Figure()
            fig.add_annotation(text="Aucune transaction frauduleuse dans le dataset",
                               xref="paper", yref="paper", x=0.5, y=0.5,
                               showarrow=False, font=dict(color="#94A3B8"))
            return fig

        grp = fraud_df.groupby(scenario_col).agg(
            n_tx=("amount", "count"),
            total_amount=("amount", "sum"),
            n_actors=("nameOrig", "nunique"),
        ).reset_index()

        colors = {"ATO": "#EF4444", "REFUND": "#3B82F6", "FAKE_CRED": "#22C55E",
                  "SPLIT_DEP": "#A78BFA", "SMURFING": "#F59E0B"}

        fig = make_subplots(rows=1, cols=2,
                            subplot_titles=["Nombre de transactions par scénario",
                                            "Montant total exfiltré (FCFA)"])
        for _, row in grp.iterrows():
            sc = row[scenario_col]
            clr = colors.get(sc, "#94A3B8")
            fig.add_trace(go.Bar(name=sc, x=[sc], y=[row["n_tx"]],
                                 marker_color=clr, showlegend=False), row=1, col=1)
            fig.add_trace(go.Bar(name=sc, x=[sc], y=[row["total_amount"]],
                                 marker_color=clr, showlegend=True), row=1, col=2)

        fig.update_layout(
            title="Synthèse par scénario — activité frauduleuse (section 3.2 du mémoire)",
            height=400, barmode="group",
            **self._dark_layout())
        return fig

    # ── A4 : Résumés en langage naturel ────────────────────────────────────

    @staticmethod
    def generate_simulation_plain_summary(result: dict) -> str:
        n = result.get("n_transactions", 0)
        rate = result.get("fraud_rate", 0.0)
        steps = result.get("steps_run", 720)
        by_sc = result.get("fraud_by_scenario", {})

        top_sc = max(by_sc, key=by_sc.get) if by_sc else "—"
        top_pct = by_sc.get(top_sc, 0.0) * 100

        lines = [
            f"La simulation a généré {n:,} transactions sur {steps} steps ({steps // 24} jours).",
            f"Le taux de fraude global est de {rate * 100:.2f} % ({int(n * rate)} transactions frauduleuses).",
        ]
        if by_sc:
            lines.append(f"Le scénario dominant est {top_sc} ({top_pct:.1f} % des fraudes).")
        if rate > 0.25:
            lines.append("⚠ Taux supérieur à 25 % — la calibration SPSA est recommandée.")
        elif rate < 0.10:
            lines.append("⚠ Taux inférieur à 10 % — augmenter les probabilités ou relancer la calibration.")
        else:
            lines.append("Taux dans la plage cible [10 %, 25 %].")
        return " ".join(lines)

    @staticmethod
    def generate_kan_plain_summary(report: dict) -> str:
        ve2 = report.get("VE2", float("nan"))
        jf  = report.get("J_Fisher", float("nan"))
        dks = report.get("ks_mean", float("nan"))
        dec = report.get("decision", "inconnu")
        k80 = report.get("k_for_VE80", "?")
        needs = report.get("features_needing_transform", [])

        lines = [
            f"Décision topologique : « {dec} ».",
            f"VE2 = {ve2:.3f} (seuil ≥ 0.40), J_Fisher = {jf:.3f} (seuil > 1), D̄_KS = {dks:.3f} (seuil < 0.15).",
            f"{k80} composantes expliquent 80 % de la variance.",
        ]
        if needs:
            lines.append(f"{len(needs)} feature(s) nécessite(nt) une transformation log(1+x) : {', '.join(needs)}.")
        if dec == "KAN valide":
            lines.append("L'architecture KAN est validée — les données peuvent être transmises au pipeline MKAN.")
        elif dec == "Transformations requises":
            lines.append("Après application de log(1+x), re-vérifier la décision.")
        else:
            lines.append("Une architecture alternative (MLP, RF) est recommandée avant de procéder.")
        return " ".join(lines)
