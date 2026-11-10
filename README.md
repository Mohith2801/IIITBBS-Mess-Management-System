# IIIT Bhubaneswar Mess Management System

Full-stack IWT project:
- Frontend: HTML, CSS, Bootstrap 5 and JavaScript
- Backend: Python Flask
- Database: SQLite

## User roles
1. Student: registers with an `@iiit-bh.ac.in` email, books meals for the upcoming week on Sunday, views booking/attendance/estimated fees, gives feedback and submits complaints.
2. Mess Management: updates the weekly menu and meal prices, views bookings, records actual meal attendance as Present/Absent, and manages complaints.

## Meal fees
- Breakfast: ₹28
- Lunch: ₹45
- Dinner: ₹40

The estimated weekly fee is calculated from the meals the student books. It is not an online payment gateway.

## Registration rule
The student's college ID is derived from the part of their email before `@iiit-bh.ac.in`. Example: `b423040@iiit-bh.ac.in` gives college ID `b423040`. The current implementation validates the email domain but does not send an OTP or verify mailbox ownership.

## Weekly booking rule
Booking is open on Sunday for the next Monday–Sunday week. Students can select or change their meal choices during that Sunday booking window. Management records actual attendance against the student's booking. Student dashboards display the management-recorded status.

## Run locally (Windows PowerShell)
1. Install Python 3.10+.
2. Open PowerShell in the project directory.
3. `py -m venv venv`
4. `venv\\Scripts\\Activate.ps1`
5. `pip install -r requirements.txt`
6. `python app.py`

## Login accounts
- Student: register using an email ending in `@iiit-bh.ac.in`; college ID is derived from the email prefix.
- Mess Management: `ms@iiit-bh.ac.in`. Initial demo password: `iiitbbsr`. Change it through email OTP before public deployment.

## Email OTP configuration
OTP delivery requires SMTP credentials. Copy `.env.example` values into your local environment or hosting provider's environment settings:
- `MAIL_SERVER` (for Gmail: `smtp.gmail.com`)
- `MAIL_PORT` (usually `587`)
- `MAIL_USERNAME` (sender mailbox)
- `MAIL_PASSWORD` (for Gmail, use an App Password; do not use your normal account password)
- `MAIL_DEFAULT_SENDER` (usually same as MAIL_USERNAME)
- `SECRET_KEY` (a long random value)

Without SMTP settings, the OTP email cannot be sent and password reset will display a configuration error. Do not put real mail passwords in source code or commit them to GitHub.

## Deployment on Render
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Add a strong `SECRET_KEY` environment variable.
- For SQLite persistence, attach a persistent disk and set `DATABASE_PATH` to a file on that disk. Without persistent storage, database records may be lost on redeploy/restart.

## Important academic-project limitations
- Email domain is checked, but OTP/email ownership verification is not implemented.
- No payment gateway is integrated; fees are calculated as an estimate from selected meals.
- This is a project demo, not an official campus service. Add CSRF protection, password reset, admin password management, backups and institutional verification before real use.
- Some menu words were unclear in the supplied photo and should be verified against the current official mess notice.
