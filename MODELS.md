# MODELS.md — Model Risk Register (§24.6)

One row per model/engine in production: purpose, inputs, training window,
validation report link (run cards), calibration status, fusion weight, owner,
last review, known failure modes, demotion triggers (§23.7).

| Model / Engine | Purpose | Inputs | Fusion weight | Calibration | Status |
|---|---|---|---|---|---|
| RuleEngine | deterministic directional/regime/behavior scoring | EvidenceBundle | 0.45 | n/a (deterministic) | planned (Phase 3) |
| BayesEngine | log-space belief updating | EvidenceBundle | 0.45 | entropy confidence | planned (Phase 3) |
| MLEngine (LightGBM) | learned p_up | evidence feature vector (§25.6 order) | 0.0 (inert) | isotonic (§6.3) | inert until §8.3 promotion |

Feature-vector width is fixed by `aimos/core/evidence_registry.py` (§25.6):
adding an evidence name is a registry PR + a retrain note here.
