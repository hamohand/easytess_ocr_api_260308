from flask import Blueprint, request, jsonify, session, current_app, Response
import os
import json
import uuid
import threading
import time
from app.services.ocr_engine import analyser_hybride

ocr_bp = Blueprint('ocr', __name__)

# Store for async batch jobs
_batch_jobs = {}
_batch_jobs_lock = threading.Lock()

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

def _resolve_image_path(filename, app=None):
    """Cherche un fichier dans uploads_temp d'abord, puis dans uploads."""
    from flask import current_app as _ca
    ctx = app or _ca
    temp_folder = ctx.config['UPLOAD_TEMP_FOLDER']
    perm_folder = ctx.config['UPLOAD_FOLDER']
    temp_path = os.path.join(temp_folder, filename)
    if os.path.exists(temp_path):
        return temp_path
    perm_path = os.path.join(perm_folder, filename)
    if os.path.exists(perm_path):
        return perm_path
    return None  # introuvable

def _analyser_un_fichier(image_path, filename, zones_config, cadre_reference):
    """Analyse un seul fichier — utilisé par le ThreadPoolExecutor."""
    try:
        resultats, alertes = analyser_hybride(image_path, zones_config, cadre_reference=cadre_reference)
        
        if resultats is None:
            return {
                'filename': filename,
                'success': False,
                'error': alertes
            }
        else:
            stats = {}
            for r in resultats.values():
                m = r.get('moteur', 'inconnu')
                stats[m] = stats.get(m, 0) + 1
            return {
                'filename': filename,
                'success': True,
                'resultats': resultats,
                'alertes': alertes,
                'stats_moteurs': stats
            }
    except Exception as e:
        return {
            'filename': filename,
            'success': False,
            'error': str(e)
        }


@ocr_bp.route('/api/analyser', methods=['POST'])
def api_analyser():
    data = request.json or {}
    print(f"DEBUG: /api/analyser received data: {data}")
    filename = data.get('filename')
    
    # 1. Determine Image Path
    image_path = None
    if filename:
        image_path = _resolve_image_path(filename)
    elif 'image_path' in session:
        image_path = session['image_path']
        
    if not image_path or not os.path.exists(image_path):
        return jsonify({'error': 'Image not found. Please upload first or provide filename.'}), 400
        
    # 2. Determine Entity/Zones
    entite_active = session.get('entite_active')
    
    if data.get('zones'):
        zones_config = data['zones']
    elif entite_active:
        zones_config = {z['nom']: {'coords': z['coords']} for z in entite_active['zones']}
    else:
        zones_config = {"Test": {"coords": [100, 100, 300, 200]}}
    
    cadre_reference = data.get('cadre_reference')
    
    try:
        resultats, alertes = analyser_hybride(image_path, zones_config, cadre_reference=cadre_reference)
        
        if resultats is None:
            return jsonify({
                'success': False,
                'error': alertes,
                'error_type': 'etiquettes_non_trouvees'
            }), 400
        
        session['resultats'] = resultats
        session['alertes'] = alertes
        
        stats = {}
        for r in resultats.values():
            m = r.get('moteur', 'inconnu')
            stats[m] = stats.get(m, 0) + 1
            
        return jsonify({
            'success': True, 
            'resultats': resultats, 
            'alertes': alertes, 
            'stats_moteurs': stats
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================
# BATCH SYNCHRONE (petit nombre de fichiers)
# =============================================

@ocr_bp.route('/api/analyser-batch', methods=['POST'])
def api_analyser_batch():
    data = request.json or {}
    filenames = data.get('filenames', [])
    zones_config = data.get('zones')
    cadre_reference = data.get('cadre_reference')
    
    if not filenames:
        return jsonify({'error': 'No filenames provided'}), 400
    
    upload_folder = current_app.config['UPLOAD_TEMP_FOLDER']
    resultats_batch = []
    reussis = 0
    echoues = 0
    
    for filename in filenames:
        image_path = _resolve_image_path(filename)
        
        if not image_path:
            resultats_batch.append({
                'filename': filename,
                'success': False,
                'error': f'Fichier non trouvé: {filename}'
            })
            echoues += 1
            continue
        
        result = _analyser_un_fichier(image_path, filename, zones_config, cadre_reference)
        resultats_batch.append(result)
        if result['success']:
            reussis += 1
        else:
            echoues += 1
    
    return jsonify({
        'success': True,
        'total': len(filenames),
        'reussis': reussis,
        'echoues': echoues,
        'resultats_batch': resultats_batch
    })


# =============================================
# BATCH ASYNC (grand nombre de fichiers)
# =============================================

@ocr_bp.route('/api/analyser-batch-async', methods=['POST'])
def api_analyser_batch_async():
    """Lance une analyse batch en arrière-plan.
    Traite les fichiers séquentiellement dans un thread unique avec le contexte Flask.
    Retourne immédiatement un job_id pour suivre la progression via SSE."""
    data = request.json or {}
    filenames = data.get('filenames', [])
    zones_config = data.get('zones')
    cadre_reference = data.get('cadre_reference')
    
    if not filenames:
        return jsonify({'error': 'No filenames provided'}), 400
    
    job_id = str(uuid.uuid4())
    app = current_app._get_current_object()
    
    job = {
        'status': 'running',
        'total': len(filenames),
        'completed': 0,
        'reussis': 0,
        'echoues': 0,
        'resultats_batch': [],
        'current_file': ''
    }
    
    with _batch_jobs_lock:
        _batch_jobs[job_id] = job
    
    def run_batch():
        with app.app_context():
            for filename in filenames:
                with _batch_jobs_lock:
                    job['current_file'] = filename
                
                image_path = _resolve_image_path(filename, app)
                if not image_path:
                    with _batch_jobs_lock:
                        job['resultats_batch'].append({
                            'filename': filename,
                            'success': False,
                            'error': f'Fichier non trouvé: {filename}'
                        })
                        job['completed'] += 1
                        job['echoues'] += 1
                    continue
                
                result = _analyser_un_fichier(image_path, filename, zones_config, cadre_reference)
                with _batch_jobs_lock:
                    job['resultats_batch'].append(result)
                    job['completed'] += 1
                    if result['success']:
                        job['reussis'] += 1
                    else:
                        job['echoues'] += 1
            
            with _batch_jobs_lock:
                job['status'] = 'done'
    
    thread = threading.Thread(target=run_batch, daemon=True)
    thread.start()
    
    return jsonify({
        'success': True,
        'job_id': job_id,
        'total': len(filenames)
    })


@ocr_bp.route('/api/batch-progress/<job_id>', methods=['GET'])
def api_batch_progress(job_id):
    """SSE endpoint — envoie la progression en temps réel."""
    def generate():
        while True:
            with _batch_jobs_lock:
                job = _batch_jobs.get(job_id)
            
            if not job:
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break
            
            payload = {
                'status': job['status'],
                'total': job['total'],
                'completed': job['completed'],
                'reussis': job['reussis'],
                'echoues': job['echoues'],
                'current_file': job['current_file']
            }
            
            if job['status'] == 'done':
                payload['resultats_batch'] = job['resultats_batch']
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                # Nettoyage après livraison
                with _batch_jobs_lock:
                    _batch_jobs.pop(job_id, None)
                break
            
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            time.sleep(0.5)
    
    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@ocr_bp.route('/api/batch-result/<job_id>', methods=['GET'])
def api_batch_result(job_id):
    """Polling fallback — retourne l'état courant du job."""
    with _batch_jobs_lock:
        job = _batch_jobs.get(job_id)
    
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    response = {
        'status': job['status'],
        'total': job['total'],
        'completed': job['completed'],
        'reussis': job['reussis'],
        'echoues': job['echoues'],
        'current_file': job['current_file']
    }
    
    if job['status'] == 'done':
        response['resultats_batch'] = job['resultats_batch']
    
    return jsonify(response)


# =============================================
# ANALYSE DE DOSSIER SERVEUR
# =============================================

@ocr_bp.route('/api/analyser-dossier', methods=['POST'])
def api_analyser_dossier():
    """Analyse tous les fichiers image d'un dossier côté serveur.
    Le dossier doit être dans uploads/ ou un chemin absolu autorisé."""
    data = request.json or {}
    dossier_path = data.get('dossier')
    zones_config = data.get('zones')
    cadre_reference = data.get('cadre_reference')
    
    if not dossier_path:
        return jsonify({'error': 'dossier path required'}), 400
    
    # Si chemin relatif, chercher dans uploads/
    upload_folder = current_app.config['UPLOAD_FOLDER']
    if not os.path.isabs(dossier_path):
        dossier_path = os.path.join(upload_folder, dossier_path)
    
    if not os.path.isdir(dossier_path):
        return jsonify({'error': f'Dossier non trouvé: {dossier_path}'}), 400
    
    # Lister les fichiers image
    filenames = []
    for f in sorted(os.listdir(dossier_path)):
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            filenames.append(f)
    
    if not filenames:
        return jsonify({'error': 'Aucun fichier image trouvé dans le dossier'}), 400
    
    # Lancer en mode async
    job_id = str(uuid.uuid4())
    max_workers = data.get('max_workers', 2)
    app = current_app._get_current_object()
    
    job = {
        'status': 'running',
        'total': len(filenames),
        'completed': 0,
        'reussis': 0,
        'echoues': 0,
        'resultats_batch': [],
        'current_file': ''
    }
    
    with _batch_jobs_lock:
        _batch_jobs[job_id] = job
    
    def run_folder_batch():
        with app.app_context():
            for filename in filenames:
                with _batch_jobs_lock:
                    job['current_file'] = filename
                
                image_path = os.path.join(dossier_path, filename)
                result = _analyser_un_fichier(image_path, filename, zones_config, cadre_reference)
                with _batch_jobs_lock:
                    job['resultats_batch'].append(result)
                    job['completed'] += 1
                    if result['success']:
                        job['reussis'] += 1
                    else:
                        job['echoues'] += 1
            
            with _batch_jobs_lock:
                job['status'] = 'done'
    
    thread = threading.Thread(target=run_folder_batch, daemon=True)
    thread.start()
    
    return jsonify({
        'success': True,
        'job_id': job_id,
        'total': len(filenames),
        'filenames': filenames
    })


# =============================================
# RÉSULTATS / CORRECTIONS (existant)
# =============================================

@ocr_bp.route('/api/resultats', methods=['GET', 'POST'])
def api_resultats():
    if request.method == 'POST':
        data = request.json
        resultats = session.get('resultats', {})
        
        for key, value in data.items():
            if key in resultats:
                resultats[key]['texte_final'] = value
                resultats[key]['texte_corrige_manuel'] = value
                resultats[key]['statut'] = 'corrigé'
        
        session['resultats'] = resultats
        session.modified = True
        return jsonify({'success': True})
    
    return jsonify(session.get('resultats', {}))

@ocr_bp.route('/api/corrections', methods=['GET'])
def api_corrections():
    resultats = session.get('resultats', {})
    alertes = session.get('alertes', [])
    zones_a_corriger = {k: v for k, v in resultats.items() if k in alertes}
    return jsonify(zones_a_corriger)


# =============================================
# APPARIEMENT RECTO/VERSO
# =============================================

@ocr_bp.route('/api/apparier-recto-verso', methods=['POST'])
def api_apparier_recto_verso():
    """
    Analyse deux images (recto/verso) d'une entité composite et vérifie
    qu'elles appartiennent à la même pièce d'identité.
    
    Body JSON:
    {
        "entite": "cni_dz",
        "image_recto": "filename_recto.jpg",
        "image_verso": "filename_verso.jpg"
    }
    
    Returns:
    {
        "success": true,
        "resultats_recto": { ... },
        "resultats_verso": { ... },
        "resultats_fusionnes": { ... },
        "appariement": {
            "apparie": true,
            "confiance": 0.92,
            "details": { "numero": {...}, "photo": {...} }
        }
    }
    """
    from app.services.document_matcher import apparier_documents
    from app.services.entity_manager import EntityManager
    
    data = request.json or {}
    entite_nom = data.get('entite')
    image_recto_filename = data.get('image_recto')
    image_verso_filename = data.get('image_verso')
    
    if not entite_nom:
        return jsonify({'error': 'Nom d\'entité manquant'}), 400
    if not image_recto_filename or not image_verso_filename:
        return jsonify({'error': 'Les deux images (recto et verso) sont requises'}), 400
    
    # Charger l'entité
    manager = current_app.entity_manager
    entite = manager.charger_entite(entite_nom)
    if not entite:
        return jsonify({'error': f'Entité "{entite_nom}" non trouvée'}), 404
    
    if not EntityManager.is_composite(entite):
        return jsonify({'error': f'L\'entité "{entite_nom}" n\'est pas composite (recto/verso)'}), 400
    
    pages = entite.get('pages', {})
    if 'recto' not in pages or 'verso' not in pages:
        return jsonify({'error': 'L\'entité composite doit avoir une page "recto" et une page "verso"'}), 400
    
    # Résoudre les chemins des images
    recto_path = _resolve_image_path(image_recto_filename)
    verso_path = _resolve_image_path(image_verso_filename)
    
    if not recto_path:
        return jsonify({'error': f'Image recto non trouvée: {image_recto_filename}'}), 404
    if not verso_path:
        return jsonify({'error': f'Image verso non trouvée: {image_verso_filename}'}), 404
    
    try:
        # --- Analyser le recto ---
        page_recto = pages['recto']
        zones_recto = {z['nom']: {k: v for k, v in z.items() if k != 'nom'} for z in page_recto.get('zones', [])}
        cadre_recto = page_recto.get('cadre_reference')
        
        resultats_recto, alertes_recto = analyser_hybride(recto_path, zones_recto, cadre_reference=cadre_recto)
        if resultats_recto is None:
            resultats_recto = {}
            current_app.logger.warning(f"⚠️ OCR recto échoué: {alertes_recto}")
        
        # --- Analyser le verso ---
        page_verso = pages['verso']
        zones_verso = {z['nom']: {k: v for k, v in z.items() if k != 'nom'} for z in page_verso.get('zones', [])}
        cadre_verso = page_verso.get('cadre_reference')
        
        resultats_verso, alertes_verso = analyser_hybride(verso_path, zones_verso, cadre_reference=cadre_verso)
        if resultats_verso is None:
            resultats_verso = {}
            current_app.logger.warning(f"⚠️ OCR verso échoué: {alertes_verso}")
        
        # --- Appariement ---
        config_appariement = entite.get('appariement', {})
        if not config_appariement:
            config_appariement = {}
        else:
            config_appariement = dict(config_appariement)  # copie pour ne pas modifier l'entité
        
        # Enrichir la config avec les zone_photo depuis les pages
        # 1. Explicitement défini dans l'entité
        if page_recto.get('zone_photo'):
            config_appariement['zone_photo_recto'] = page_recto['zone_photo']
        if page_verso.get('zone_photo'):
            config_appariement['zone_photo_verso'] = page_verso['zone_photo']
        
        # 2. Auto-détection : chercher une zone nommée "photo" dans les zones OCR
        if not config_appariement.get('zone_photo_recto'):
            photo_zone = _trouver_zone_photo(page_recto.get('zones', []))
            if photo_zone:
                config_appariement['zone_photo_recto'] = photo_zone
                current_app.logger.info(f"📸 Zone photo auto-détectée sur le recto: {photo_zone}")
        if not config_appariement.get('zone_photo_verso'):
            photo_zone = _trouver_zone_photo(page_verso.get('zones', []))
            if photo_zone:
                config_appariement['zone_photo_verso'] = photo_zone
                current_app.logger.info(f"📸 Zone photo auto-détectée sur le verso: {photo_zone}")
        
        images_info = {
            'recto_path': recto_path,
            'verso_path': verso_path
        }
        
        result_appariement = apparier_documents(
            resultats_recto, resultats_verso,
            config_appariement, images_info
        )
        
        # --- Fusionner les résultats ---
        resultats_fusionnes = {}
        resultats_fusionnes.update(resultats_recto)
        resultats_fusionnes.update(resultats_verso)
        
        return jsonify({
            'success': True,
            'resultats_recto': resultats_recto,
            'alertes_recto': alertes_recto if isinstance(alertes_recto, list) else [alertes_recto] if alertes_recto else [],
            'resultats_verso': resultats_verso,
            'alertes_verso': alertes_verso if isinstance(alertes_verso, list) else [alertes_verso] if alertes_verso else [],
            'resultats_fusionnes': resultats_fusionnes,
            'appariement': result_appariement
        })
        
    except Exception as e:
        current_app.logger.error(f"Erreur appariement: {e}")
        return jsonify({'error': str(e)}), 500


def _trouver_zone_photo(zones):
    """Cherche automatiquement une zone nommée 'photo' dans la liste des zones.
    
    Retourne les coordonnées [x1, y1, x2, y2] de la zone photo, ou None.
    """
    PHOTO_NAMES = {'photo', 'photo_identite', 'photoidentite', 'portrait', 'visage'}
    for zone in zones:
        nom = zone.get('nom', '').lower().replace(' ', '_').replace('-', '_')
        if nom in PHOTO_NAMES:
            coords = zone.get('coords')
            if coords and len(coords) == 4:
                return coords
    return None
