🏠 CypInvEst - Real Estate Management System
CypInvEst is a modern, high-performance real estate platform built with FastAPI. The project implements a role-based access control (RBAC) system with three distinct user personas: User, Agent, and Admin.

📂 Project Structure & Architecture
The project directory is organized as follows:

Plaintext
RealEstatePrj/
├── main.py                 # FastAPI Backend Entry Point
├── requirements.txt        # Project Dependencies
├── README.md               # Project Documentation
├── static/                 # Static Assets
│   ├── css/                # Stylesheets
│   └── htmlfotos/          # Project Images & Backgrounds
│       └── loginspage.png
└── templates/              # Jinja2 HTML Templates
    ├── setrole.html        # Landing / Role Selection
    ├── userlogin.html      # User Authentication
    ├── userregister.html   # User Registration
    ├── agentlogin.html     # Agent Authentication
    ├── agentregister.html  # Agent Registration
    ├── adminlogin.html     # Admin Authentication (Access Only)
    ├── home.html           # Main Dashboard (In-Progress)
    ├── about.html          # About Page
    └── search.html         # Property Search Page
🚀 Quick Start for Developers
1. Prerequisites
Ensure you have Python 3.8+ installed on your machine.

2. Install Dependencies
Run the following command to install the required libraries:

Bash
pip install fastapi uvicorn jinja2 python-multipart

fastapi: Backend framework.

uvicorn: To run the server.

jinja2: HTML templating engine.

python-multipart: To read form data (Login/Register).
3. Running the Server
Execute the application using Uvicorn with the reload flag enabled for development:

Bash
uvicorn backend:app --reload
The application will be available at http://127.0.0.1:8000.

🔑 Core Technologies & Logic
Backend (FastAPI): Selected for high performance and asynchronous capabilities. Utilizes dynamic URL patterns (/login/{role}) to minimize code redundancy and handle multiple roles through a single logic flow.

Frontend (Jinja2 & Glassmorphism): Integrated Jinja2 for dynamic error handling and data injection. The UI implements a modern Glassmorphism aesthetic with role-specific color palettes (Blue for Users, Orange for Agents, Red for Admins).

Authentication Flow:

In-Memory Store: Currently utilizes a Python dictionary (users) for user persistence. Migration to SQL (PostgreSQL/SQLite) is planned.

Admin Security: Registration for the Admin role is disabled on the frontend. Access is restricted to pre-defined administrative accounts within the backend.

Role Protection: Users are strictly restricted to their designated portals. For example, an Admin account cannot bypass security through the User login gate.

👥 Team Contribution Guidelines
Adding New Routes: When implementing a new view, ensure you define a corresponding @app.get("/route-name") decorator in main.py.

HTML Forms: Ensure the name attribute of input fields matches the FastAPI Form(...) parameters exactly (e.g., name="first_name").

CSS Standards: Maintain design consistency. Use the shadow and transition effects (e.g., box-shadow, .glass-box) defined in setrole.html as a reference for new components.

Version Control: Maintain clear and concise commit messages in English (e.g., git commit -m "Add property search filter logic").

📈 Roadmap
[x] Base Authentication & Role Selection System.

[ ] SQLite / PostgreSQL Database Migration.

[ ] User Dashboard & Advanced Search Engine.

[ ] Agent Property Upload & Management Portal.

[ ] Administrative Approval & Verification Workflow.

📧 Contact
For any technical queries or architectural discussions, please reach out to the repository owner.