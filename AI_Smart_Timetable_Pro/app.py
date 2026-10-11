import csv
import io
import json
import os
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "smart_timetable.db"
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///" + str(DB_PATH).replace("\\", "/"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db = SQLAlchemy(app)

# Keep the existing users/timetables table and column names compatible with the earlier ZIP.
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    class_name = db.Column(db.String(100), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    timetables = db.relationship("Timetable", backref="owner", lazy=True, cascade="all, delete-orphan")

class Timetable(db.Model):
    __tablename__ = "timetables"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    class_name = db.Column(db.String(100), nullable=False, default="")
    days_json = db.Column(db.Text, nullable=False)
    subjects_json = db.Column(db.Text, nullable=False)
    slots_json = db.Column(db.Text, nullable=False)
    timetable_json = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    @property
    def timetable(self): return json.loads(self.timetable_json)
    @property
    def days(self): return json.loads(self.days_json)
    @property
    def subjects(self): return json.loads(self.subjects_json)
    @property
    def slots(self): return json.loads(self.slots_json)

with app.app_context():
    db.create_all()

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access is required.", "error")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapped

def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None

@app.context_processor
def inject_user():
    return {"logged_in_user": current_user(), "now_year": datetime.utcnow().year}

def build_schedule(subjects, days, slots):
    # Deterministic round-robin scheduler: distribute subjects evenly and avoid same-subject repeats.
    result = {}
    previous_by_day = {}
    subject_counts = {subject: 0 for subject in subjects}
    for day_index, day in enumerate(days):
        result[day] = []
        last_subject = None
        for slot_index, slot in enumerate(slots):
            if slot == "☕ Break":
                result[day].append({"time": slot, "subject": "☕ Break"})
                continue
            available = sorted(subjects, key=lambda s: (subject_counts[s], (subjects.index(s) + day_index + slot_index) % len(subjects)))
            non_repeat = [s for s in available if s != last_subject]
            subject = (non_repeat or available)[0] if available else "Free / Study time"
            subject_counts[subject] += 1
            last_subject = subject
            result[day].append({"time": slot, "subject": subject})
    return result

def owned_timetable_or_404(timetable_id):
    return Timetable.query.filter_by(id=timetable_id, user_id=session.get("user_id")).first_or_404()

@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("admin_dashboard" if session.get("role") == "admin" else "dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        class_name = request.form.get("class_name", "").strip()
        if not full_name or not username or not password:
            flash("Please complete all required fields.", "error")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already taken.", "error")
        else:
            db.session.add(User(full_name=full_name, username=username,
                                password_hash=generate_password_hash(password), role="student", class_name=class_name))
            try:
                db.session.commit()
                flash("Account created. You can now sign in.", "success")
                return redirect(url_for("login"))
            except IntegrityError:
                db.session.rollback()
                flash("That username is already taken.", "error")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session["user_id"] = user.id
            session["role"] = user.role
            session["full_name"] = user.full_name
            flash(f"Welcome back, {user.full_name}.", "success")
            return redirect(url_for("admin_dashboard" if user.role == "admin" else "dashboard"))
        flash("Incorrect username or password.", "error")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    user = current_user()
    records = Timetable.query.filter_by(user_id=user.id).order_by(Timetable.created_at.desc()).all()
    return render_template("dashboard.html", user=user, records=records)

@app.route("/generator", methods=["GET", "POST"])
@login_required
def generator():
    if session.get("role") == "admin":
        flash("Use a student account to generate a personal timetable.", "info")
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:120] or "My Smart Timetable"
        class_name = request.form.get("class_name", "").strip()[:100] or current_user().class_name or "My Class"
        days = [d for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] if d in request.form.getlist("days")]
        subjects = list(dict.fromkeys([x.strip()[:80] for x in request.form.get("subjects", "").splitlines() if x.strip()]))
        if not days:
            flash("Choose at least one working day.", "error")
            return redirect(url_for("generator"))
        if len(subjects) < 2:
            flash("Add at least two subjects, one per line.", "error")
            return redirect(url_for("generator"))
        try:
            count = max(3, min(10, int(request.form.get("slots_per_day", 6))))
            duration = max(20, min(120, int(request.form.get("duration", 45))))
            break_after = max(0, min(count - 1, int(request.form.get("break_after", 3))))
            start = datetime.strptime(request.form.get("start_time", "09:00"), "%H:%M")
            break_duration = max(5, min(60, int(request.form.get("break_duration", 15))))
        except (ValueError, TypeError):
            flash("Check the time and period settings.", "error")
            return redirect(url_for("generator"))
        slots, current = [], start
        for i in range(count):
            end = current + timedelta(minutes=duration)
            slots.append(f"{current.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}")
            current = end
            if break_after and i + 1 == break_after and i + 1 < count:
                slots.append("☕ Break")
                current += timedelta(minutes=break_duration)
        schedule = build_schedule(subjects, days, slots)
        record = Timetable(title=title, class_name=class_name, days_json=json.dumps(days),
                           subjects_json=json.dumps(subjects), slots_json=json.dumps(slots),
                           timetable_json=json.dumps(schedule, ensure_ascii=False), user_id=current_user().id)
        db.session.add(record)
        db.session.commit()
        flash("Your timetable was generated and saved.", "success")
        return redirect(url_for("view_timetable", timetable_id=record.id))
    return render_template("generator.html")

@app.route("/timetable/<int:timetable_id>")
@login_required
def view_timetable(timetable_id):
    item = owned_timetable_or_404(timetable_id)
    return render_template("timetable.html", item=item)

@app.route("/timetable/<int:timetable_id>/rename", methods=["POST"])
@login_required
def rename_timetable(timetable_id):
    item = owned_timetable_or_404(timetable_id)
    title = request.form.get("title", "").strip()
    if not title:
        flash("Enter a timetable name.", "error")
    else:
        item.title = title[:120]
        db.session.commit()
        flash("Timetable renamed.", "success")
    return redirect(url_for("view_timetable", timetable_id=item.id))

@app.route("/timetable/<int:timetable_id>/delete", methods=["POST"])
@login_required
def delete_timetable(timetable_id):
    item = owned_timetable_or_404(timetable_id)
    db.session.delete(item)
    db.session.commit()
    flash("Timetable deleted.", "success")
    return redirect(url_for("dashboard"))

def timetable_payload(item):
    return {"id": item.id, "title": item.title, "class_name": item.class_name,
            "days": item.days, "subjects": item.subjects, "slots": item.slots,
            "timetable": item.timetable, "created_at": item.created_at.isoformat() if item.created_at else None}

@app.route("/timetable/<int:timetable_id>/export.json")
@login_required
def export_json(timetable_id):
    item = owned_timetable_or_404(timetable_id)
    data = json.dumps(timetable_payload(item), ensure_ascii=False, indent=2)
    buffer = io.BytesIO(data.encode("utf-8"))
    buffer.seek(0)
    return send_file(buffer, mimetype="application/json; charset=utf-8", as_attachment=True,
                     download_name=f"timetable-{item.id}.json", max_age=0)

# Backward-compatible endpoint used by links in the previous version.
@app.route("/api/timetable/<int:timetable_id>")
@login_required
def export_json_legacy(timetable_id):
    return jsonify(timetable_payload(owned_timetable_or_404(timetable_id)))

@app.route("/timetable/<int:timetable_id>/export.csv")
@login_required
def export_csv(timetable_id):
    item = owned_timetable_or_404(timetable_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Time"] + item.days)
    for index, slot in enumerate(item.slots):
        row = [slot]
        for day in item.days:
            entries = item.timetable.get(day, [])
            row.append(entries[index].get("subject", "") if index < len(entries) else "")
        writer.writerow(row)
    buffer = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    buffer.seek(0)
    return send_file(buffer, mimetype="text/csv; charset=utf-8", as_attachment=True,
                     download_name=f"timetable-{item.id}.csv", max_age=0)

@app.route("/admin")
@admin_required
def admin_dashboard():
    query = request.args.get("q", "").strip()
    users_query = User.query
    if query:
        users_query = users_query.filter(db.or_(User.full_name.ilike(f"%{query}%"), User.username.ilike(f"%{query}%"), User.class_name.ilike(f"%{query}%")))
    users = users_query.order_by(User.created_at.desc()).all()
    records = Timetable.query.order_by(Timetable.created_at.desc()).limit(30).all()
    return render_template("admin.html", users=users, records=records,
                           timetable_count=Timetable.query.count(), student_count=User.query.filter_by(role="student").count(), search_query=query)

@app.route("/admin/create-student", methods=["POST"])
@admin_required
def admin_create_student():
    full_name = request.form.get("full_name", "").strip()
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    class_name = request.form.get("class_name", "").strip()
    if not full_name or not username or len(password) < 8:
        flash("Enter a name, username and password with at least 8 characters.", "error")
    elif User.query.filter_by(username=username).first():
        flash("That username already exists.", "error")
    else:
        db.session.add(User(full_name=full_name, username=username, password_hash=generate_password_hash(password), class_name=class_name, role="student"))
        try:
            db.session.commit(); flash("Student account created.", "success")
        except IntegrityError:
            db.session.rollback(); flash("That username already exists.", "error")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "error")
    elif user.id == session.get("user_id") or user.role == "admin":
        flash("Admin accounts cannot be deleted here.", "error")
    else:
        db.session.delete(user); db.session.commit(); flash("Student and their saved timetables deleted.", "success")
    return redirect(url_for("admin_dashboard"))

@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We couldn't find that page or timetable."), 404

@app.errorhandler(500)
def server_error(_error):
    db.session.rollback()
    return render_template("error.html", code=500, message="Something went wrong. Check the terminal for the error details."), 500

@app.cli.command("create-admin")
def create_admin():
    """Create or promote an admin account with environment variables."""
    username = os.environ.get("ADMIN_USERNAME", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    full_name = os.environ.get("ADMIN_NAME", "Administrator").strip() or "Administrator"
    if not username or len(password) < 12:
        print("Set ADMIN_USERNAME and ADMIN_PASSWORD (at least 12 characters) before running flask create-admin.")
        return
    user = User.query.filter_by(username=username).first()
    if user:
        user.role = "admin"; user.password_hash = generate_password_hash(password); user.full_name = full_name
    else:
        db.session.add(User(full_name=full_name, username=username, password_hash=generate_password_hash(password), role="admin"))
    db.session.commit()
    print(f"Admin account '{username}' is ready.")

if __name__ == "__main__":
    app.run(debug=True)
