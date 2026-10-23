"""
calibration_report.py  Interprétation d'un résultat de calibration SSE/SPSA :
faut-il relancer, et avec quoi ?

Chaque diagnostic est calculé à partir du résultat lui-même (historique, θ0, θ*,
distribution cible Dr et distribution simulée au meilleur point). Les seuils de
décision sont des seuils de travail, signalés comme tels dans le texte.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SCEN_LABELS = ["ATO", "REFUND", "FAKE_CRED", "SPLIT_DEP", "SMURFING"]
THETA_LABELS = ["p_ATO", "p_REFUND", "p_FAKE_CRED", "p_SPLIT_DEP", "alpha_SMURFING"]
THETA_KEYS = ["ato", "refund", "fake_credentials", "split_deposit", "smurfing_freq_mult"]

# Seuils de travail
MOVE_MIN = 0.02          # déplacement relatif minimal de θ (fraction de la largeur des bornes)
GAIN_MIN = 0.05          # gain relatif minimal de SSE entre θ0 et θ*
TREND_MAX = 0.01         # gain relatif de SSE sur les 20 % dernières itérations au-delà duquel ça progresse encore
FIT_BAD = 0.5            # SSE(θ*) / SSE(sans fraude) au-delà duquel la forme de la cible n'est pas reproduite
SHARE_TOL = 0.05         # écart toléré à la part égale (20 %) par scénario
BOUND_TOL = 0.01         # proximité d'une borne (fraction de la largeur)


def _target_range(fraud_config_path) -> tuple[float, float]:
    try:
        cfg = json.loads(Path(fraud_config_path).read_text(encoding="utf-8"))
        g = cfg.get("global", {})
        return float(g.get("fraud_target_min", 0.20)), float(g.get("fraud_target_max", 0.26))
    except Exception:
        return 0.20, 0.26


def _current_fingerprint(result: dict, fraud_config_path) -> dict | None:
    try:
        from calibration_sse import file_fingerprint
        src = Path(__file__).parent
        cfg_path = Path(fraud_config_path) if fraud_config_path else None
        param_dir = Path((result.get("fingerprint") or {}).get("param_dir")
                         or src.parent / "config" / "paramFiles")
        return {"fraud_config": file_fingerprint([cfg_path]) if cfg_path else None,
                "param_files": file_fingerprint([param_dir]),
                "engine": file_fingerprint([src / "momtsim_torch.py"])}
    except Exception:
        return None


def interpret_calibration(result: dict, fraud_config_path=None,
                          check_staleness: bool = True) -> dict:
    """Retourne {verdict, converged, summary, checks[], metrics{}, next_steps[]}."""
    checks: list[dict] = []

    def add(level, title, detail, action=None):
        checks.append({"level": level, "title": title, "detail": detail, "action": action})

    cfg = result.get("config", {})
    lo_t, hi_t = _target_range(fraud_config_path) if fraud_config_path else (0.20, 0.26)
    target_mid = float(cfg.get("target_mid", 0.23))
    history = [h for h in result.get("history", []) if h.get("sse") is not None]
    lo_b = np.array(result.get("bounds_lo", [0.02, 0.02, 1e-4, 0.02, 0.5]))
    hi_b = np.array(result.get("bounds_hi", [0.5, 0.5, 0.3, 0.5, 10.0]))
    width = hi_b - lo_b
    theta_star = np.array([result["probas"][k] for k in THETA_KEYS])
    theta0 = np.array(result.get("theta0") or theta_star)
    sse_star = result.get("sse_final")
    sse0 = result.get("sse_theta0")
    sse_zero = result.get("sse_zero_fraud")
    best = result.get("best_eval") or {}
    metrics: dict = {"target_range": [lo_t, hi_t], "n_iterations": len(history),
                     "sse_star": sse_star, "sse_theta0": sse0, "sse_zero_fraud": sse_zero}

    # 0. Interruption
    if result.get("cancelled"):
        add("bloquant", "Calibration interrompue",
            f"Seules {len(history)} itérations ont été évaluées sur {cfg.get('maxiter', '?')}.",
            "Relancer avec --reprendre pour continuer depuis le dernier point de reprise.")

    # 1. Données ou code modifiés depuis la calibration
    if check_staleness and fraud_config_path:
        now = _current_fingerprint(result, fraud_config_path)
        old = result.get("fingerprint")
        if now and old:
            changed = [name for key, name in (("fraud_config", "fraudScenariosConfig.json"),
                                              ("param_files", "paramFiles/*.csv"),
                                              ("engine", "momtsim_torch.py"))
                       if old.get(key) and now.get(key) and old[key] != now[key]]
            if changed:
                add("bloquant", "Entrées modifiées depuis la calibration",
                    "Fichiers changés depuis ce run : " + ", ".join(changed) + ". "
                    "Le theta* obtenu ne correspond plus au simulateur actuel.",
                    "Relancer la calibration.")
        elif not old:
            add("attention", "Empreinte des entrées absente",
                "Ce résultat a été produit avant l'ajout des empreintes : impossible de vérifier "
                "qu'il correspond aux fichiers et au code actuels.",
                "Relancer la calibration pour obtenir un résultat traçable.")

    if not best:
        add("bloquant", "Rapport d'une ancienne version de la calibration",
            "Il ne contient ni la distribution simulée au meilleur point, ni le point de départ : "
            "le taux de fraude obtenu, la forme temporelle et le déplacement de theta ne sont pas "
            "évaluables.",
            "Relancer la calibration avec la version actuelle.")

    # 2. Taux de fraude réalisé au meilleur point
    fr = best.get("fraud_rate")
    n_mules = cfg.get("n_mules")
    if fr is not None:
        metrics["fraud_rate_star"] = fr
        if not (lo_t <= fr <= hi_t):
            odds_t, odds = target_mid / (1 - target_mid), fr / max(1e-9, 1 - fr)
            sugg = int(round(n_mules * odds_t / odds)) if n_mules and odds > 0 else None
            add("bloquant", "Taux de fraude hors de la fourchette cible",
                f"Taux de fraude simulé à theta* : {fr:.1%} (fourchette {lo_t:.0%} à {hi_t:.0%}).",
                (f"Ajuster n_mules : estimation au premier ordre {sugg} au lieu de {n_mules} "
                 f"(ATO, Refund, Split Deposit et le nombre de réseaux de smurfing sont "
                 f"proportionnels au nombre de mules), puis relancer." if sugg else
                 "Ajuster n_mules puis relancer."))
        else:
            add("ok", "Taux de fraude dans la fourchette",
                f"Taux de fraude simulé à theta* : {fr:.1%} (fourchette {lo_t:.0%} à {hi_t:.0%}).")

    # 3. Progression encore en cours ?
    still_improving = False
    if len(history) >= 3:
        bests = np.minimum.accumulate([h["sse"] for h in history])
        i80 = max(0, int(np.floor(0.8 * (len(bests) - 1))))
        trend = (bests[i80] - bests[-1]) / bests[i80] if bests[i80] > 0 else 0.0
        metrics["sse_gain_last_20pct"] = float(trend)
        still_improving = trend > TREND_MAX
        if still_improving:
            add("bloquant", "La SSE diminue encore en fin de calibration",
                f"Gain de {trend:.1%} sur les 20 % dernières itérations "
                f"(seuil de travail {TREND_MAX:.0%}).",
                "Relancer en partant de theta* (option --depuis-theta-etoile) avec plus d'itérations.")
    converged = (not result.get("cancelled")) and len(history) >= 3 and not still_improving

    # 4. θ a-t-il bougé ?
    rel_move = np.abs(theta_star - theta0) / width
    metrics["theta_rel_move"] = rel_move.tolist()
    gain0 = (sse0 - sse_star) / sse0 if sse0 and sse_star is not None and sse0 > 0 else None
    metrics["sse_gain_vs_theta0"] = gain0
    if gain0 is not None and gain0 < GAIN_MIN:
        grads = np.array([h["grad"] for h in result.get("history", []) if h.get("grad")])
        lr = cfg.get("lr")
        detail = (f"Déplacement maximal de theta : {rel_move.max():.1%} de la largeur des bornes ; "
                  f"gain de SSE par rapport au départ analytique : {gain0:.1%}. "
                  "SPSA n'a presque rien apporté au départ analytique.")
        action = "Augmenter le pas a (lr) ou utiliser gain_schedule = spall."
        if len(grads) and lr:
            med = np.median(np.abs(grads), axis=0)
            med = np.where(med > 0, med, np.nan)
            a_sugg = float(np.nanmedian(0.05 * width / med))
            if np.isfinite(a_sugg):
                metrics["lr_suggested"] = a_sugg
                action = (f"Le gradient estimé est faible devant l'échelle de la SSE normalisée : "
                          f"un pas a d'environ {a_sugg:.3g} (au lieu de {lr}) déplacerait chaque "
                          f"paramètre d'environ 5 % de sa plage par itération. Relancer avec ce pas.")
        add("attention", "SPSA n'a presque pas amélioré theta", detail, action)

    # 5. Qualité de l'ajustement de la forme temporelle
    Ds = np.array(best.get("Ds")) if best.get("Ds") is not None else None
    Dr = np.array(result["Dr"]) if result.get("Dr") is not None else None
    if sse_star is not None and sse_zero:
        fit = sse_star / sse_zero
        metrics["fit_ratio"] = fit
        if Ds is not None and best.get("legit_bins") is not None:
            legit = np.array(best["legit_bins"])
            fbin = Ds.sum(axis=0)
            daily = np.divide(fbin, fbin + legit, out=np.zeros_like(fbin), where=(fbin + legit) > 0)
            in_range = int(((daily >= lo_t) & (daily <= hi_t)).sum())
            metrics["daily_fraud_rate"] = daily.tolist()
            metrics["daily_in_range"] = in_range
        if fit >= FIT_BAD:
            detail = (f"SSE(theta*) vaut {fit:.0%} de la SSE d'une simulation sans aucune fraude "
                      f"({sse_star:.4g} contre {sse_zero:.4g}) : la répartition dans le temps de la "
                      f"cible n'est pas reproduite.")
            action = None
            if "daily_fraud_rate" in metrics:
                d = np.array(metrics["daily_fraud_rate"])
                detail += (f" Taux de fraude par intervalle : de {d.min():.0%} à {d.max():.0%}, "
                           f"{metrics['daily_in_range']}/{len(d)} intervalles dans la fourchette.")
                if not cfg.get("volume_follow", False):
                    action = ("La cible suit le volume légitime de chaque intervalle alors que le "
                              "nombre de tirages d'injection est constant. Option : volume_follow = "
                              "true (injection proportionnelle au volume du pas, déjà utilisée par le "
                              "flux live). C'est un choix méthodologique : il doit être appliqué aussi "
                              "à la génération des jeux et décrit dans le mémoire (section 3.1.2).")
            add("attention", "Forme temporelle de la cible non reproduite", detail, action)

    # 6. Bornes et parts par scénario
    for i, name in enumerate(THETA_LABELS):
        at_lo = theta_star[i] <= lo_b[i] + BOUND_TOL * width[i]
        at_hi = theta_star[i] >= hi_b[i] - BOUND_TOL * width[i]
        if not (at_lo or at_hi):
            continue
        if i == 2 and at_hi:
            add("info", "p_FAKE_CRED à sa borne haute",
                "Saturation attendue : au plus un nouveau compte dormant par pas, réservoir de "
                "200 comptes (section 3.1.6). Son débit plafonne indépendamment de p.")
        elif at_lo:
            add("attention", f"{name} à sa borne basse",
                "Le scénario produit déjà trop de fraude à la probabilité minimale.",
                "Réduire n_mules (moins de tirages d'injection par pas).")
        else:
            add("attention", f"{name} à sa borne haute",
                "Le scénario ne produit pas assez de fraude même à la probabilité maximale.",
                "Augmenter n_mules.")

    if Ds is not None and Ds.sum() > 0:
        shares = Ds.sum(axis=1) / Ds.sum()
        metrics["scenario_shares"] = dict(zip(SCEN_LABELS, shares.tolist()))
        if Dr is not None:
            rel = np.sqrt(((Dr - Ds) ** 2).sum(axis=1)) / np.sqrt((Dr ** 2).sum(axis=1))
            metrics["scenario_rel_error"] = dict(zip(SCEN_LABELS, rel.tolist()))
            ratio = Ds.sum(axis=1) / np.maximum(Dr.sum(axis=1), 1e-9)
            metrics["scenario_volume_vs_target"] = dict(zip(SCEN_LABELS, ratio.tolist()))
            absent = [f"{SCEN_LABELS[i]} ({ratio[i]:.1%} de sa cible)" for i in range(5)
                      if i != 2 and ratio[i] < 0.10]
            if absent:
                add("bloquant", "Scénario quasi absent de la fraude simulée",
                    "Volume simulé au meilleur point : " + ", ".join(absent) + ". La probabilité de "
                    "déclenchement ne suffit pas à l'expliquer : le scénario ne se déclenche presque plus.",
                    "Vérifier la logique du scénario dans momtsim_torch.py, puis relancer la calibration.")
        off = [f"{SCEN_LABELS[i]} {shares[i]:.0%}" for i in range(5)
               if i != 2 and abs(shares[i] - 0.2) > SHARE_TOL]
        if off:
            add("attention", "Répartition entre scénarios éloignée de l'équirépartition",
                "Parts de la fraude simulée (cible 20 % chacun) : " + ", ".join(off) + ".")

    levels = [c["level"] for c in checks]
    if "bloquant" in levels:
        verdict = "RELANCER"
        summary = "Relancer : au moins un diagnostic bloquant (voir les actions proposées)."
    elif "attention" in levels:
        verdict = "ACCEPTABLE"
        summary = ("Utilisable en l'état pour générer les jeux, avec les réserves listées ; "
                   "une relance n'est utile que si l'une des actions proposées est appliquée.")
    else:
        verdict = "OK"
        summary = "Pas besoin de relancer : theta* peut être utilisé pour la génération."

    next_steps = []
    if verdict == "RELANCER":
        next_steps.append("python momtsim_cli.py calibrer")
    next_steps.append("python momtsim_cli.py generer --jeu tous")
    return {"verdict": verdict, "converged": bool(converged), "summary": summary,
            "checks": checks, "metrics": metrics, "next_steps": next_steps}


def format_report(report: dict, result: dict | None = None, width: int = 78) -> str:
    """Texte lisible en console (caractères compatibles avec la console Windows)."""
    import textwrap
    tag = {"bloquant": "[BLOQUANT]", "attention": "[ATTENTION]", "info": "[INFO]", "ok": "[OK]"}
    lines = ["=" * width, f" VERDICT : {report['verdict']}", "=" * width]
    lines += textwrap.wrap(report["summary"], width)
    if result is not None:
        lines.append("")
        lines.append("theta* :")
        for lab, key in zip(THETA_LABELS, THETA_KEYS):
            t0 = result.get("theta0")
            start = f"   (départ {t0[THETA_KEYS.index(key)]:.4f})" if t0 else ""
            lines.append(f"  {lab:<16} {result['probas'][key]:.4f}{start}")
        m = report["metrics"]
        if m.get("sse_star") is not None:
            lines.append(f"  SSE(theta*)      {m['sse_star']:.6g}")
        if m.get("sse_theta0") is not None:
            lines.append(f"  SSE(theta0)      {m['sse_theta0']:.6g}")
        if m.get("sse_zero_fraud") is not None:
            lines.append(f"  SSE sans fraude  {m['sse_zero_fraud']:.6g}   (référence)")
        if m.get("fraud_rate_star") is not None:
            lines.append(f"  Taux de fraude   {m['fraud_rate_star']:.2%}")
        if m.get("scenario_shares"):
            lines.append("  Parts : " + ", ".join(f"{k} {v:.0%}" for k, v in m["scenario_shares"].items()))
    lines.append("")
    for c in report["checks"]:
        lines += textwrap.wrap(f"{tag[c['level']]} {c['title']}", width)
        lines += textwrap.wrap(c["detail"], width, initial_indent="    ", subsequent_indent="    ")
        if c.get("action"):
            lines += textwrap.wrap("-> " + c["action"], width, initial_indent="    ",
                                   subsequent_indent="       ")
    lines.append("")
    lines.append("Étape suivante :")
    lines += [f"  {s}" for s in report["next_steps"]]
    return "\n".join(lines)
