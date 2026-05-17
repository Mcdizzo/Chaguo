# Soma — Tanzania University Admissions (Phase 1)

A web app that helps Form Six students in Tanzania see which undergraduate programs they may qualify for, using admission data from the [TCU](https://tcu.go.tz) guidebook.

Students enter A-Level subjects and grades; the app matches them against program minimum points and shows requirements from the official guidebook.

## Features

- **Student matcher** — Enter principal/subsidiary subjects and grades; get a ranked list of programs you meet on points.
- **Results search** — Filter matches by university name or program name.
- **Guidebook pipeline** — Download the latest TCU undergraduate PDF, extract programs with Groq, and store them in SQLite.
- **Resumable extraction** — Skips universities already loaded; adds missing universities from the guidebook automatically.

## Requirements

- Python 3.10+
- [Groq API key](https://console.groq.com/) (for guidebook extraction)

## Setup

```bash
git clone <your-repo-url>
cd project_uni

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_key_here
```

The database file lives at `tz_admissions/admissions.db`. It is created or updated when you run the extraction pipeline. You can ship a pre-populated database or build it yourself (see below).

## Run the web app

From the project root:

```bash
python app/app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

## Guidebook pipeline (optional)

Use this to refresh data from TCU when a new guidebook is published.

**1. Download the latest PDF** (and run extraction unless you pass `--no-extract`):

```bash
python tz_admissions/pipeline/update_guidebook.py
```

Options:

- `--force` — Re-download even if the local file looks up to date.
- `--no-extract` — Download only; do not call the extractor.

**2. Extract programs only** (e.g. if you already have the PDF):

```bash
python tz_admissions/pipeline/extract_requirements.py
```

Or point at a specific file:

```bash
python tz_admissions/pipeline/extract_requirements.py data/guidebooks/your_file.pdf
```

Useful flags:

- `--dry-run` — Split the PDF by university and log chunks; no API or database writes.
- `--max-universities N` — Process only the first N sections (for testing).

PDFs are stored under `data/guidebooks/`.

## Project layout

```
project_uni/
├── README.md
├── requirements.txt
├── .env                    # not committed — create locally
├── app/
│   ├── app.py              # Flask server
│   ├── templates/
│   └── static/
├── data/
│   └── guidebooks/         # TCU PDFs + download manifest
└── tz_admissions/
    ├── admissions.db       # SQLite database
    ├── database/
    │   ├── schema.sql
    │   └── db.py
    └── pipeline/
        ├── update_guidebook.py
        └── extract_requirements.py
```

## GitHub and this README

You do **not** need any special setting for GitHub to show this file.

1. Save this file as **`README.md`** in the **root** of the repository (same folder as `.gitignore`).
2. Commit and push:

   ```bash
   git add README.md
   git commit -m "Add README"
   git push
   ```

3. Open your repo on GitHub — the README body appears on the main page below the file list. That is automatic for `README.md`, `README.txt`, or `README` at the repo root.

If the README does not appear, check that it is on your default branch (usually `main` or `master`) and that the filename is exactly `README.md` (case matters on some systems).

## License

Add your license here if you publish the repo publicly.
