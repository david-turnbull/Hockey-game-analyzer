# NHL Hockey Analytics Platform (Hockey-Ops)

A professional, portfolio-quality internal hockey operations analytics platform designed for analysts, scouts, and coaching staff. This platform enables the selection of NHL seasons, teams, and games to perform in-depth event and player performance analysis, with an interactive shot map, shift visualization, and analytical research capabilities.

---

## Technical Stack

- **Backend**: Python 3.11+, Flask (Application Factory, Blueprints)
- **Database**: SQLite (for development), SQLAlchemy ORM (SQLAlchemy 2.0+)
- **Frontend**: HTML5, CSS3 (Vanilla design, dark theme, custom responsive grid), Jinja2 Templates
- **Testing**: pytest

---

## Directory Structure

```
hockey-analytics-platform/
├── app/                      # Main Flask application packages
│   ├── __init__.py           # Application Factory
│   ├── config.py             # Environment configurations
│   ├── models/               # SQLAlchemy ORM models
│   ├── routes/               # Flask blueprints
│   ├── static/               # CSS, JS, and image assets
│   └── templates/            # Jinja2 HTML templates
├── data_pipeline/            # Data Ingestion and Transformation
├── scripts/                  # Command-line utility scripts
│   └── initialise_database.py
├── tests/                    # Pytest test suite
├── requirements.txt          # Third-party python dependencies
└── run.py                    # Entry point to run the application
```

---

## Installation & Setup

### 1. Prerequisites
- Python 3.11 or higher installed on your system.

### 2. Environment Configuration
Clone the repository and navigate into the workspace. Create and activate a virtual environment:

#### Windows (PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

#### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the dependencies:
```bash
pip install -r requirements.txt
```

### 3. Database Initialization
Run the schema creation and database seeding utility script to create the local SQLite database (`hockey.db`) with appropriate tables and initial seeding records:
```bash
python scripts/initialise_database.py
```

---

## Running the Application

To start the Flask development server:
```bash
python run.py
```
By default, the server will start at [http://127.0.0.1:5000/](http://127.0.0.1:5000/). Open this address in your browser to view the Diagnostics dashboard.

---

## Running the Tests

To run the full suite of automated tests using pytest:
```bash
python -m pytest
```
To run tests with code coverage:
```bash
python -m pytest --cov=app tests/
```
