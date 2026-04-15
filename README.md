# 🏠 CypInvEst - Real Estate Management System

CypInvEst is a modern, high-performance real estate platform built with **FastAPI**. The project implements a role-based access control (RBAC) system with three distinct user personas: **User**, **Agent**, and **Admin**.

---

## 📂 Project Structure & Architecture
The project directory is organized as follows:

```text
RealEstatePrj/
├── backend.py              # FastAPI Backend Entry Point
├── .gitignore              # Files ignored by Git (venv, pycache)
├── README.md               # Project Documentation
├── static/                 # Static Assets
│   ├── css/                # Stylesheets (style.css)
│   └── htmlfotos/          # Project Images & Backgrounds
│       └── loginspage.png
└── templates/              # Jinja2 HTML Templates
    ├── setrole.html        # Landing / Role Selection
    ├── choose_role.html    # Alternative Role Selection
    ├── userlogin.html      # User Authentication
    ├── userregister.html   # User Registration
    ├── agentlogin.html     # Agent Authentication
    ├── agentregister.html  # Agent Registration
    ├── adminlogin.html     # Admin Authentication
    ├── home.html           # Main Dashboard (In-Progress)
    ├── about.html          # About Page
    └── search.html         # Property Search Page
🚀 Quick Start for Developers
1. Prerequisites
Ensure you have Python 3.8+ installed on your machine.

2. Install Dependencies
Run the following command to install the required libraries:

pip install fastapi uvicorn jinja2 python-multipart

▶fastapi: Backend framework.

▶uvicorn: ASGI server to run the application.

▶jinja2: Template engine for rendering HTML.

▶python-multipart: Required for parsing form data during Login/Register.

3. Running the Server
Execute the application using Uvicorn with the reload flag enabled for development:

uvicorn backend:app --reload

The application will be available at: http://127.0.0.1:8000

🔑 Core Technologies & Logic
Backend (FastAPI): Selected for high performance. Utilizes dynamic URL patterns (/login/{role}) to minimize code redundancy.

Frontend (Jinja2 & Glassmorphism): Uses Jinja2 for dynamic data injection. The UI features a modern Glassmorphism aesthetic with role-specific color palettes (Blue: User, Orange: Agent, Red: Admin).

Authentication Flow:

In-Memory Store: Currently uses a Python dictionary for user persistence (Migration to SQL is planned).

Admin Security: Admin registration is disabled on the frontend. Access is restricted to pre-defined accounts.

Role Protection: Users are strictly restricted to their designated portals.

👥 Team Contribution Guidelines
Adding New Routes: Define a corresponding @app.get("/route-name") in backend.py.

HTML Forms: The name attribute of input fields must match the FastAPI Form(...) parameters exactly.

CSS Standards: Maintain consistency using the glass-box effects defined in the existing templates.

Version Control: Always work on the demoproject branch. Use clear commit messages (e.g., git commit -m "Add search filter logic").

---

## 👥 Team Collaboration (How to Contribute)

To keep the `main` branch stable, all developers **must** work on the `demoproject` branch. Follow these steps:

### 1. Clone the Project
If it's your first time, clone the repository:
```bash
git clone [https://github.com/EfeAskin/RealEstatePrj.git](https://github.com/EfeAskin/RealEstatePrj.git)
cd RealEstatePrj

Never code on main. Always switch to demoproject:
git checkout demoproject

Before you start coding, always pull the latest changes from the team:
git pull origin demoproject

After coding, send your work to GitHub:
git add .
git commit -m "feat: explain what you added (e.g., added login logic)"
git push origin demoproject

⚠️ Warning: Do not merge demoproject into main without consulting the repository owner.

📈 Roadmap
[x] Base Authentication & Role Selection System.

[ ] SQLite / PostgreSQL Database Migration.

[ ] User Dashboard & Advanced Search Engine.

[ ] Agent Property Upload & Management Portal.

[ ] Administrative Approval & Verification Workflow.

📧 Contact
For any technical queries or architectural discussions, please reach out to the repository owner.