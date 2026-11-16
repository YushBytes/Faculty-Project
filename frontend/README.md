# ACADLYTICS web app

See the repository README for running the whole system. Locally:

```bash
npm ci
ACADLYTICS_API_URL=http://localhost:8000 npm run dev -- -p 3001   # http://localhost:3001
npm run lint && npm run build
```

Architecture: [`docs/FRONTEND_ARCHITECTURE.md`](docs/FRONTEND_ARCHITECTURE.md).
