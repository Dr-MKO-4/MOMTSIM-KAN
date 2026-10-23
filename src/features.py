"""
features.py  Ingénierie des caractéristiques transactionnelles
(section 3.4 du mémoire), calculées à partir du journal brut.

Implémentation entièrement vectorisée : les comptes, les types d'action et les
couples de comptes sont codés en entiers une seule fois, chaque caractéristique
est calculée sur des tableaux NumPy dans l'ordre (compte, pas) obtenu par un tri
stable, puis replacée dans l'ordre du journal. Aucune boucle Python par compte ni
par groupe ; mémoire bornée (pas de copie triée du DataFrame par caractéristique).
Les définitions sont celles de dashboard/stream_features.py (calcul en flux).
"""

import numpy as np
import pandas as pd


def _as_key(values: np.ndarray) -> np.ndarray:
    """Identifiants de compte en int64 s'ils sont entiers (merge_asof n'accepte
    pas une clé `by` en int32), inchangés sinon (identifiants texte du flux live)."""
    return values.astype(np.int64) if np.issubdtype(values.dtype, np.integer) else values


def _group_ids(*sorted_keys: np.ndarray) -> np.ndarray:
    """Identifiant de groupe croissant pour des lignes triées selon `sorted_keys`."""
    n = len(sorted_keys[0])
    change = np.zeros(n, dtype=bool)
    if n:
        change[0] = True
    for k in sorted_keys:
        change[1:] |= k[1:] != k[:-1]
    return np.cumsum(change) - 1


class FeatureEngineer:
    """
    Calcule, pour chaque transaction du rawLog, l'ensemble des features
    dérivées formalisées en section 3.4 :
    ΔBorig, ΔBdest, r1, r2, Flag_anomalie, δ_commission, Var_agent,
    ρ_rupture, ρ_refund, V1h, Flag_nuit, ρ_nouveau.
    """

    WINDOW_30J = 30 * 24
    WINDOW_90J = 90 * 24
    ANOMALY_WINDOW = 10

    def __init__(self, df: pd.DataFrame, eps: float = 1e-6, mule_tolerance_steps: int = 48):
        # Tri stable : à l'intérieur d'un pas, l'ordre du journal est conservé
        self.df = df.sort_values(["step"], kind="mergesort").reset_index(drop=True)
        self.eps = eps
        # Tolérance temporelle pour l'appariement mule (smurfing), en steps (1 step = 1h).
        # 48 couvre largement le délai de relais mule -> récepteur du simulateur
        # (delay_mule_max_hours = 12 dans fraudScenariosConfig.json).
        self.mule_tolerance_steps = mule_tolerance_steps

    #
    def compute_all(self) -> pd.DataFrame:
        df = self.df
        self._encode(df)
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
        # Ordre de sortie : par compte émetteur puis par pas (comme précédemment)
        df = df.iloc[self._order_acct].reset_index(drop=True)
        self.df = df
        return df

    # ── codage entier des clés et ordre (compte, pas) ────────────────────────
    def _encode(self, df: pd.DataFrame) -> None:
        n = len(df)
        orig = df["nameOrig"].values
        dest = df["nameDest"].values
        # Espace de codes commun aux émetteurs et destinataires, ordonné comme les valeurs
        codes, uniques = pd.factorize(np.concatenate([orig, dest]), sort=True)
        self._orig = codes[:n].astype(np.int64)
        self._dest = codes[n:].astype(np.int64)
        self._n_acc = max(len(uniques), 1)
        self._action, _ = pd.factorize(df["action"].values, sort=True)
        self._step = df["step"].values.astype(np.int64)
        self._amount = df["amount"].values.astype(np.float64)
        self._max_step = int(self._step.max()) if n else 0
        # Ordre (compte émetteur, pas), stable
        self._order_acct = np.lexsort((self._step, self._orig))
        self._gid_acct = _group_ids(self._orig[self._order_acct])
        # Clé (groupe, pas) croissante dans cet ordre : fenêtres glissantes par searchsorted
        self._big = self._max_step + 2 * self.WINDOW_90J + 10
        self._key_acct = self._gid_acct * self._big + self._step[self._order_acct]

    def _windowed_sum(self, values_sorted: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        """Somme de `values_sorted` (ordre compte-pas) sur les pas [lo, hi) du même
        compte, pour chaque ligne. O(n log n), une seule passe sur tout le journal."""
        cs = np.concatenate([[0.0], np.cumsum(values_sorted, dtype=np.float64)])
        g = self._gid_acct * self._big
        i_lo = np.searchsorted(self._key_acct, g + lo, side="left")
        i_hi = np.searchsorted(self._key_acct, g + hi, side="left")
        return cs[i_hi] - cs[i_lo]

    def _scatter(self, values_sorted: np.ndarray) -> np.ndarray:
        """Replace des valeurs calculées dans l'ordre compte-pas à l'ordre du journal."""
        out = np.empty_like(values_sorted)
        out[self._order_acct] = values_sorted
        return out

    #
    # ΔBorig, ΔBdest  éq. 3.4 (section 3.4.1)
    #
    def _delta_balances(self, df: pd.DataFrame) -> pd.DataFrame:
        df["delta_B_orig"] = df["oldBalanceOrig"] - df["newBalanceOrig"]
        df["delta_B_dest"] = df["newBalanceDest"] - df["oldBalanceDest"]
        return df

    #
    # r1, r2 (feature clé ATO)
    #
    def _ratios_r1_r2(self, df: pd.DataFrame) -> pd.DataFrame:
        df["r1"] = df["amount"] / (df["oldBalanceOrig"] + self.eps)
        df["r2"] = df["amount"] / (df["newBalanceOrig"] + self.eps)
        df["r1_r2_product"] = df["r1"] * df["r2"]  # exploitable par un nœud MultKAN
        return df

    #
    # Flag_anomalie : 10 opérations précédentes du même compte ET du même type,
    # transaction courante exclue, au moins deux observations, écart-type ddof = 1
    #
    def _flag_anomalie(self, df: pd.DataFrame) -> pd.DataFrame:
        order = np.lexsort((self._step, self._action, self._orig))
        gid = _group_ids(self._orig[order], self._action[order])
        x = self._amount[order]
        n = len(x)
        s = np.zeros(n)
        c = np.zeros(n)
        valid_lags = []
        for lag in range(1, min(self.ANOMALY_WINDOW, max(n - 1, 0)) + 1):
            same = gid[lag:] == gid[:-lag]
            valid_lags.append((lag, same))
            s[lag:] += np.where(same, x[:-lag], 0.0)
            c[lag:] += same
        mean = np.divide(s, c, out=np.zeros(n), where=c > 0)
        # Seconde passe (écarts à la moyenne) : même calcul que le flux, sans perte de précision
        ss = np.zeros(n)
        for lag, same in valid_lags:
            d = x[:-lag] - mean[lag:]
            ss[lag:] += np.where(same, d * d, 0.0)
        std = np.sqrt(np.divide(ss, c - 1, out=np.zeros(n), where=c > 1))
        flag_sorted = (c >= 2) & (x > mean + 2.0 * std)
        flag = np.empty(n, dtype=bool)
        flag[order] = flag_sorted
        df["flag_anomalie"] = flag
        return df

    #
    # Flag_nuit
    #
    def _flag_nuit(self, df: pd.DataFrame) -> pd.DataFrame:
        hour_of_day = df["step"] % 24
        df["flag_nuit"] = ((hour_of_day >= 22) | (hour_of_day < 6))
        return df

    #
    # V1h : nombre de tx du compte émetteur dans le pas courant (1 step = 1h)
    #
    def _velocity_1h(self, df: pd.DataFrame) -> pd.DataFrame:
        key = self._orig * (self._max_step + 1) + self._step
        _, inv, counts = np.unique(key, return_inverse=True, return_counts=True)
        df["v1h"] = counts[inv].astype(np.int64)
        return df

    #
    # δ_commission, feature Smurfing
    # Calcul CAUSAL, au niveau de la transaction : chaque TRANSFER sortant d'un
    # compte est apparié au TRANSFER entrant le plus récent sur ce même compte,
    # reçu à un step STRICTEMENT antérieur et au plus mule_tolerance_steps avant.
    # La valeur n'est portée que par la ligne sortante appariée (NaN ailleurs).
    #
    def _delta_commission_smurfing(self, df: pd.DataFrame) -> pd.DataFrame:
        n = len(df)
        delta_col = np.full(n, np.nan)
        ratio_col = np.full(n, np.nan)
        mule_col = np.zeros(n, dtype=bool)

        is_transfer = df["action"].values == "TRANSFER"
        if is_transfer.any():
            rows = np.flatnonzero(is_transfer)
            out_tx = pd.DataFrame({
                "row": rows,
                "account": self._orig[rows],
                # int64 : merge_asof refuse une clé int32 avec une tolérance entière
                "step_out": self._step[rows],
                "amount_out": self._amount[rows],
            }).sort_values("step_out", kind="mergesort")
            # Tri (step, montant) : à égalité de step, merge_asof retient la dernière
            # ligne, soit le plus gros montant reçu -- règle déterministe partagée avec
            # dashboard/stream_features.py (l'ordre intra-step n'est pas connu).
            in_tx = pd.DataFrame({
                "account": self._dest[rows],
                "step_in": self._step[rows],
                "amount_in": self._amount[rows],
            }).sort_values(["step_in", "amount_in"], kind="mergesort")

            # allow_exact_matches=False : l'ordre des transactions à l'intérieur d'un
            # step (1 h) n'est pas connu, une entrée du même step ne peut donc pas être
            # tenue pour antérieure. Le relais mule -> récepteur du simulateur est
            # différé d'au moins 1 step (delay_mule_min_hours), il n'est pas perdu.
            merged = pd.merge_asof(
                out_tx, in_tx, left_on="step_out", right_on="step_in", by="account",
                direction="backward", tolerance=self.mule_tolerance_steps,
                allow_exact_matches=False)
            matched = merged[merged["amount_in"].notna()]
            if not matched.empty:
                delta = matched["amount_in"].values - matched["amount_out"].values
                ratio = delta / (matched["amount_in"].values + self.eps)
                r = matched["row"].values
                delta_col[r] = delta
                ratio_col[r] = ratio
                # Critère 1 de Zhdanova et al. : 0 < δ ≤ 10% du montant reçu
                mule_col[r] = (ratio > 0) & (ratio <= 0.10)

        df["delta_commission"] = delta_col
        df["delta_commission_ratio"] = ratio_col
        df["is_mule_candidate"] = mule_col
        return df

    #
    # Var_agent, Split Deposit : variance (ddof = 0) des CASH_IN d'un même couple
    # (agent, client) au même step, portée par toutes les lignes de ce couple et de
    # ce step (même convention que la version précédente par jointure)
    #
    def _var_agent_split_deposit(self, df: pd.DataFrame) -> pd.DataFrame:
        n = len(df)
        var_col = np.full(n, np.nan)
        k_col = np.zeros(n, dtype=np.int64)
        is_ci = df["action"].values == "CASH_IN"
        if is_ci.any():
            key = (self._orig * self._n_acc + self._dest) * (self._max_step + 1) + self._step
            kc = key[is_ci]
            x = self._amount[is_ci]
            uk, inv, cnt = np.unique(kc, return_inverse=True, return_counts=True)
            mean = np.bincount(inv, weights=x) / cnt
            var = np.bincount(inv, weights=(x - mean[inv]) ** 2) / cnt     # deux passes
            pos = np.searchsorted(uk, key)
            pos_c = np.minimum(pos, len(uk) - 1)
            hit = uk[pos_c] == key
            var_col[hit] = var[pos_c[hit]]
            k_col[hit] = cnt[pos_c[hit]]
        df["var_agent_split"] = var_col
        df["k_fragments"] = k_col
        return df

    #
    # ρ_rupture, Fake Credentials : moyenne des montants du compte sur les 30 jours
    # précédant le pas courant (pas courant exclu)
    #
    def _rho_rupture_fake_cred(self, df: pd.DataFrame) -> pd.DataFrame:
        steps = self._step[self._order_acct]
        amounts = self._amount[self._order_acct]
        lo, hi = steps - self.WINDOW_30J, steps
        sums = self._windowed_sum(amounts, lo, hi)
        counts = self._windowed_sum(np.ones_like(amounts), lo, hi)
        means = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
        mean_hist = self._scatter(means)
        df["mean_historique_30j"] = mean_hist
        df["rho_rupture"] = df["amount"] / (np.nan_to_num(mean_hist, nan=0.0) + self.eps)
        return df

    #
    # ρ_refund, fenêtre glissante 30j, pas courant inclus
    # Remboursements REÇUS par le compte / paiements ÉMIS par le compte.
    # Un REFUND est émis par le marchand (nameOrig = marchand, nameDest = client
    # remboursé) : il est compté du côté du compte qui le reçoit.
    #
    def _rho_refund(self, df: pd.DataFrame) -> pd.DataFrame:
        order = self._order_acct
        steps = self._step[order]
        is_payment = (df["action"].values[order] == "PAYMENT").astype(np.float64)
        lo, hi = steps - self.WINDOW_30J, steps + 1
        n_payment = self._windowed_sum(is_payment, lo, hi)

        # Codes des comptes émetteurs (ordre croissant) -> identifiant de groupe
        emitters = self._orig[order]
        first = np.concatenate([[True], emitters[1:] != emitters[:-1]]) if len(emitters) else np.zeros(0, bool)
        emitter_codes = emitters[first]                       # croissant, indice = gid
        is_refund = df["action"].values == "REFUND"
        r_dest = self._dest[is_refund]
        r_step = self._step[is_refund]
        g = np.searchsorted(emitter_codes, r_dest)
        g_c = np.minimum(g, max(len(emitter_codes) - 1, 0))
        known = (len(emitter_codes) > 0) & (emitter_codes[g_c] == r_dest) if len(r_dest) else np.zeros(0, bool)
        rkeys = np.sort(g_c[known] * self._big + r_step[known])
        gk = self._gid_acct * self._big
        n_refund = (np.searchsorted(rkeys, gk + hi, side="left")
                    - np.searchsorted(rkeys, gk + lo, side="left"))
        df["rho_refund"] = self._scatter(n_refund / (n_payment + self.eps))
        return df

    #
    # ρ_nouveau : part de destinataires sans contact du couple dans les 90 jours
    # précédents, sur les transactions des 30 derniers jours (pas courant inclus)
    #
    def _rho_nouveau(self, df: pd.DataFrame) -> pd.DataFrame:
        order = self._order_acct
        n = len(order)
        steps = self._step[order]
        pair = self._orig[order] * self._n_acc + self._dest[order]
        # Dernier contact du même couple avant la transaction (ordre compte-pas)
        pos = np.arange(n)
        o2 = np.lexsort((pos, pair))
        pair2, steps2 = pair[o2], steps[o2]
        prev = np.full(n, -1, dtype=np.int64)
        same = pair2[1:] == pair2[:-1]
        prev_sorted = np.where(same, steps2[:-1], -1)
        prev[o2[1:]] = prev_sorted
        is_new = ((prev < 0) | ((steps - prev) > self.WINDOW_90J)).astype(np.float64)

        lo, hi = steps - self.WINDOW_30J, steps + 1
        sums = self._windowed_sum(is_new, lo, hi)
        counts = self._windowed_sum(np.ones(n), lo, hi)
        df["rho_nouveau"] = self._scatter(sums / np.maximum(counts, 1))
        return df


if __name__ == "__main__":
    from pathlib import Path as _Path
    _root = _Path(__file__).parent.parent

    df_raw = pd.read_parquet(str(_root / "config" / "rawLog_torch.parquet"))
    engineer = FeatureEngineer(df_raw)
    df_features = engineer.compute_all()
    df_features.to_parquet(str(_root / "config" / "featuresLog.parquet"), index=False)

    print(df_features[["step", "action", "amount", "r1", "r2", "flag_anomalie",
                        "flag_nuit", "v1h", "delta_commission_ratio",
                        "is_mule_candidate", "var_agent_split", "rho_rupture",
                        "rho_refund", "rho_nouveau"]].tail(20))
