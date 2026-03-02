import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev_secret_key'
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')          # Fichiers permanents (entités, templates)
    UPLOAD_TEMP_FOLDER = os.path.join(BASE_DIR, 'uploads_temp') # Fichiers temporaires (OCR, sessions)
    ENTITIES_FOLDER = os.path.join(BASE_DIR, 'entities')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'tiff', 'pdf', 'docx'}
    
    # Tesseract path if needed (windows)
    # TESSERACT_CMD = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'
