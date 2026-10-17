"""Made-up gym logbooks for the tests and the recorded checks, in the shape of Alex's (one row a set; Date d/m/yyyy
or DNF, Week, Day, Exercise with its set type in brackets, Sets, Reps as a target or range, Reps Achieved,
Weight with kg, Objective, Notes; blank rows between workouts), with its quirks: a DNF workout, rep ranges, a
note about dumbbells, uneven spacing, a bracket that is part of the name. Never Alex's real data."""
import io

HEADINGS = ["Date", "Week", "Day", "Exercise", "Sets", "Reps", "Reps Achieved", "Weight", "Objective", "Notes"]


def _rows():
    rows = []

    def workout(day, week, name, sets):
        for exercise, reps, done, weight, objective, note in sets:
            rows.append([day, week, name, exercise, "1", reps, done, weight, objective, note])
        rows.append([""] * len(HEADINGS))

    workout("6/10/2026", "1", "Upper 1", [
        ("Bench   press (warm-up)", "12-15", "15", "20kg", "Warm-up", ""),
        ("Bench press (working)", "5-8", "8", "40kg", "To failure", ""),
        ("Bench press (working)", "5-8", "7", "40kg", "Near failure", ""),
        ("Incline press (working)", "8-12", "10", "14kg", "To failure", "dumbbells, 14 each"),
        ("Lat pulldown - wide grip (working)", "10-12", "12", "55kg", "To failure", "go up to 57-60kg next week"),
        ("Lateral raise (working)", "12-15", "15", "8kg", "Find groove", ""),
    ])
    workout("8/10/2026", "1", "Lower 1", [
        ("Squat (warm-up)", "8-10", "10", "40kg", "Warm-up", ""),
        ("Squat (working)", "4-6", "6", "80kg", "To failure", ""),
        ("Leg press (high foot) (working)", "10-15", "21", "120kg", "To failure", "too easy"),
        ("Romanian deadlift (working)", "6-10", "8", "70kg", "Near failure", "knee felt a bit off"),
    ])
    workout("10/10/2026", "1", "Upper 2", [
        ("Overhead press (working)", "6-8", "6", "30kg", "To failure", ""),
        ("Seated row (working)", "8-12", "12", "50kg", "To failure", ""),
    ])
    workout("DNF", "1", "Lower 2", [
        ("Deadlift (working)", "3-5", "", "", "To failure", ""),
        ("Leg curl (working)", "10-12", "", "", "To failure", ""),
    ])
    workout("13/10/2026", "2", "Upper 1", [
        ("Bench press (warm-up)", "12-15", "15", "20kg", "Warm-up", ""),
        ("Bench press (working)", "5-8", "9", "40kg", "To failure", ""),
        ("Bench press (working)", "5-8", "8", "40kg", "Near failure", ""),
        ("Incline press (working)", "8-12", "10", "14kg", "To failure", "dumbbells"),
        ("Lat pulldown - wide grip (working)", "10-12", "12", "57kg", "To failure", ""),
        ("Lateral raise (working)", "12-15", "", "", "Find groove", "skipped, shoulder"),
    ])
    return rows


def logbook_csv() -> bytes:
    import csv

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADINGS)
    writer.writerows(_rows())
    return out.getvalue().encode("utf-8")


def logbook_xlsx() -> bytes:
    """One tab a workout, with no Day column (the tab's name is the workout's)."""
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    tabs: dict[str, list] = {}
    for row in _rows():
        if any(row):
            tabs.setdefault(row[2], []).append([row[0], row[1], row[3], row[4], row[5], row[6], row[7], row[8], row[9]])
    for name, rows in tabs.items():
        sheet = book.create_sheet(name)
        sheet.append(["Date", "Week", "Exercise", "Sets", "Reps", "Reps Achieved", "Weight", "Objective", "Notes"])
        previous = None
        for row in rows:
            if previous is not None and row[0] != previous:
                sheet.append([None] * 9)
            sheet.append(row)
            previous = row[0]
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def wide_csv() -> bytes:
    """Another layout: a row an exercise, sets x reps in one cell, a column a set's result."""
    lines = [
        "Workout,Exercise,Plan,Set 1,Set 2,Set 3,Date",
        "Push,Bench press,3x8,60x8,60x7,60x6,1/10/2026",
        "Push,Dips,3x10,0x10,0x9,0x8,1/10/2026",
        ",,,,,,",
        "Pull,Barbell row,3x8,50x8,50x8,50x7,3/10/2026",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


# What Claude is recorded as answering for these (the tests' own: the live checks are evals/fixtures/gym.json)
MAPPING = {"columns": [
    {"table": "", "heading": heading, "field": field_name, "sure": True}
    for heading, field_name in zip(HEADINGS, ["date", "week", "workout", "exercise", "sets", "reps", "reps_done", "weight", "purpose", "notes"])
]}
MEANINGS = {
    "brackets": [{"index": 0, "meaning": "warm-up"}, {"index": 1, "meaning": "working"}, {"index": 2, "meaning": "name"}],
    "purposes": [{"index": 0, "category": "warm_up"}, {"index": 1, "category": "to_failure"}, {"index": 2, "category": "near_failure"}, {"index": 3, "category": "technique"}],
    "exercises": [],
    "notes": [],
}
