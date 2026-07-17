# MODELS.md — Model Risk Register (§24.6)

One row per model/engine in production: purpose, inputs, training window,
validation report link (run cards), calibration status, fusion weight, owner,
last review, known failure modes, demotion triggers (§23.7).

| Model / Engine | Purpose | Inputs | Fusion weight | Calibration | Status |
|---|---|---|---|---|---|
| RuleEngine | deterministic directional/regime/behavior scoring | EvidenceBundle | 0.45 | n/a (deterministic) | live (Phase 3) |
| BayesEngine | log-space belief updating | EvidenceBundle | 0.45 | entropy confidence | live (Phase 3) |
| MLEngine (LightGBM) | learned p_up | evidence feature vector (§25.6 order) | 0.0 (inert) | isotonic (§6.3) | inert — shadow ladder wired (P6-T1), stays weight 0 until human raises it (§8.3) |
| LLM News Sensor | headlines → structured news evidence | Headline[] | n/a (observation sensor) | §8.4 monthly recalibration | wired (P6-T3), feature-flagged off; cache-or-die replay |

## Promotion ladder (§8.3, P6-T1)
Walk-forward validation ONLY (random split forbidden — `learning/train.py`
`assert_temporal_split`) → val AUC > 0.55 + Brier improves → 2-week shadow
(weight 0) → human raises `intelligence.fusion_weights.ml` in config + restart.
No auto-deployment (`shadow_weight()` returns 0 until config changes).

## Drift demotion (§23.7, P6-T2)
PSI > 0.25 on > 20% of features → "retraining recommended" proposal (never an
auto config write). Brier degradation > 20% → ML fusion weight auto-halves (the
one automated demotion — safe in the direction of caution).

Feature-vector width is fixed by `aimos/core/evidence_registry.py` (§25.6):
adding an evidence name is a registry PR + a retrain note here.
