#!/bin/bash
set -e

echo "🚀 Starting the setup process..."

# Backend setup
echo "🐍 Setting up the Python backend..."
if ! command -v pyenv &> /dev/null
then
    echo "pyenv could not be found, please install it first."
    exit 1
fi
pyenv install --skip-existing

if ! command -v uv &> /dev/null
then
    echo "uv could not be found, please install it first."
    exit 1
fi
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
echo "✅ Backend setup complete."

# Database setup
echo "🐘 Setting up the PostgreSQL database..."
if ! command -v docker &> /dev/null
then
    echo "Docker could not be found, please install it first."
    exit 1
fi

if [ ! "$(docker ps -q -f name=story-manager-db)" ]; then
    if [ "$(docker ps -aq -f status=exited -f name=story-manager-db)" ]; then
        # container exists but is stopped
        echo "Starting existing story-manager-db container..."
        docker start story-manager-db
    else
        # container does not exist
        echo "Creating and starting new story-manager-db container..."
        docker run -d \
          --name story-manager-db \
          -e POSTGRES_DB=story_manager \
          -e POSTGRES_USER=storyuser \
          -e POSTGRES_PASSWORD=storypass \
          -p 5432:5432 \
          postgres:15
    fi
fi

echo "DATABASE_URL=postgresql+psycopg://storyuser:storypass@localhost:5432/story_manager" > .env
echo "✅ .env file created."

echo "⏳ Running database migrations..."
source .venv/bin/activate
alembic -c backend/alembic.ini upgrade head
echo "✅ Database migrations complete."

# Frontend setup
echo "⚛️ Setting up the Node.js frontend..."
if ! command -v nvm &> /dev/null
then
    echo "nvm could not be found, please install it first."
    exit 1
fi

# In a subshell to avoid changing the current shell's node version
(
  export NVM_DIR="$HOME/.nvm"
  [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
  nvm install
  nvm use
  cd frontend
  npm install
)
echo "✅ Frontend setup complete."

echo "🎉 Setup complete! You can now run the application."
