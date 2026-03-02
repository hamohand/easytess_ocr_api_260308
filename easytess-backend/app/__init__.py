from flask import Flask
from flask_cors import CORS
import os
import logging
from config import Config

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Extensions
    CORS(app, resources={r"/*": {"origins": "*"}})
    
    # Ensure directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_TEMP_FOLDER'], exist_ok=True)
    entities_folder = app.config['ENTITIES_FOLDER']
    os.makedirs(entities_folder, exist_ok=True)
    
    # Initialize Services
    from app.services.entity_manager import EntityManager
    app.entity_manager = EntityManager(entities_folder)
    
    # Register Blueprints
    from app.api.ocr_routes import ocr_bp
    from app.api.entity_routes import entity_bp
    from app.api.file_routes import file_bp
    from app.api.docx_routes import docx_bp
    from app.api.document_routes import document_bp
    
    app.register_blueprint(ocr_bp)
    app.register_blueprint(entity_bp)
    app.register_blueprint(file_bp)
    app.register_blueprint(docx_bp)
    app.register_blueprint(document_bp)
    
    @app.route('/')
    def index():
        return {
            "message": "EasyTess API is running",
            "endpoints": {
                "ocr": "/api/analyser",
                "entities": "/api/entites",
                "upload": "/api/upload"
            }
        }
    
    return app
