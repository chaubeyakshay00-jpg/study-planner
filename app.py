
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import sqlite3

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

app = Flask(__name__)
app.secret_key = "study-planner-change-this-secret"

DATABASE = Path(__file__).resolve().parent / "studyplanner.db"


# ---------------- DATABASE CONNECTION ----------------

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------- CREATE / UPDATE DATABASE ----------------

def create_table():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                hours INTEGER NOT NULL CHECK(hours BETWEEN 1 AND 24),
                date TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                priority TEXT NOT NULL DEFAULT 'Medium'
            )
        """)

        # Add priority to an existing database if it is missing.
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(tasks)"
            ).fetchall()
        }

        if "priority" not in columns:
            conn.execute("""
                ALTER TABLE tasks
                ADD COLUMN priority TEXT NOT NULL DEFAULT 'Medium'
            """)


# ---------------- VALIDATE FORM DATA ----------------

def validate_task_form(form):
    name = form.get("name", "").strip()
    subject = form.get("subject", "").strip()
    hours_text = form.get("hours", "").strip()
    date_text = form.get("date", "").strip()
    priority = form.get("priority", "Medium").strip()

    errors = []

    if not name or len(name) > 80:
        errors.append("Name is required and must be at most 80 characters.")

    if not subject or len(subject) > 120:
        errors.append("Subject is required and must be at most 120 characters.")

    try:
        hours = int(hours_text)
        if not 1 <= hours <= 24:
            errors.append("Study hours must be between 1 and 24.")
    except (ValueError, TypeError):
        hours = None
        errors.append("Enter a valid whole number of study hours.")

    try:
        parsed_date = datetime.strptime(date_text, "%Y-%m-%d")
        if parsed_date.strftime("%Y-%m-%d") != date_text:
            raise ValueError
    except (ValueError, TypeError):
        errors.append("Select a valid study date.")

    if priority not in ("Low", "Medium", "High"):
        errors.append("Select a valid priority.")

    if errors:
        return None, errors

    return {
        "name": name,
        "subject": subject,
        "hours": hours,
        "date": date_text,
        "priority": priority
    }, []


# ---------------- HOME PAGE / ADD TASK ----------------

@app.route("/", methods=["GET", "POST"])
def home():

    if request.method == "POST":
        values, errors = validate_task_form(request.form)

        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for("home"))

        with get_db() as conn:
            conn.execute("""
                INSERT INTO tasks
                    (name, subject, hours, date, completed, priority)
                VALUES (?, ?, ?, ?, 0, ?)
            """, (
                values["name"],
                values["subject"],
                values["hours"],
                values["date"],
                values["priority"]
            ))

        flash("Study task added successfully.", "success")
        return redirect(url_for("home"))

    # Search and filters
    search = request.args.get("q", "").strip()[:120]
    status = request.args.get("status", "all")

    if status not in ("all", "pending", "completed"):
        status = "all"

    date_filter = request.args.get("date", "").strip()

    if date_filter:
        try:
            datetime.strptime(date_filter, "%Y-%m-%d")
        except ValueError:
            date_filter = ""

    conditions = []
    params = []

    if search:
        conditions.append("(name LIKE ? OR subject LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if status == "pending":
        conditions.append("completed = 0")
    elif status == "completed":
        conditions.append("completed = 1")

    if date_filter:
        conditions.append("date = ?")
        params.append(date_filter)

    query = "SELECT * FROM tasks"

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += """
        ORDER BY date ASC,
        CASE priority
            WHEN 'High' THEN 1
            WHEN 'Medium' THEN 2
            ELSE 3
        END,
        id DESC
    """

    with get_db() as conn:
        tasks = conn.execute(query, params).fetchall()
        all_tasks = conn.execute(
            "SELECT * FROM tasks"
        ).fetchall()

    total_tasks = len(all_tasks)
    completed_tasks = sum(
        1 for task in all_tasks if task["completed"]
    )
    pending_tasks = total_tasks - completed_tasks

    progress = (
        round(completed_tasks / total_tasks * 100)
        if total_tasks else 0
    )

    today = date.today().isoformat()

    today_tasks = [
        task for task in tasks
        if task["date"] == today
    ]

    return render_template(
        "index.html",
        tasks=tasks,
        today_tasks=today_tasks,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        progress=progress,
        today=today,
        search=search,
        status=status,
        date_filter=date_filter
    )


# ---------------- EDIT TASK ----------------

@app.route("/edit/<int:task_id>", methods=["GET", "POST"])
def edit_task(task_id):

    with get_db() as conn:
        task = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()

    if task is None:
        flash("Task not found.", "error")
        return redirect(url_for("home"))

    if request.method == "POST":
        values, errors = validate_task_form(request.form)

        if errors:
            for error in errors:
                flash(error, "error")
            return redirect(url_for("edit_task", task_id=task_id))

        with get_db() as conn:
            conn.execute("""
                UPDATE tasks
                SET name = ?, subject = ?, hours = ?,
                    date = ?, priority = ?
                WHERE id = ?
            """, (
                values["name"],
                values["subject"],
                values["hours"],
                values["date"],
                values["priority"],
                task_id
            ))

        flash("Study task updated successfully.", "success")
        return redirect(url_for("home"))

    return render_template("edit.html", task=task)


# ---------------- MARK TASK COMPLETED ----------------

@app.route("/complete/<int:task_id>", methods=["POST"])
def complete_task(task_id):

    with get_db() as conn:
        cursor = conn.execute("""
            UPDATE tasks
            SET completed = 1
            WHERE id = ?
        """, (task_id,))

        found = cursor.rowcount > 0

    if found:
        flash("Task marked as completed.", "success")
    else:
        flash("Task not found.", "error")

    return redirect(url_for("home"))


# ---------------- DELETE TASK ----------------

@app.route("/delete/<int:task_id>", methods=["POST"])
def delete_task(task_id):

    # Delete by the actual database ID, not list position.
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id = ?",
            (task_id,)
        )

        found = cursor.rowcount > 0

    if found:
        flash("Task deleted successfully.", "success")
    else:
        flash("Task not found.", "error")

    return redirect(url_for("home"))


# ---------------- START APPLICATION ----------------

if __name__ == "__main__":
    create_table()
    app.run(debug=True)
