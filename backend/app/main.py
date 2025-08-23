from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, HttpUrl
from pathlib import Path

# Import the main function from FanFicFare's CLI module
from fanficfare.cli import main as fff_main

app = FastAPI(title="Story Manager")

class WebNovelRequest(BaseModel):
    url: HttpUrl

@app.post("/api/books/add_web_novel", status_code=status.HTTP_201_CREATED)
async def add_web_novel(request: WebNovelRequest):
    """
    Downloads a web novel from a given URL using FanFicFare and saves it to the library.
    """
    try:
        # Get the directory of the current script to base paths on.
        # .resolve() makes it an absolute path.
        app_dir = Path(__file__).parent.resolve()

        # Path to personal.ini is inside the app directory.
        ini_path = app_dir / "personal.ini"

        # Path to the library is two levels up from the app directory (i.e., at the project root).
        library_path = (app_dir / ".." / ".." / "library").resolve()

        # Ensure the library directory exists; create it if it doesn't.
        library_path.mkdir(exist_ok=True)

        # Check if the personal.ini file exists. If not, it's a server configuration error.
        if not ini_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error: personal.ini not found."
            )

        # Construct arguments for fanficfare's CLI main function, simulating a command-line call:
        # fff --personal-ini /path/to/ini --output-dir /path/to/library <url>
        args = [
            "--personal-ini", str(ini_path),
            "--output-dir", str(library_path),
            str(request.url)
        ]

        # Call FanFicFare. It returns 0 on success and a non-zero integer on failure.
        # FanFicFare prints its own detailed logs/errors to stdout/stderr.
        result = fff_main(args)

        if result == 0:
            # Successfully downloaded or updated.
            return {"status": "success", "message": "Book processed successfully."}
        else:
            # FanFicFare failed. Its own logs will have the specific reason.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"FanFicFare failed to download the story. Error code: {result}. "
                       "Check server logs for more details from FanFicFare."
            )

    except Exception as e:
        # Catch any other unexpected exceptions from the library or our code.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {str(e)}"
        )

@app.get("/")
def read_root():
    """A simple root endpoint to confirm the server is running."""
    return {"message": "Welcome to the Story Manager API"}
