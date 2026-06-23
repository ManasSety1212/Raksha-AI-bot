import sys
import os

# Ensure the root directory is in the path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)

# Import the actual Flask app from app.py
from app import app

if __name__ == "__main__":
    app.run()
