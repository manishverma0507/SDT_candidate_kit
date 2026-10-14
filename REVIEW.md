# REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `compute_late_minutes` | Used `minutes > 10` after `int(seconds/60)`. `09:40:01` is 601s → 10 minutes, and `10 > 10` is false, so it returned 0. Also ignored R1 truncation and overnight shift start. | Shift 09:30, punch-in `09:40:01` IST. Spec wants `late_minutes=10`; starter returned 0. | Late iff elapsed seconds **> 600**, then `floor` minutes since `shift_start` on the attendance date. |
| 2 | `compute_work_hours` | Python `round` is banker's rounding and binary float, not half-up. No second truncation. | Durations that sit on x.xx5 (e.g. 9.125h) disagree with R4. | Truncate to seconds, `Decimal` `/ 3600`, `ROUND_HALF_UP` to 2 places. |
| 3 | `compute_overtime` | No 30-minute minimum; overnight `shift_end` was applied on the start date; naive vs IST-aware datetimes could crash or skew. | EMP0005 22:00–06:00, out 06:40 IST: spec 40; starter compared to 06:00 *same* day. Out at 18:35 (5 min) should be 0, starter stored 5. | Shift end moves +1 day when overnight. Count floor minutes only if `>= 30`. |
| 4 | module import / startup | No indexes. Concurrent creates/punches raced; list would `COLLSCAN` at 100k. | Two parallel `POST /employees` with the same `emp_code` both 201. | Create unique `emp_code`, unique `(emp_code,date)`, `department`, and `(date,-1,emp_code)` at startup. |
| 5 | `MongoClient(...)` | Default naive datetimes. R1 IST date and epoch conversion then depend on the host TZ. | Punch at 21:55 IST stored/read back as a local-naive value; overnight `date` wrong on a UTC machine. | `tz_aware=True, tzinfo=timezone.utc`. Convert at the API boundary. |
| 6 | every response | BSON datetimes leaked as ISO strings; `id` / `_id` appeared. History nested punch times were not converted. | `GET /attendance` after punch-in: `punch_in` was not an int, body had `id`. | Serialize employees/records to epoch ms; never return `_id`/`id`; convert history `at` and punch `from`/`to`. |
| 7 | `health` | Always `{"status":"ok"}` without pinging Mongo. | Stop mongod; runner still got 200 and started tests. | `db.command("ping")`; on failure 503. |
| 8 | `EmployeeIn` / `PunchInIn` | No OpenAPI constraints (emp_code pattern, email, HH:MM, epoch range, presence-only status). Extra derived fields not ignored by contract. | `emp_code=BAD`, `punched_at=1783312500` (seconds), `status=LEAVE` were accepted or 500. | Pydantic models matching the spec; `extra="ignore"`; `StrictInt` epoch bounds. |
| 9 | `create_employee` | Check-then-insert. `created_at=datetime.now()` naive local, not epoch ms. Equal `shift_start`/`shift_end` allowed. | Parallel duplicate creates; `created_at` not an int; `09:30`/`09:30` returned 201. | Unique index + `DuplicateKeyError` → 409. Server UTC truncated `created_at`. Shifts must differ → 422. |
| 10 | `list_employees` | `skip = page * page_size` skipped page 1. `total` ignored the department filter. No `emp_code` sort. `page_size` uncapped. | `page=1` returned EMP0003+ instead of EMP0001. `department=Sales` still showed `total` of the whole collection. | `skip=(page-1)*page_size`; count the filter; sort `emp_code`; `page_size` 1–100. |
| 11 | `punch_in` | Unknown employee → 500. Date from local `ts.date()`, not IST/R1 overnight. Check-then-insert. Returned `id`. No 404. | `EMP9999` 500; 05:00 IST on a 22:00–06:00 shift dated that morning instead of the previous day; two punch-ins both 201. | 404 if missing; IST + overnight date; unique `(emp_code,date)` insert → 409; serialize without `id`. |
| 12 | `list_attendance` | Loaded the matching set into memory and sorted in Python. No secondary `emp_code` sort. `date_from > date_to` not 422. Missing `history`/`half_day` not defaulted. Added `id`. | Would OOM/slow at 100k. Legacy EMP0002 omitted `half_day`. Unordered ties on the same date. | Mongo `find` + sort + skip/limit; 422 on inverted range; default `history=[]`, `half_day=false`. |

Also note anything you looked at and decided was **not** a defect, and why.

- `load_dotenv()` without `override=True` is correct: injected `MONGO_URI` / `MONGO_DB` win over a local `.env`.
- Falling back to `mongodb://localhost:27017` and `attendance_db` is only a local convenience; the grader injects env vars.
- `IST = timezone(timedelta(hours=5, minutes=30))` is the right offset; the bugs were in *using* it, not in the constant.
- FastAPI app title/version `"2.0.0"` matched the contract.
- Using sync PyMongo (not Motor) matches the starter and is enough for this process model.
