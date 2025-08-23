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

### Prerequisites

* Python 3.13+
* Node.js 20+
* Docker (Recommended)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/jalbertcory/story-manager.git](https://github.com/jalbertcory/story-manager.git)
    cd story-manager
    ```

2.  **Backend Setup:**
    ```bash
    cd backend
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Frontend Setup:**
    ```bash
    cd frontend
    npm install
    ```

4.  **Configuration:**
    Create a `.env` file in the `backend` directory and configure the necessary variables (e.g., `LIBRARY_PATH`).

5.  **Run the application:**
    * Start the backend server from the `backend` directory.
    * Start the frontend development server from the `frontend` directory.

---
