# 📚 Story Manager: Your Personal Digital Library

Story Manager is a self-hosted digital library and reader for your personal collection of EPUBs and web novels. It provides a clean web interface to manage your books and leverages the power of FanFicFare to keep your favorite web novels up-to-date automatically.



---

## ✨ Core Features

* **Unified Library**: Manage both local EPUB files and web novels in one place.
* **EPUB Upload**: Easily upload your existing `.epub` files directly through the web UI.
* **Web Novel Tracking**: Simply add a URL, and InkWell will download the story and package it as an EPUB.
* **Automatic Updates**: A background scheduler periodically checks for new chapters for all your tracked web novels using FanFicFare.
* **Stub Protection**: InkWell is configured to **never delete old chapters**, so you won't lose content if an author removes it from the source to publish commercially.
* **API-First Design**: A robust backend API allows for integration with other applications, such as a future mobile e-reader or audiobook player.
* **(Future) Audiobook Conversion**: Planned integration for background text-to-speech conversion to turn any book in your library into an audiobook.

---

## 🛠️ Technology Stack

* **Backend**: Python with **FastAPI** for a high-performance API.
* **Web Novel Fetching**: **FanFicFare** library.
* **Task Scheduling**: **APScheduler** for periodic chapter updates.
* **Database**: **SQLite** for simple, file-based storage of metadata.
* **Frontend**: **React** (using Vite) for a modern, responsive user interface.
* **Containerization**: **Docker** for easy deployment.

---

## 🚀 Getting Started

### Local Development Setup

This project uses `uv` for python package management, `pyenv` for Python version management, and `nvm` for Node.js version management to ensure a consistent development environment.

#### Prerequisites

*   **uv**: Follow the official installation guides for your OS.
*   **pyenv**: Follow the official installation guides for your OS.
*   **nvm**: Follow the official `nvm` installation guide.
*   **Docker**: Required for running the application with Docker Compose.

#### Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/jalbertcory/story-manager.git
    cd story-manager
    ```

2.  **Set up the Backend (Python):**
    *   Install the required Python version (this will be read from the `.python-version` file):
        ```bash
        pyenv install
        ```
    *   Create and activate a virtual environment:
        ```bash
        # Create the virtual environment
        uv venv
        # Activate the virtual environment
        source .venv/bin/activate
        ```
    *   Install dependencies:
        ```bash
        uv pip install -e ".[dev]"
        ```

3.  **Set up the Database (PostgreSQL):**
    *   Start PostgreSQL in Docker:
        ```bash
        make run-db
        ```
    *   Create a `.env` file in the project root with the database configuration:
        ```bash
        DATABASE_URL=postgresql+psycopg://storyuser:storypass@localhost:5432/story_manager
        ```
    *   To stop the database: `docker stop story-manager-db`
    *   To start it again: `docker start story-manager-db`
    *   To remove it completely: `docker rm -f story-manager-db`

4.  **Run Database Migrations:**
    *   Apply the database schema migrations (make sure your virtual environment is activated):
        ```bash
        # Activate the virtual environment first
        source .venv/bin/activate
        # Run migrations
        alembic -c backend/alembic.ini upgrade head
        ```

5.  **Set up the Frontend (Node.js):**
    *   Install and use the required Node.js version (this will be read from the `.nvmrc` file):
        ```bash
        nvm install
        nvm use
        ```
    *   Install dependencies from the `frontend` directory:
        ```bash
        cd frontend
        npm install
        cd ..
        ```

6.  **Run the Application:**
    *   **Backend**:
        ```bash
        # From the project root
        make run-backend
        ```
    *   **Frontend**:
        ```bash
        # From the project root, in a separate terminal
        make run-ui
        ```

Your application should now be running!
*   Web UI: `http://localhost:5173`
*   API: `http://localhost:8000`

---

## 🐋 Deploy with Docker Compose

The easiest way to run Story Manager is with Docker Compose. This method sets up the application and all its dependencies in a containerized environment.

The web UI is exposed on port **7890**, and the API is on port **8000**.

### Data Persistence

The `docker-compose.yml` is configured to store persistent data on the host machine inside a `config` directory. When you first run the `docker compose up` command, Docker will automatically create this directory in the same folder where your `docker-compose.yml` file is located.

This `config` directory will contain the following subdirectories:
*   `config/library`: Stores your uploaded EPUB files and downloaded web novels.
*   `config/pgdata`: Stores the PostgreSQL database.

This setup ensures that your library and application data are preserved even if you stop or remove the container.

### Running the Application

To start the application, run the following command from the root of the repository:
```bash
docker compose up -d
```

### Publishing an updated base image to ghcr.io
1. make a personal access token (classic) in Github
2. run `docker login --username <username> --password <your_personal_access_token> ghcr.io`

### Using on Unraid

The provided `docker-compose.yml` is compatible with Unraid's Docker Compose Manager.

1.  **Copy the `docker-compose.yml` file** to a new directory on your Unraid server (e.g., `/mnt/user/appdata/story-manager`).
2.  **Review the Volume Mappings**: The `docker-compose.yml` uses relative paths for its volumes (`./config`). When you run it on Unraid, it will create the `config` directory inside the path you chose in step 1 (e.g., `/mnt/user/appdata/story-manager/config`). You don't need to edit the `docker-compose.yml` file if this is what you want.
3.  **Start the Container**: From the directory containing `docker-compose.yml`, run `docker compose up -d`.
4.  **Access Story Manager**: You can now access the web interface at `http://<UNRAID_HOST>:7890`.

---
