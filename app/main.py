"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from annotated_types import doc
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from pymongo import MongoClient, ASCENDING, DESCENDING
PRESENCE = {"PRESENT", "WFH", "ON_DUTY"}

load_dotenv()


client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def create_indexes():
    db.employees.create_index(
        [("emp_code", ASCENDING)],
        unique=True,
        name="uq_employees_emp_code"
    )

    db.employees.create_index(
        [("department", ASCENDING), ("joined_on", ASCENDING)],
        name="ix_employees_department_joined"
    )

    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("date", ASCENDING)],
        unique=True,
        name="uq_attendance_emp_date"
    )

    db.attendance_logs.create_index(
        [("date", DESCENDING), ("emp_code", ASCENDING)],
        name="ix_attendance_date_emp"
    )

    db.attendance_logs.create_index(
        [("date", ASCENDING), ("status", ASCENDING)],
        name="ix_attendance_date_status"
    )


class RegularizeRequest(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    shift_start_time = punch_in.replace(
        hour=h, minute=m, second=0, microsecond=0
    )
    minutes = int(
        (punch_in - shift_start_time).total_seconds() // 60)
    return max(0, minutes - 10)


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)



def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))

    end = datetime.fromisoformat(date_str).replace(
        hour=h, minute=m
    )

    # Make both datetimes timezone-aware in IST
    if punch_out.tzinfo is None:
        punch_out = punch_out.replace(tzinfo=IST)

    end = end.replace(tzinfo=IST)

    return max(0, int((punch_out - end).total_seconds() / 60))



# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc



@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    q = {}

    if department:
        q["department"] = department

    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)

    items = list(
        db.employees.find(q).skip(skip).limit(page_size)
    )

    for item in items:
        item["_id"] = str(item["_id"])

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }



@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    ts = (
        datetime.fromtimestamp(body.punched_at / 1000, IST)
        if body.punched_at
        else datetime.now(IST)
    )

    d = ts.date().isoformat()

    if db.attendance_logs.find_one({
        "emp_code": body.emp_code,
        "date": d
    }):
        raise HTTPException(409, "Already punched in for this date")

    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)

    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}



@app.post("/attendance/punch-out")
def punch_out(emp_code: str):
    now = datetime.now(IST)
    today = now.date().isoformat()

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": today
    })

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found for today"
        )

    if record.get("punch_out") is not None:
        raise HTTPException(
            status_code=409,
            detail="Already punched out for today"
        )

    emp = db.employees.find_one({"emp_code": emp_code})

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    punch_in_time = record["punch_in"]

    if isinstance(punch_in_time, str):
        punch_in_time = datetime.fromisoformat(punch_in_time)

    if punch_in_time.tzinfo is None:
        punch_in_time = punch_in_time.replace(tzinfo=IST)
    else:
        punch_in_time = punch_in_time.astimezone(IST)

    punch_out_time = now

    work_hours = compute_work_hours(
        punch_in_time, punch_out_time
    )

    overtime = compute_overtime(
        punch_out_time,
        emp["shift_end"],
        today
    )

    half_day = work_hours < 4.5

    db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {"$set": {
            "punch_out": punch_out_time,
            "work_hours": work_hours,
            "overtime_minutes": overtime,
            "half_day": half_day
        }}
    )

    return {
        "emp_code": emp_code,
        "punch_out": punch_out_time.isoformat(),
        "work_hours": work_hours,
        "overtime_minutes": overtime,
        "half_day": half_day
    }




# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #

@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeRequest
):
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date
    })
    if not record:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found"
        )

    changes = {}
    updates = body.model_dump(exclude_unset=True)

    # Validate status and punch times
    if updates.get("status") in ("ABSENT", "LEAVE"):
        if "punch_in" in updates or "punch_out" in updates:
            raise HTTPException(
                status_code=422,
                detail="Cannot supply punch times with ABSENT or LEAVE"
            )

        if record.get("punch_in") is not None:
            changes["punch_in"] = None

        if record.get("punch_out") is not None:
            changes["punch_out"] = None

    # Identify fields that actually changed
    for field, value in updates.items():
        if field in ("reason", "regularized_by"):
            continue

        if value != record.get(field):
            changes[field] = value

    # Reject requests that make no changes
    if not changes:
        raise HTTPException(
            status_code=422,
            detail="No changes supplied"
        )

    now = datetime.now(IST)

    history_entry = {
        "at": int(now.timestamp() * 1000),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes
    }

    result = db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": changes,
            "$push": {"history": history_entry}
        }
    )

    if result.modified_count == 0:
        raise HTTPException(
            status_code=409,
            detail="Concurrent update conflict"
        )

    updated = db.attendance_logs.find_one(
        {"_id": record["_id"]}
    )
    updated["id"] = str(updated.pop("_id"))

    return updated


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    # Validate month format
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError

        month_start = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Month must be in YYYY-MM format"
        )

    # Check employee exists
    emp = db.employees.find_one({"emp_code": emp_code})

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    # Calculate month boundaries
    start_date = month_start.strftime("%Y-%m-%d")

    if month_start.month == 12:
        next_month = datetime(month_start.year + 1, 1, 1)
    else:
        next_month = datetime(
            month_start.year,
            month_start.month + 1,
            1
        )

    end_date = next_month.strftime("%Y-%m-%d")

    # Calculate working days from joining date
    joined_on = datetime.strptime(
        emp["joined_on"], "%Y-%m-%d"
    ).date()

    current_day = max(month_start.date(), joined_on)
    last_day = next_month.date()

    working_days = 0

    while current_day < last_day:
        if current_day.weekday() < 5:
            working_days += 1

        current_day += timedelta(days=1)

    # MongoDB aggregation pipeline
    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": start_date,
                    "$lt": end_date
                }
            }
        },
        {
            "$addFields": {
                "_day_of_week": {
                    "$dayOfWeek": {
                        "$dateFromString": {
                            "dateString": "$date"
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": None,

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {
                                        "$not": [
                                            {
                                                "$in": [
                                                    "$_day_of_week",
                                                    [1, 7]
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },

                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },

                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },

                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }
            }
        }
    ]

    result = list(db.attendance_logs.aggregate(pipeline))

    # Handle months without attendance records
    summary = result[0] if result else {}

    present_days = summary.get("present_days", 0)
    leave_days = summary.get("leave_days", 0)
    late_count = summary.get("late_count", 0)
    total_late_minutes = summary.get("total_late_minutes", 0)
    total_overtime_minutes = summary.get(
        "total_overtime_minutes", 0
    )

    # Calculate attendance percentage
    if working_days > 0:
        from decimal import Decimal, ROUND_HALF_UP

        attendance_pct = float(
            (Decimal(str(present_days)) * Decimal("100")
             / Decimal(working_days)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP
            )
        )
    else:
        attendance_pct = None

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": leave_days,
        "late_count": late_count,
        "total_late_minutes": total_late_minutes,
        "total_overtime_minutes": total_overtime_minutes,
        "attendance_pct": attendance_pct
    }

@app.get("/analytics/departments/summary")
def department_summary(
    month: str,
    department: str = None
):
    from decimal import Decimal, ROUND_HALF_UP
    from datetime import datetime, timedelta

    # Validate month
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError

        month_start = datetime.strptime(month, "%Y-%m")

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Month must be in YYYY-MM format"
        )

    # Calculate month boundaries
    if month_start.month == 12:
        next_month = datetime(month_start.year + 1, 1, 1)
    else:
        next_month = datetime(
            month_start.year,
            month_start.month + 1,
            1
        )

    start_date = month_start.strftime("%Y-%m-%d")
    end_date = next_month.strftime("%Y-%m-%d")
    month_end = (next_month - timedelta(days=1)).strftime("%Y-%m-%d")

    # Include employees who have joined by month end
    employee_match = {
        "joined_on": {"$lte": month_end}
    }

    if department:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},

        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {
                                        "$eq": [
                                            "$emp_code",
                                            "$$employee_code"
                                        ]
                                    },
                                    {"$gte": ["$date", start_date]},
                                    {"$lt": ["$date", end_date]}
                                ]
                            }
                        }
                    },
                    {
                        "$addFields": {
                            "_day_of_week": {
                                "$dayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date"
                                    }
                                }
                            }
                        }
                    }
                ],
                "as": "logs"
            }
        },

        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True
            }
        },

        # Calculate metrics for each employee
        {
            "$group": {
                "_id": {
                    "emp_code": "$emp_code",
                    "department": "$department"
                },

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {
                                        "$not": [
                                            {
                                                "$in": [
                                                    "$logs._day_of_week",
                                                    [1, 7]
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },

                "work_hours_sum": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {"$ne": ["$logs.work_hours", None]}
                                ]
                            },
                            "$logs.work_hours",
                            0
                        ]
                    }
                },

                "work_hours_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    },
                                    {"$ne": ["$logs.work_hours", None]}
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },

                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$logs.late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$logs.late_minutes", 0]},
                            "$logs.late_minutes",
                            0
                        ]
                    }
                },

                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },

                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0
                        ]
                    }
                }
            }
        },

        # Combine employee metrics by department
        {
            "$group": {
                "_id": "$_id.department",
                "headcount": {"$sum": 1},
                "present_days": {"$sum": "$present_days"},
                "work_hours_sum": {"$sum": "$work_hours_sum"},
                "work_hours_count": {"$sum": "$work_hours_count"},
                "late_count": {"$sum": "$late_count"},
                "total_late_minutes": {"$sum": "$total_late_minutes"},
                "leave_count": {"$sum": "$leave_count"},
                "on_duty_count": {"$sum": "$on_duty_count"}
            }
        },

        {"$sort": {"_id": 1}}
    ]

    results = list(db.employees.aggregate(pipeline))

    items = []

    for row in results:
        count = row["work_hours_count"]

        if count:
            avg_hours = (
                Decimal(str(row["work_hours_sum"])) / Decimal(count)
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )
            avg_hours = float(avg_hours)
        else:
            avg_hours = None

        present_days = float(
            Decimal(str(row["present_days"])).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )
        )

        items.append({
            "department": row["_id"],
            "headcount": row["headcount"],
            "present_days": present_days,
            "avg_work_hours": avg_hours,
            "late_count": row["late_count"],
            "total_late_minutes": row["total_late_minutes"],
            "leave_count": row["leave_count"],
            "on_duty_count": row["on_duty_count"]
        })

    return {
        "month": month,
        "items": items
    }

@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None
):
    # Validate month and get the month's date range
    
  if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
    raise HTTPException(
        status_code=422,
        detail="Month must be in YYYY-MM format"
    )
  

    pipeline = [
        {
    "$match": {
        "date": {
            "$gte": f"{month}-01",
            "$lt": f"{month}-99"
        }
    }
},

        # Calculate total late minutes and late count per employee
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                }
            }
        },

        # Include only employees who were late
        {"$match": {"total_late_minutes": {"$gt": 0}}},

        # Get employee details
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    # Filter by department if supplied
    if department is not None:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline += [
        # Competition ranking: ties share ranks
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {"rank": {"$rank": {}}}
            }
        },

        # Apply limit after ranking so ties are included
        {"$match": {"rank": {"$lte": limit}}},

        # Sort results
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },

        # Select response fields
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ]

    rows = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": rows
    }


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...)
):
    # Validate dates
   
  for value, field in [(from_, "from"), (to, "to")]:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be in YYYY-MM-DD format"
        )
 

    start_dt = datetime.strptime(from_, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    end_dt = datetime.strptime(to, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )

    if end_dt < start_dt or (end_dt - start_dt).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="to must be >= from and range cannot exceed 92 days"
        )

    # Check department exists
    if not db.employees.find_one({"department": department}):
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )

    pipeline = [
        # Get attendance records in the requested date range
        {
            "$match": {
                "date": {
                    "$gte": from_,
                    "$lte": to
                }
            }
        },

        # Get employee details
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"},

        # Only this department
        {"$match": {"employee.department": department}},

        # Calculate daily attendance counts
        {
            "$group": {
                "_id": "$date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", list(PRESENCE)]},
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$gt": [
                                    {"$ifNull": ["$late_minutes", 0]},
                                    0
                                ]
                            },
                            1,
                            0
                        ]
                    }
                }
            }
        },

        # Convert date strings into MongoDB dates
        {
            "$project": {
                "_id": 0,
                "date": {
                    "$dateFromString": {
                        "dateString": "$_id"
                    }
                },
                "present_count": 1,
                "late_count": 1
            }
        },

        # Add start and end dates, even if no attendance exists
        {
            "$unionWith": {
                "pipeline": [
                    {
                        "$documents": [
                            {
                                "date": start_dt,
                                "present_count": 0,
                                "late_count": 0
                            },
                            {
                                "date": end_dt,
                                "present_count": 0,
                                "late_count": 0
                            }
                        ]
                    }
                ]
            }
        },

        # Merge duplicate dates from attendance and boundary records
        {
            "$group": {
                "_id": "$date",
                "present_count": {"$max": "$present_count"},
                "late_count": {"$max": "$late_count"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$_id",
                "present_count": 1,
                "late_count": 1
            }
        },

        # Fill missing calendar days inside the requested range
        {
            "$densify": {
                "field": "date",
                "range": {
                    "bounds": [start_dt, end_dt],
                    "step": 1,
                    "unit": "day"
                }
            }
        },

        # Default missing counts to zero
        {
            "$set": {
                "present_count": {
                    "$ifNull": ["$present_count", 0]
                },
                "late_count": {
                    "$ifNull": ["$late_count", 0]
                },
                "date_str": {
                    "$dateToString": {
                        "date": "$date",
                        "format": "%Y-%m-%d",
                        "timezone": "UTC"
                    }
                }
            }
        },

        # Calculate department headcount for each day
        {
            "$lookup": {
                "from": "employees",
                "let": {"day": "$date_str"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department,
                            "$expr": {
                                "$lte": ["$joined_on", "$$day"]
                            }
                        }
                    },
                    {"$count": "n"}
                ],
                "as": "headcount_data"
            }
        },
        {
            "$set": {
                "headcount": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$headcount_data.n", 0]},
                        0
                    ]
                },
                "is_working_day": {
                    "$and": [
                        {
                            "$gte": [
                                {"$dayOfWeek": "$date"},
                                2
                            ]
                        },
                        {
                            "$lte": [
                                {"$dayOfWeek": "$date"},
                                6
                            ]
                        }
                    ]
                }
            }
        },

        # Attendance rate only on working days with employees
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]}
                            ]
                        },
                        {
                            "$divide": [
                                "$present_count",
                                "$headcount"
                            ]
                        },
                        None
                    ]
                }
            }
        },

        # Seven-day moving average in MongoDB
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, 0]
                        }
                    }
                }
            }
        },

        {"$sort": {"date": 1}},

        {
            "$project": {
                "_id": 0,
                "date": "$date_str",
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1
            }
        }
    ]

    rows = list(db.attendance_logs.aggregate(pipeline))

    # Apply half-up rounding to the reported rates
    items = []
    for row in rows:
        for field in ("attendance_rate", "moving_avg_7d"):
            value = row.get(field)
            if value is not None:
                row[field] = float(
                    Decimal(str(value)).quantize(
                        Decimal("0.0001"),
                        rounding=ROUND_HALF_UP
                    )
                )
        items.append(row)

    return {
        "department": department,
        "from": from_,
        "to": to,
        "items": items
    }

@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None
):
    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    }

    if endpoint not in allowed:
        raise HTTPException(
            status_code=422,
            detail="Unsupported endpoint"
        )

    # Validate required parameters
    if endpoint == "employee_monthly" and (not emp_code or not month):
        raise HTTPException(422, "emp_code and month are required")

    if endpoint in {"department_summary", "late_leaderboard"} and not month:
        raise HTTPException(422, "month is required")

    if endpoint == "department_trend":
        if not department or not from_ or not to:
            raise HTTPException(422, "department, from and to are required")

    # Build the month date range
    if month:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise HTTPException(422, "month must be YYYY-MM")

        month_start = datetime.strptime(month, "%Y-%m")
        if month_start.month == 12:
            next_month = datetime(month_start.year + 1, 1, 1)
        else:
            next_month = datetime(
                month_start.year,
                month_start.month + 1,
                1
            )

        start_date = month_start.strftime("%Y-%m-%d")
        end_date = next_month.strftime("%Y-%m-%d")

    # Explain the attendance list query
    if endpoint == "attendance_list":
        query = {}

        if emp_code:
            query["emp_code"] = emp_code

        if from_ or to:
            query["date"] = {}
            if from_:
                query["date"]["$gte"] = from_
            if to:
                query["date"]["$lte"] = to

        result = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1},
                "limit": limit
            },
            verbosity="executionStats"
        )
        return result

    # Explain the employee monthly query
    if endpoint == "employee_monthly":
        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": start_date,
                        "$lt": end_date
                    }
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "record_count": {"$sum": 1},
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": ["$late_minutes", 0]},
                                1,
                                0
                            ]
                        }
                    }
                }
            }
        ]
        collection = "attendance_logs"

    # Explain the department summary query
    elif endpoint == "department_summary":
        pipeline = [
            {
                "$match": {
                    "joined_on": {"$lt": end_date}
                }
            },
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"code": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$emp_code", "$$code"]},
                                        {"$gte": ["$date", start_date]},
                                        {"$lt": ["$date", end_date]}
                                    ]
                                }
                            }
                        }
                    ],
                    "as": "logs"
                }
            }
        ]

        if department:
            pipeline[0]["$match"]["department"] = department

        collection = "employees"

    # Explain the late leaderboard query
    elif endpoint == "late_leaderboard":
        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": start_date,
                        "$lt": end_date
                    }
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {
                        "$sum": {"$ifNull": ["$late_minutes", 0]}
                    }
                }
            },
            {"$match": {"total_late_minutes": {"$gt": 0}}},
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "employee"
                }
            }
        ]

        if department:
            pipeline.append({
                "$match": {"employee.department": department}
            })

        collection = "attendance_logs"

    # Explain the department trend query
    else:
        try:
            datetime.strptime(from_, "%Y-%m-%d")
            datetime.strptime(to, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                422,
                "from and to must use YYYY-MM-DD format"
            )

        if to < from_:
            raise HTTPException(422, "to must be >= from")

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": from_,
                        "$lte": to
                    }
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "employee"
                }
            },
            {"$unwind": "$employee"},
            {"$match": {"employee.department": department}}
        ]
        collection = "attendance_logs"

    # Return MongoDB's raw executionStats explain output
    return db.command(
        "explain",
        {
            "aggregate": collection,
            "pipeline": pipeline,
            "cursor": {}
        },
        verbosity="executionStats"
    )