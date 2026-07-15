# AIMOS Dashboard (§16.2, §18.5)

React (Vite) frontend for the 9 screens. Requires Node ≥ 18.

```
npm install
npm run dev     # proxies /api to the FastAPI backend on :8000
```

Screens: Markets · Asset detail · Decision Anatomy · Universe & Venues ·
Positions & Risk · Decisions · Performance · Config viewer · Agents. Every screen
reads the journal-backed API so what you see is exactly what happened (§16.2).

NOTE: this is the build scaffold. The screens currently render raw API JSON;
the production components (lightweight-charts candles, evidence tables,
left-to-right anatomy flow) are built out against these endpoints.
