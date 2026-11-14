# Frontend (React + JavaScript, Vite)

Created in Milestone 0 with `npm create vite@latest . -- --template react` (JavaScript, no TypeScript).

```
frontend/src/
├── main.jsx  App.jsx            # router + auth guard
├── lib/
│   ├── api.js                   # fetch wrapper for FastAPI (adds Supabase JWT)
│   ├── supabase.js              # supabase-js client: AUTH ONLY
│   ├── auth.jsx                 # AuthProvider, useAuth, role guard
│   └── livekit.js               # join room helpers (livekit-client)
├── hooks/                       # useSSE (customer ring events), usePolling, ...
├── components/                  # Shell, Table, StatCard, CallScreen, Toast ...
├── pages/
│   ├── business/                # Onboarding, Home, Knowledge, AgentSettings, Campaigns, Inbound, Calls, CallDetail, Bookings, Billing
│   ├── admin/                   # Overview, Latency, Quality, FlaggedCalls, TestSuite
│   └── customer/                # IncomingCall (/c/:token), CallUs (/call)
└── styles/
```
