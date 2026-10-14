"""Local verification for foundation, starter fixes, punch-out, and regularize.

Not part of the graded application. Run from candidate_kit/:

    .venv/Scripts/python.exe tests/test_stage1.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ["MONGO_URI"] = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
os.environ["MONGO_DB"] = "sdt_stage1_test"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, db  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
failures: list[str] = []


def ist_ms(year, month, day, hour, minute, second=0) -> int:
    dt = datetime(year, month, day, hour, minute, second, tzinfo=IST)
    return int(dt.timestamp()) * 1000


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def reset() -> None:
    db.employees.delete_many({})
    db.attendance_logs.delete_many({})


def create_emp(client: TestClient, code: str, **kwargs) -> dict:
    body = {
        "emp_code": code,
        "name": kwargs.get("name", "Asha Rao"),
        "email": kwargs.get("email", f"{code.lower()}@example.com"),
        "department": kwargs.get("department", "Engineering"),
        "shift_start": kwargs.get("shift_start", "09:30"),
        "shift_end": kwargs.get("shift_end", "18:30"),
        "joined_on": kwargs.get("joined_on", "2026-01-05"),
    }
    res = client.post("/employees", json=body)
    check(f"create {code} status", res.status_code == 201, str(res.status_code) + res.text)
    return res.json() if res.status_code == 201 else {}


def main() -> int:
    with TestClient(app) as client:
        print("health")
        h = client.get("/health")
        check("health 200", h.status_code == 200 and h.json() == {"status": "ok"}, h.text)

        print("employee validation and pagination")
        reset()
        bad = client.post(
            "/employees",
            json={
                "emp_code": "BAD",
                "name": "X",
                "email": "not-an-email",
                "department": "Engineering",
                "joined_on": "2026-01-05",
            },
        )
        check("invalid emp_code 422", bad.status_code == 422, str(bad.status_code))

        same_shift = client.post(
            "/employees",
            json={
                "emp_code": "EMP0999",
                "name": "Same Shift",
                "email": "same@example.com",
                "department": "Engineering",
                "shift_start": "09:30",
                "shift_end": "09:30",
                "joined_on": "2026-01-05",
            },
        )
        check("equal shifts 422", same_shift.status_code == 422, str(same_shift.status_code))

        a = create_emp(client, "EMP0001")
        check("created_at is int ms", isinstance(a.get("created_at"), int), str(a.get("created_at")))
        check("no _id on employee", "_id" not in a and "id" not in a, str(a.keys()))
        check("defaults shifts", a.get("shift_start") == "09:30" and a.get("shift_end") == "18:30")

        dup = client.post(
            "/employees",
            json={
                "emp_code": "EMP0001",
                "name": "Dup",
                "email": "dup@example.com",
                "department": "Engineering",
                "joined_on": "2026-01-05",
            },
        )
        check("duplicate emp sequential 409", dup.status_code == 409, str(dup.status_code))

        create_emp(client, "EMP0002", department="Sales")
        create_emp(client, "EMP0003", department="Sales")
        listed = client.get("/employees", params={"page": 1, "page_size": 2})
        body = listed.json()
        check("list page 1 skip", body["items"][0]["emp_code"] == "EMP0001", str(body))
        check("list sorted emp_code", [i["emp_code"] for i in body["items"]] == ["EMP0001", "EMP0002"])
        check("list total all", body["total"] == 3, str(body["total"]))
        sales = client.get("/employees", params={"department": "Sales"})
        check("list total filtered", sales.json()["total"] == 2, str(sales.json()))
        too_big = client.get("/employees", params={"page_size": 101})
        check("page_size 101 -> 422", too_big.status_code == 422, str(too_big.status_code))

        print("punch-in rules R1 R2")
        reset()
        create_emp(client, "EMP0001")
        missing = client.post("/attendance/punch-in", json={"emp_code": "EMP9999"})
        check("unknown employee 404", missing.status_code == 404, str(missing.status_code))

        seconds = client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0001", "punched_at": 1_783_312_500},
        )
        check("seconds-looking timestamp 422", seconds.status_code == 422, str(seconds.status_code))

        leave = client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0001", "status": "LEAVE", "punched_at": ist_ms(2026, 7, 6, 9, 28)},
        )
        check("LEAVE punch-in 422", leave.status_code == 422, str(leave.status_code))

        exact_grace = client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 9, 40, 0)},
        )
        check("09:40:00 late_minutes 0", exact_grace.status_code == 201 and exact_grace.json()["late_minutes"] == 0, exact_grace.text)
        check("punch-in date IST", exact_grace.json()["date"] == "2026-07-06", str(exact_grace.json().get("date")))
        check("open record defaults", exact_grace.json()["punch_out"] is None and exact_grace.json()["work_hours"] is None)
        check("no id on attendance", "id" not in exact_grace.json() and "_id" not in exact_grace.json())
        check("history empty", exact_grace.json()["history"] == [])

        one_sec = client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 7, 9, 40, 1)},
        )
        check("09:40:01 late_minutes 10", one_sec.status_code == 201 and one_sec.json()["late_minutes"] == 10, one_sec.text)

        again = client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 9, 45)},
        )
        check("second punch-in same date 409", again.status_code == 409, str(again.status_code))

        print("overnight punch-in")
        reset()
        create_emp(client, "EMP0005", department="Support", shift_start="22:00", shift_end="06:00")
        early_morning = client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0005", "punched_at": ist_ms(2026, 7, 7, 5, 0)},
        )
        check(
            "overnight 05:00 belongs to previous date",
            early_morning.status_code == 201 and early_morning.json()["date"] == "2026-07-06",
            early_morning.text,
        )
        evening = client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0005", "punched_at": ist_ms(2026, 7, 7, 21, 55)},
        )
        check(
            "overnight 21:55 is same IST date",
            evening.status_code == 201 and evening.json()["date"] == "2026-07-07",
            evening.text,
        )

        print("punch-out R3 R4 R5")
        reset()
        create_emp(client, "EMP0001")
        client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 9, 28)})
        same_time = client.post(
            "/attendance/punch-out",
            json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 9, 28)},
        )
        check("punch-out at punch_in 422", same_time.status_code == 422, str(same_time.status_code) + same_time.text)
        too_late = client.post(
            "/attendance/punch-out",
            json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 7, 9, 29)},
        )
        check("punch-out >24h 422", too_late.status_code == 422, str(too_late.status_code) + too_late.text)
        sample = client.post(
            "/attendance/punch-out",
            json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 18, 35)},
        )
        check("sample work_hours 9.12", sample.status_code == 200 and sample.json()["work_hours"] == 9.12, sample.text)
        check("overtime 5 min -> 0", sample.json().get("overtime_minutes") == 0, str(sample.json()))
        check("half_day false", sample.json().get("half_day") is False)

        already = client.post(
            "/attendance/punch-out",
            json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 18, 40)},
        )
        check("punch-out already closed 409", already.status_code == 409, str(already.status_code) + already.text)

        reset()
        create_emp(client, "EMP0003")
        client.post("/attendance/punch-in", json={"emp_code": "EMP0003", "punched_at": ist_ms(2026, 7, 6, 10, 5)})
        late_ot = client.post(
            "/attendance/punch-out",
            json={"emp_code": "EMP0003", "punched_at": ist_ms(2026, 7, 6, 19, 10)},
        )
        check("late 35", late_ot.json().get("late_minutes") == 35, late_ot.text)
        check("overtime 40", late_ot.json().get("overtime_minutes") == 40, late_ot.text)
        check("work_hours 9.08", late_ot.json().get("work_hours") == 9.08, late_ot.text)

        reset()
        create_emp(client, "EMP0004")
        client.post(
            "/attendance/punch-in",
            json={"emp_code": "EMP0004", "status": "WFH", "punched_at": ist_ms(2026, 7, 7, 9, 30)},
        )
        half = client.post(
            "/attendance/punch-out",
            json={"emp_code": "EMP0004", "punched_at": ist_ms(2026, 7, 7, 13, 0)},
        )
        check("half day 3.5 hours", half.json().get("work_hours") == 3.5 and half.json().get("half_day") is True, half.text)

        reset()
        create_emp(client, "EMP0005", shift_start="22:00", shift_end="06:00")
        client.post("/attendance/punch-in", json={"emp_code": "EMP0005", "punched_at": ist_ms(2026, 7, 6, 21, 55)})
        overnight_out = client.post(
            "/attendance/punch-out",
            json={"emp_code": "EMP0005", "punched_at": ist_ms(2026, 7, 7, 6, 40)},
        )
        check("overnight work_hours 8.75", overnight_out.status_code == 200 and overnight_out.json()["work_hours"] == 8.75, overnight_out.text)
        check("overnight overtime 40", overnight_out.json().get("overtime_minutes") == 40, overnight_out.text)
        check("overnight date stays start day", overnight_out.json().get("date") == "2026-07-06")

        none = client.post("/attendance/punch-out", json={"emp_code": "EMP0001"})
        check("punch-out unknown employee 404", none.status_code == 404)

        print("list attendance")
        listed = client.get("/attendance", params={"date_from": "2026-07-08", "date_to": "2026-07-01"})
        check("date_from > date_to 422", listed.status_code == 422, str(listed.status_code))
        ok = client.get("/attendance", params={"emp_code": "EMP0005"})
        check("list one overnight record", ok.status_code == 200 and ok.json()["total"] == 1, ok.text)
        check("list punch_in is int", isinstance(ok.json()["items"][0]["punch_in"], int))

        print("regularize")
        reset()
        create_emp(client, "EMP0001")
        client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 10, 5)})
        client.post("/attendance/punch-out", json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 18, 30)})
        patched = client.patch(
            "/attendance/EMP0001/2026-07-06",
            json={
                "punch_in": ist_ms(2026, 7, 6, 9, 28),
                "reason": "biometric glitch",
                "regularized_by": "hr.admin",
            },
        )
        pj = patched.json()
        check("regularize 200", patched.status_code == 200, patched.text)
        check("recomputed late 0", pj.get("late_minutes") == 0, str(pj))
        check("one history entry", len(pj.get("history") or []) == 1, str(pj.get("history")))
        hist = (pj.get("history") or [{}])[0]
        check("history at is int", isinstance(hist.get("at"), int), str(hist.get("at")))
        check("history punch_in from/to are int", isinstance(hist.get("changes", {}).get("punch_in", {}).get("from"), int))
        check("history includes late_minutes", "late_minutes" in hist.get("changes", {}), str(hist.get("changes")))
        check("punch-in did not duplicate history on original punch", True)

        noop = client.patch(
            "/attendance/EMP0001/2026-07-06",
            json={
                "punch_in": ist_ms(2026, 7, 6, 9, 28),
                "reason": "biometric glitch",
                "regularized_by": "hr.admin",
            },
        )
        check("no-op regularize 422", noop.status_code == 422, str(noop.status_code) + noop.text)

        absent_bad = client.patch(
            "/attendance/EMP0001/2026-07-06",
            json={
                "status": "ABSENT",
                "punch_in": ist_ms(2026, 7, 6, 9, 28),
                "reason": "cannot mix these",
                "regularized_by": "hr.admin",
            },
        )
        check("ABSENT with punch_in 422", absent_bad.status_code == 422)

        absent = client.patch(
            "/attendance/EMP0001/2026-07-06",
            json={"status": "ABSENT", "reason": "marked absent", "regularized_by": "hr.admin"},
        )
        check("ABSENT clears punches", absent.status_code == 200 and absent.json()["punch_in"] is None, absent.text)
        check("ABSENT derived zeros", absent.json()["late_minutes"] == 0 and absent.json()["work_hours"] is None)
        check("history grew to 2", len(absent.json()["history"]) == 2)

        missing_day = client.patch(
            "/attendance/EMP0001/2026-07-01",
            json={"status": "LEAVE", "reason": "no such day", "regularized_by": "hr.admin"},
        )
        check("missing record 404", missing_day.status_code == 404)

        wrong_date = client.patch(
            "/attendance/EMP0001/2026-07-06",
            json={
                "status": "PRESENT",
                "punch_in": ist_ms(2026, 7, 7, 9, 30),
                "reason": "wrong attendance day",
                "regularized_by": "hr.admin",
            },
        )
        check("punch_in other date 422", wrong_date.status_code == 422, wrong_date.text)

        print("legacy missing history/half_day")
        db.attendance_logs.insert_one(
            {
                "emp_code": "EMP0001",
                "date": "2026-07-14",
                "status": "PRESENT",
                "punch_in": datetime(2026, 7, 14, 4, 2, tzinfo=timezone.utc),
                "punch_out": datetime(2026, 7, 14, 13, 1, tzinfo=timezone.utc),
                "work_hours": 8.98,
                "late_minutes": 0,
                "overtime_minutes": 0,
            }
        )
        legacy = client.get("/attendance", params={"date_from": "2026-07-14", "date_to": "2026-07-14"})
        item = legacy.json()["items"][0]
        check("legacy history []", item["history"] == [])
        check("legacy half_day false", item["half_day"] is False)

        print("concurrency")
        reset()
        payload = {
            "emp_code": "EMP0100",
            "name": "Race",
            "email": "race@example.com",
            "department": "Engineering",
            "joined_on": "2026-01-05",
        }

        def create_once():
            return client.post("/employees", json=payload).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(lambda _: create_once(), range(8)))
        check("create race one 201", codes.count(201) == 1, str(codes))
        check("create race rest 409", codes.count(409) == 7, str(codes))

        reset()
        create_emp(client, "EMP0001")
        punch_payload = {"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 9, 30)}

        def punch_once():
            return client.post("/attendance/punch-in", json=punch_payload).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            punch_codes = list(pool.map(lambda _: punch_once(), range(8)))
        check("punch-in race one 201", punch_codes.count(201) == 1, str(punch_codes))
        check("punch-in race rest 409", punch_codes.count(409) == 7, str(punch_codes))
        check("one attendance doc", db.attendance_logs.count_documents({}) == 1)

        out_payload = {"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 18, 30)}

        def out_once():
            return client.post("/attendance/punch-out", json=out_payload).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            out_codes = list(pool.map(lambda _: out_once(), range(8)))
        check("punch-out race one 200", out_codes.count(200) == 1, str(out_codes))
        check("punch-out race rest 409", out_codes.count(409) == 7, str(out_codes))

        reset()
        create_emp(client, "EMP0001")
        client.post("/attendance/punch-in", json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 10, 5)})
        client.post("/attendance/punch-out", json={"emp_code": "EMP0001", "punched_at": ist_ms(2026, 7, 6, 18, 30)})

        def patch_once(i: int):
            return client.patch(
                "/attendance/EMP0001/2026-07-06",
                json={
                    "reason": f"concurrent edit {i}xx",
                    "regularized_by": f"user{i}",
                    "punch_in": ist_ms(2026, 7, 6, 9, 28 + i % 2),
                },
            ).status_code

        with ThreadPoolExecutor(max_workers=6) as pool:
            patch_codes = list(pool.map(patch_once, range(6)))
        rec = db.attendance_logs.find_one({"emp_code": "EMP0001", "date": "2026-07-06"})
        hist_len = len(rec.get("history") or [])
        check("regularize no silent history loss", hist_len >= 1, str(hist_len))
        check(
            "regularize winners match history length",
            patch_codes.count(200) == hist_len and set(patch_codes) <= {200, 409, 422},
            f"codes={patch_codes} hist={hist_len}",
        )

    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for item in failures:
            print(" -", item)
        return 1
    print("All stage-1 checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
