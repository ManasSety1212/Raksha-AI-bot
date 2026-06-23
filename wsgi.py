import sys
import os

# Get path of current file (wsgi.py)
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)

# Try to import from the uniquely named core file
try:
    from raksha_app import app
except ImportError as e:
    raise ImportError(f"CRITICAL: AI Bot 'raksha_app.py' not found. Error: {str(e)}")

if __name__ == "__main__":
    app.run()

if __name__ == "__main__":
    app.run()
