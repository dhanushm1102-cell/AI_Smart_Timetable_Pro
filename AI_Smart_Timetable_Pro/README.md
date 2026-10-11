# AI Smart Timetable Generator — Pro (SQLite)

A clean, responsive Flask application with student registration/login, admin dashboard, timetable generation, per-student saved records, JSON/CSV downloads, print/PDF, and SQLite persistence.

## Important: keep your existing database

This version deliberately keeps the existing `users` and `timetables` table names and their columns compatible with the earlier SQLite ZIP. To keep your old admin/student accounts and saved timetables, **back up your current `smart_timetable.db`, then copy this ZIP's application files into your existing `AI_Smart_Timetable_SQLite` project folder without deleting or replacing `smart_timetable.db`**. If you extract to a new folder instead, copy your old `smart_timetable.db` into the new app folder before running it.

The database path is next to `app.py` and is created automatically only if it does not exist.

## Windows PowerShell setup

Open PowerShell inside the project folder:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If the virtual environment already exists, just activate it and install requirements.

### Existing admin account

Your existing admin account is retained if you keep the same database. Start the app:

```powershell
python app.py
```

Open http://127.0.0.1:5000.

### Create or reset an admin (optional)

Use a strong password of at least 12 characters:

```powershell
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "UseYourOwnStrongPassword123!"
$env:ADMIN_NAME = "Site Administrator"
python -m flask --app app create-admin
```

This promotes/resets the selected username, so don't run it unless you intend to set that admin password.

## Features

- Student registration and login with hashed passwords
- Admin-only dashboard and student account management
- Per-student timetable ownership checks
- Balanced timetable generation with selectable weekdays, subjects, start time, period duration, periods/day and break
- Saved timetable history, rename and delete
- JSON download (actual attachment), CSV download, browser print / Save as PDF
- Responsive student-friendly interface

## Notes

- This is a local development project. Before public deployment, set a strong `SECRET_KEY`, disable debug mode, add CSRF protection, and use HTTPS.
- Timetables are rule-generated; they do not solve all institutional constraints automatically.
