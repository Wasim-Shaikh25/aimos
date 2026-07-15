import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { Badge, Empty } from '../components/ui'
export default function DecisionAnatomy() {
  const [ids, setIds] = useState([]); const [sel, setSel] = useState(''); const [a, setA] = useState(null)
  useEffect(() => { api.decisions(30).then(d => {
    if (!d?.decisions?.length) return
    setIds(d.decisions.map(x => x.decision_id)); setSel(d.decisions[0].decision_id)
  }) }, [])
  useEffect(() => { if (sel) api.anatomy(sel).then(setA) }, [sel])
  if (!ids.length) return <div className="page"><h1>Decision Anatomy</h1><Empty what="decisions" /></div>
  const u = a?.understanding, c = a?.chosen
  return <div className="page"><h1>Decision Anatomy</h1>
    <select value={sel} onChange={e => setSel(e.target.value)}>{ids.map(i => <option key={i}>{i}</option>)}</select>
    {u && <div className="flow" style={{ marginTop: 14 }}>
      <div className="node"><div className="t">Evidence → Engines</div>
        rule {u.engine_votes.rule?.toFixed(2)} · bayes {u.engine_votes.bayes?.toFixed(2)} · ml {u.engine_votes.ml?.toFixed(2)}</div>
      <div className="arrow">→</div>
      <div className="node"><div className="t">Fusion</div>p_up <b>{u.p_up.toFixed(3)}</b><br/>conf {(u.confidence * 100).toFixed(0)}%</div>
      <div className="arrow">→</div>
      <div className="node"><div className="t">Regime / Behavior</div><Badge dir={u.regime}>{u.regime}</Badge> {(Math.max(...Object.values(u.regime_probs)) * 100).toFixed(0)}%<br/>{u.behavior}</div>
      <div className="arrow">→</div>
      <div className="node"><div className="t">Scores</div>health {u.coin_health.toFixed(0)} · risk {u.risk_score.toFixed(0)} · opp {u.opportunity_score.toFixed(0)}</div>
      <div className="arrow">→</div>
      <div className="node"><div className="t">Chosen</div><Badge dir={c.action}>{c.action}</Badge> {c.plugin}</div>
    </div>}
    {u && <><h2>Reasons</h2><ul className="mono">{u.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></>}
  </div>
}
