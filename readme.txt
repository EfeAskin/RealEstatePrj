===============================================================================
 CypInvEst - Real Estate Management System
 Installation & Setup Instructions (readme.txt)
===============================================================================

A FastAPI + Neon PostgreSQL web application with an AI semantic-search and
recommendation engine (OpenAI + pgvector). These instructions install the system
on a clean machine and get it running in a web browser.


-------------------------------------------------------------------------------
1. PREREQUISITES
-------------------------------------------------------------------------------
 - Python 3.11 (3.10+ acceptable). Verify with:  python --version
 - pip (ships with Python).
 - An internet connection. The database (Neon) and the AI features (OpenAI) are
   cloud services accessed over the network.
 - A modern web browser (Chrome, Edge, Firefox).
 - Operating system: developed and tested on Windows 11 (PowerShell). macOS and
   Linux also work; only the virtual-environment activation command differs
   (noted in step 3).


-------------------------------------------------------------------------------
2. OBTAIN THE SOURCE CODE
-------------------------------------------------------------------------------
 Copy the project folder "RealEstatePrj" from the CD to your hard drive,
 e.g. C:\RealEstatePrj

 Open a terminal (PowerShell on Windows) and change into that folder:

     cd C:\RealEstatePrj


-------------------------------------------------------------------------------
3. CREATE A VIRTUAL ENVIRONMENT AND INSTALL DEPENDENCIES
-------------------------------------------------------------------------------
 Create an isolated Python environment:

     python -m venv venv

 Activate it:
     Windows (PowerShell):   .\venv\Scripts\Activate.ps1
     Windows (cmd.exe):      venv\Scripts\activate.bat
     macOS / Linux:          source venv/bin/activate

 Install all required libraries:

     pip install -r requirements.txt

 This installs FastAPI, Uvicorn, Jinja2, psycopg2 (PostgreSQL driver), bcrypt,
 the OpenAI SDK, pgvector, and the other dependencies.


-------------------------------------------------------------------------------
4. CONFIGURE ENVIRONMENT VARIABLES (.env)
-------------------------------------------------------------------------------
 The application reads its secrets from a file named ".env" in the project root.
 A ready-to-use .env (pointing at the project's cloud database) is included on
 the CD - if present, you may skip to step 6.

 If you need to create it, make a file called ".env" containing:

     DATABASE_URL=postgresql://<user>:<password>@<host>.neon.tech/<db>?sslmode=require
     OPENAI_API_KEY=sk-...            (optional - see note below)

 Notes:
  - DATABASE_URL is the Neon PostgreSQL connection string (required).
  - OPENAI_API_KEY enables AI semantic search and recommendations. If it is
    omitted, the system still runs and search automatically falls back to
    ordinary keyword search - no errors.
  - Do NOT commit or share the .env file; it contains credentials.


-------------------------------------------------------------------------------
5. DATABASE SETUP  (only when provisioning a NEW database)
-------------------------------------------------------------------------------
 If you are using the provided cloud database (the bundled .env), the schema and
 data already exist - SKIP this step and go to step 6.

 To set up a fresh Neon database:
  (a) Create a Neon project at https://neon.tech and copy its connection string
      into DATABASE_URL (step 4).
  (b) Apply the schema migrations (creates the pgvector extension, the embedding
      columns, and the supporting tables):

          python scripts/run_migration.py scripts/migrations/001_ai_foundation.sql
          python scripts/run_migration.py scripts/migrations/002_adopt_reference_best_practices.sql

  (c) (Optional, requires OPENAI_API_KEY) Generate the search embeddings for the
      existing properties:

          python scripts/backfill_embeddings.py


-------------------------------------------------------------------------------
6. RUN THE APPLICATION
-------------------------------------------------------------------------------
 Start the web server:

     uvicorn backend:app --reload

 (Equivalently:  python backend.py)

 When you see "Application startup complete", open a browser at:

     http://127.0.0.1:8000

 Press CTRL+C in the terminal to stop the server.


-------------------------------------------------------------------------------
7. (OPTIONAL) VERIFY THE INSTALLATION
-------------------------------------------------------------------------------
 Run the offline test suite (no database or API key required):

     python tests/test_ai_offline.py

 It prints PASS for each check and "ALL PASS" at the end.


-------------------------------------------------------------------------------
8. TROUBLESHOOTING
-------------------------------------------------------------------------------
 - "ModuleNotFoundError": the virtual environment is not active, or
   dependencies were not installed. Repeat step 3.
 - "Port 8000 is already in use": run on another port, e.g.
       uvicorn backend:app --reload --port 8001
 - Database connection errors: check DATABASE_URL in .env and your internet
   connection; the Neon string must end with "?sslmode=require".
 - On Windows, if Turkish characters cause a console error when running the
   helper scripts, prefix the command with:  set PYTHONIOENCODING=utf-8
 - Search returns keyword results only: OPENAI_API_KEY is missing or invalid;
   add a valid key to .env to enable AI semantic search.

===============================================================================
