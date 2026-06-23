import sys
import os

# Get path of current file (wsgi.py)
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)

# Force search in subfolders if missing in root
backend_path = os.path.join(project_root, 'python_backend')
if os.path.exists(backend_path):
    sys.path.append(backend_path)

# Try to import from various possible sources
try:
    from app import app
except ImportError:
    try:
        from python_backend.app import app
    except ImportError:
        raise ImportError("CRITICAL: AI Bot 'app.py' not found in root or python_backend folder.")

if __name__ == "__main__":
    app.run()
