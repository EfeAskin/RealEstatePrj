🏠 CypInvEst - Real Estate Management System
CypInvEst is a modern, high-performance real estate platform built with FastAPI. The project implements a role-based access control (RBAC) system with three distinct user personas: User, Agent, and Admin.

📂 Project Structure & Architecture
The project directory is organized as follows:

Plaintext
RealEstatePrj/
├── backend.py              # FastAPI Backend Entry Point
├── database.py             # Data Persistence & Hash Logic
├── requirements.txt        # Project Dependencies (bcrypt, fastapi, etc.)
├── .gitignore              # Files ignored by Git (venv, pycache)
├── README.md               # Project Documentation
├── static/                 # Static Assets
│   ├── css/
│   │   └── style.css       # Stylesheets
│   └── htmlfotos           # Project Images & Backgrounds
├── routers/                # Modular Route Handlers
│   ├── __init__.py         # Makes the directory a Python package
│   ├── auth.py             # Authentication Logic (Login/Register)
│   ├── profile.py          # Profile & Role Management Logic
│   └── listings.py         # Property Listings & Management Logic
├── services/               # Logic for specific business operations
└── templates/              # Jinja2 HTML Templates
    ├── setrole.html        # Landing / Role Selection
    ├── choose_role.html    # Alternative Role Selection
    ├── userlogin.html      # User Authentication
    ├── userregister.html   # User Registration
    ├── agentlogin.html     # Agent Authentication
    ├── agentregister.html  # Agent Registration
    ├── adminlogin.html     # Admin Authentication
    ├── home.html           # Main Dashboard
    ├── about.html          # About Page
    ├── search.html         # Property Search Page
    ├── profile_base.html   # Base Layout for Profile Pages
    ├── personal_info.html  # Personal Data Management
    ├── messages.html       # Messaging System (In-Progress)
    ├── favourites.html     # Saved Properties
    ├── transactions.html   # User Transaction History
    ├── properties.html     # Agent's Property Management
    ├── requests.html       # Agent's Customer Requests
    ├── payment.html        # Payment & Booking Calculation
    ├── dashboard.html      # Admin Overview
    ├── users.html          # Admin User Management
    ├── approving.html      # Admin Property Approval
    ├── system_logs.html    # Admin System Logs
    └── sales_logs.html     # Admin Sales Reports
🚀 Quick Start for Developers
1. Prerequisites
Ensure you have Python 3.8+ installed on your machine.

2. Install Dependencies
Run the following command to install the required libraries:

Bash
pip install -r requirements.txt
Core Libraries:

fastapi: Backend framework.

uvicorn: ASGI server.

jinja2: Template engine.

bcrypt: Secure password hashing.

python-multipart: Parsing form data.

3. Running the Server
Execute the application using Uvicorn with the reload flag enabled for development:

Bash
uvicorn backend:app --reload
The application will be available at: http://127.0.0.1:8000

🔑 Core Technologies & Logic
Backend (FastAPI): Modular architecture using APIRouter for clean code separation. Routes are organized into auth, profile, and listings.

Security: Passwords are never stored in plain text. Utilizing bcrypt for hashing and verification.

Frontend (Jinja2 & Glassmorphism): Dynamic data injection. The UI features a modern Glassmorphism aesthetic with role-specific color palettes (Blue: User, Orange: Agent, Red: Admin).

Authentication & Role Logic:

In-Memory Store: Uses database.py for persistence (Migration to SQL planned).

Dynamic Profiles: Profile fields adapt based on the role (e.g., IBAN/Company for Agents).

Role Switching: Users can upgrade to Agent status via a secure verification process.

👥 Team Contribution Guidelines
Modular Routing: Do not clutter backend.py. Define new routes in their respective files under the routers/ directory. Use APIRouter and include them in backend.py using app.include_router().

HTML Forms: Ensure the name attribute of HTML input fields matches the FastAPI Form(...) parameter names exactly to avoid 422 Unprocessable Entity errors.

CSS Standards: Maintain the Glassmorphism aesthetic. Use the existing classes in style.css for consistency across all dashboards.

Dependency Management: If you install a new package, immediately update the requirements.txt file using pip freeze > requirements.txt.

---

## 👥 Team Collaboration (How to Contribute)

To maintain the stability of the main branch, all development must occur on the demoproject branch. Follow these steps to ensure a smooth workflow:

### 1. Setup & Sync
If it's your first time, clone the repository and switch to the development branch:
```bash
git clone https://github.com/EfeAskin/RealEstatePrj.git
cd RealEstatePrj
git checkout demoproject

Never code on main. Always switch to demoproject:
git checkout demoproject

2. Daily Workflow
Before you start coding, always pull the latest changes to avoid merge conflicts:

git pull origin demoproject

3. Committing Changes

# Check your changes
git status

# Add files to staging
git add .

# Commit with a meaningful message
git commit -m "feat: explain what you added"

# Push to the remote branch
git push origin demoproject

4. Safety Rules
Branch Protection: Never push directly to main.

Environment Files: Do not commit .env files or sensitive API keys.

Merge Requests: Do not merge demoproject into main without consulting the repository owner.

⚠️ Warning: Do not merge demoproject into main without consulting the repository owner.

📈 Roadmap
[x] Base Authentication & Role Selection System.

[x] Secure Password Hashing (Bcrypt).

[x] Dynamic Profile Management & Role Switching.

[x] Modular Routing Architecture (Auth, Profile, Listings).

[ ] SQLite / PostgreSQL Database Migration.

[ ] User Dashboard & Advanced Search Engine.

[ ] Agent Property Upload & Management Portal.

[ ] Administrative Approval & Verification Workflow.

📧 Contact
For any technical queries or architectural discussions, please reach out to the repository owner.
