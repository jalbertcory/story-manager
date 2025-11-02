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
if ! command -v psql &> /dev/null
then
    echo "PostgreSQL not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y postgresql
fi

# Start the PostgreSQL service
sudo service postgresql start

# Check if the user 'storyuser' already exists
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='storyuser'" | grep -q 1; then
    echo "User 'storyuser' already exists."
else
    echo "Creating user 'storyuser'..."
    sudo -u postgres psql -c "CREATE USER storyuser WITH PASSWORD 'storypass';"
fi

# Check if the database 'story_manager' already exists
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='story_manager'" | grep -q 1; then
    echo "Database 'story_manager' already exists."
else
    echo "Creating database 'story_manager'..."
    sudo -u postgres psql -c "CREATE DATABASE story_manager OWNER storyuser;"
fi

echo "DATABASE_URL=postgresql+psycopg://storyuser:storypass@localhost:5432/story_manager" > .env
echo "✅ .env file created."

echo "⏳ Running database migrations..."
source .venv/bin/activate
alembic -c backend/alembic.ini upgrade head
echo "✅ Database migrations complete."

# Frontend setup
echo "⚛️ Setting up the Node.js frontend..."
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm

if ! command -v nvm &> /dev/null
then
    echo "nvm could not be found, please install it first."
    exit 1
fi

# In a subshell to avoid changing the current shell's node version
(
  nvm install
  nvm use
  cd frontend
  npm install
  npx playwright install-deps
  npx playwright install
)
echo "✅ Frontend setup complete."

echo "🎉 Setup complete! You can now run the application."
