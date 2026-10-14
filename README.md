# Employee Attendance & Analytics API

FastAPI + MongoDB service for the HROne assignment. All application code is in `app/main.py`.

## Run

MongoDB 6.0+ must be reachable. Set `MONGO_URI` and `MONGO_DB` in the environment (a local `.env` is optional; real env vars win).

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python sample_seed.py                               # optional: nine sample documents
uvicorn app.main:app --port 8000
```

`GET /health` returns 200 only after MongoDB answers a ping. Indexes are created at startup.

## Status

CRUD, R1–R5, pagination, and concurrency for create / punch-in / punch-out / regularize are implemented.

Still to implement: the four analytics aggregations and `GET /admin/explain/{endpoint}`. `DECISIONS.md` will be completed with those.
