# DECISIONS.md  (about 150-200 words in total - plain language, your own words)

1. **Indexes.** Which indexes did you create, and which query or guarantee does each one serve? Which one did you consider and reject?
I added indexes for employee codes, employee department and joining date, and attendance records by employee and date. These indexes help find employees quickly, filter attendance by date, and support analytics queries. A unique index prevents duplicate employee codes and duplicate employee-date attendance records. I still need to verify index usage through MongoDB explain statistics.
2. **Punch-in race.** Two identical punch-in requests arrive at the same instant. Walk through exactly what happens in your code.
If two identical punch-in requests arrive at the same time, both may initially check that no record exists. A unique employee-date index should allow only one insert and reject the duplicate. The API should handle duplicate-key errors and return an appropriate conflict response. This behavior needs to be tested with simultaneous requests.
3. **Ties.** Two employees are tied on late minutes at the cutoff of `limit`. What does your leaderboard return, and why?
Employees with equal total late minutes should receive the same competition rank. For example, ranks can be 1, 2, 2, and 4. The limit should be applied after ranking so every employee tied at the cutoff rank is included.
4. **Headcount.** How does your department summary make sure employees with zero logs are counted?
Department headcount should come from eligible employee records, not attendance logs. Employees who joined on or before the reporting period ends must count even if they have no attendance records. Future joiners should be excluded.
5. **One thing you would change** if this had to serve 100x the data.
For 100 times more data, I would check query execution plans, optimize indexes, and measure aggregation performance. I would also add automated tests and benchmark realistic data volumes before considering database scaling.
