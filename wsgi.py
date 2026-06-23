import sys
import os
import importlib.util

# Get path of current file (wsgi.py)
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)

# ABSOLUTE FILE LOADER: Forces Python to read app.py regardless of modules
def load_module_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

try:
    # Try loading from root first
    app_path = os.path.join(project_root, 'app.py')
    if os.path.exists(app_path):
        app_module = load_module_from_path("app_core", app_path)
        app = app_module.app
    else:
        # Fallback to python_backend if root is missing
        app_path = os.path.join(project_root, 'python_backend', 'app.py')
        app_module = load_module_from_path("app_core", app_path)
        app = app_module.app
except Exception as e:
    raise ImportError(f"CRITICAL: Could not find or load app.py. Error: {str(e)}")

if __name__ == "__main__":
    app.run()

if __name__ == "__main__":
    app.run()
