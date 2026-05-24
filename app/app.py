from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tz_admissions"))

from database.db import DB_PATH, get_connection

app = Flask(__name__)

GRADE_POINTS = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1, "S": 0.5, "F": 0}


def calculate_points(subjects):
    principal_grades = [
        GRADE_POINTS.get(s["grade"].upper(), 0)
        for s in subjects
        if s["level"] == "principal"
    ]
    principal_grades.sort(reverse=True)
    return sum(principal_grades[:3])


def match_programs(subjects, conn):
    programs = conn.execute(
        """
        SELECT p.program_name, p.program_code,
               p.minimum_points, p.admission_capacity,
               p.duration_years, p.requirements_raw,
               u.name AS university_name, u.website, u.head_office
        FROM programs p
        JOIN universities u ON p.uni_id = u.uni_id
        WHERE p.requirements_raw IS NOT NULL
        """
    ).fetchall()

    student_points = calculate_points(subjects)
    results = []
    for prog in programs:
        min_pts = prog["minimum_points"] or 0
        if student_points >= min_pts:
            results.append(
                {
                    "program_name": prog["program_name"],
                    "program_code": prog["program_code"],
                    "university_name": prog["university_name"],
                    "university_website": prog["website"],
                    "location": prog["head_office"],
                    "minimum_points": min_pts,
                    "admission_capacity": prog["admission_capacity"],
                    "duration_years": prog["duration_years"],
                    "requirements_raw": prog["requirements_raw"],
                    "student_points": student_points,
                    "margin": student_points - min_pts,
                }
            )

    results.sort(key=lambda x: x["margin"], reverse=True)
    return results


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/match", methods=["POST"])
def match():
    data = request.get_json() or {}
    subjects = data.get("subjects", [])
    if not subjects:
        return jsonify({"error": "No subjects provided"}), 400

    conn = get_connection(DB_PATH)
    try:
        results = match_programs(subjects, conn)
    finally:
        conn.close()

    return jsonify({"results": results, "total": len(results)})


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)