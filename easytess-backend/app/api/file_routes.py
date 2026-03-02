from flask import Blueprint, request, jsonify, session, current_app, send_from_directory, send_file
from werkzeug.utils import secure_filename
import os
import uuid
import json
from datetime import datetime
from app.utils.pdf_utils import convert_pdf_to_image

file_bp = Blueprint('file', __name__)

@file_bp.route('/api/upload', methods=['POST'])
def upload_file():
    if 'image' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    filename = secure_filename(file.filename)
    unique_id = str(uuid.uuid4())
    saved_filename = f"ocr_{unique_id}_{filename}"
    temp_folder = current_app.config['UPLOAD_TEMP_FOLDER']
    filepath = os.path.join(temp_folder, saved_filename)
    file.save(filepath)
    
    # Conversion PDF -> Image si nécessaire
    if filename.lower().endswith('.pdf'):
        try:
            image_filename = f"{os.path.splitext(saved_filename)[0]}.jpg"
            image_filepath = os.path.join(temp_folder, image_filename)
            convert_pdf_to_image(filepath, image_filepath)
            
            # On bascule sur l'image pour la suite du traitement
            saved_filename = image_filename
            filepath = image_filepath
        except Exception as e:
            return jsonify({'error': f'Erreur lors de la conversion PDF: {str(e)}'}), 500
    
    session['image_path'] = filepath
    session['filename'] = filename
    session['saved_filename'] = saved_filename
    
    return jsonify({
        'success': True, 
        'filename': filename, 
        'saved_filename': saved_filename,
        'url': f"/uploads_temp/{saved_filename}"
    })

@file_bp.route('/api/upload-batch', methods=['POST'])
def upload_batch():
    if 'images' not in request.files:
        return jsonify({'error': 'No files part'}), 400
    
    files = request.files.getlist('images')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No selected files'}), 400
    
    temp_folder = current_app.config['UPLOAD_TEMP_FOLDER']
    uploaded = []
    for file in files:
        if file.filename == '':
            continue
        filename = secure_filename(file.filename)
        unique_id = str(uuid.uuid4())
        saved_filename = f"ocr_{unique_id}_{filename}"
        filepath = os.path.join(temp_folder, saved_filename)
        file.save(filepath)
        
        # Conversion PDF -> Image si nécessaire
        if filename.lower().endswith('.pdf'):
            try:
                image_filename = f"{os.path.splitext(saved_filename)[0]}.jpg"
                image_filepath = os.path.join(temp_folder, image_filename)
                convert_pdf_to_image(filepath, image_filepath)
                saved_filename = image_filename
            except Exception as e:
                uploaded.append({
                    'filename': filename,
                    'saved_filename': None,
                    'error': f'Erreur conversion PDF: {str(e)}'
                })
                continue
        
        uploaded.append({
            'filename': filename,
            'saved_filename': saved_filename
        })
    
    return jsonify({
        'success': True,
        'files': uploaded
    })

@file_bp.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve permanent uploaded files (entity references, templates)"""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

@file_bp.route('/uploads_temp/<path:filename>')
def uploaded_temp_file(filename):
    """Serve temporary uploaded files (OCR sessions)"""
    return send_from_directory(current_app.config['UPLOAD_TEMP_FOLDER'], filename)

@file_bp.route('/api/export-json')
def export_json():
    resultats = session.get('resultats', {})
    export_data = {
        'filename': session.get('filename'),
        'date': datetime.now().isoformat(),
        'resultats': resultats
    }
    return jsonify(export_data)

@file_bp.route('/api/export-json-file', methods=['GET', 'POST'])
def export_json_file():
    if request.method == 'POST':
        data = request.json
        resultats = data.get('resultats', {})
        filename_base = data.get('filename', 'resultats')
    else:
        resultats = session.get('resultats', {})
        filename_base = session.get('filename', 'resultats')

    export_data = {
        'filename': filename_base,
        'date': datetime.now().isoformat(),
        'resultats': resultats
    }
    
    filename = f"export_{filename_base}.json"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    return send_file(filepath, as_attachment=True, download_name=filename)

@file_bp.route('/api/export-json-batch', methods=['POST'])
def export_json_batch():
    data = request.json or {}
    resultats_batch = data.get('resultats_batch', [])
    
    export_data = {
        'date': datetime.now().isoformat(),
        'total': len(resultats_batch),
        'resultats_batch': resultats_batch
    }
    
    filename = f"export_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    return send_file(filepath, as_attachment=True, download_name=filename)
