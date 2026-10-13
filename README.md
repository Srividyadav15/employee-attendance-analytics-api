# Candidate kit

Read in this order:

1. `PROBLEM_STATEMENT.docx`: what you are asked to do, how it is evaluated.
2. `openapi.yaml`: the API contract and the business rules (R1 - R10).
3. `DATA_MODEL.md`: what is stored in MongoDB, with nine sample documents.
4. `app/main.py`: the starter. Put **all** your code in this one file. It must start with `uvicorn app.main:app --port 8000`.
5. `REVIEW.md`, `DECISIONS.md`: templates to fill in.

`sample_data/` holds the nine sample documents as MongoDB Extended JSON; `sample_seed.py` loads them. The grader's dataset is
much larger and contains cases they do not show.

## Local setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set MONGO_URI / MONGO_DB (local docker: docker run -p 27017:27017 mongo:7)
python sample_seed.py
uvicorn app.main:app --port 8000 --reload
```
MongoDB **6.0 or newer** is required (the grader uses 7.0). MongoDB Atlas free tier (M0) works.

## Submit
A public Git repository with `app/main.py`, `requirements.txt`, `REVIEW.md`, `DECISIONS.md` and a short `README.md`.
No `.env`, no secrets, no Dockerfile.
# Employee Attendance & Analytics API

## Project Overview
This project implements an Employee Attendance and Analytics API using FastAPI and MongoDB.

## Implemented Features
- FastAPI application setup and MongoDB connectivity.
- Employee creation and listing.
- Attendance punch-in and punch-out endpoints.
- Attendance listing and regularization.
- Employee monthly analytics.
- Department summary analytics.
- Late leaderboard.
- Department trend endpoint.
- Admin endpoint for MongoDB query explain statistics.
- MongoDB index creation at application startup.

## How to Run
1. Install the required dependencies:

   `pip install -r requirements.txt`

2. Configure `MONGO_URI` and `MONGO_DB` in the environment.

3. Start the application:

   `uvicorn app.main:app --port 8000`

4. Open the API documentation:

   `http://127.0.0.1:8000/docs`

## Remaining Work and Limitations
The API endpoints have been implemented, but full validation against all assignment requirements is still in progress. Department trend calculations require further verification, including headcount, attendance rate, and the seven-day moving average. Analytics edge cases, concurrency behavior, and MongoDB index usage through the Explain endpoint also require further testing.

The review findings and design decisions documentation must be completed or reviewed before the submission is considered final.

## Configuration and Security
Provide MongoDB connection settings through environment variables. Do not commit `.env` files, credentials, secrets, or virtual environment folders.
