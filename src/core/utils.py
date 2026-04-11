def ensure_dir(path):
    import os
    os.makedirs(path, exist_ok=True)
