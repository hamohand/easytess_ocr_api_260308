import os
import shutil
import logging
import numpy as np
from difflib import SequenceMatcher
from PIL import Image, ImageOps
from app.utils.image_utils import apply_pillow_patch
from app.utils.qrcode_utils import decoder_code_hybride
from app.services.image_matcher import find_template_orb

# Apply patch
apply_pillow_patch()

logger = logging.getLogger(__name__)


def upscale_for_ocr(img, min_height=100, target_height=200):
    """
    Agrandit les petites images pour améliorer la reconnaissance OCR.
    
    Args:
        img: Image PIL ou numpy array
        min_height: Hauteur minimum en dessous de laquelle on agrandit
        target_height: Hauteur cible après agrandissement
    
    Returns:
        Image PIL agrandie (ou originale si déjà assez grande)
    """
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    
    w, h = img.size
    
    if h < min_height:
        # Calculer le facteur d'échelle pour atteindre target_height
        scale = target_height / h
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        # Utiliser LANCZOS pour un upscaling de qualité
        img_upscaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        logger.info(f"🔍 Upscale OCR: {w}x{h} -> {new_w}x{new_h} (x{scale:.1f})")
        return img_upscaled
    
    return img


def isolate_dark_text(zone_img, dark_threshold=80, remove_vlines=False):
    """
    Isole le texte foncé en filtrant le fond texturé.
    
    Cette fonction garde uniquement les pixels très foncés (le texte noir)
    et supprime le fond texturé clair.
    
    Args:
        zone_img: Image PIL de la zone
        dark_threshold: Seuil de luminosité (0-255), les pixels plus foncés sont gardés
        remove_vlines: Si True, supprime les lignes verticales du fond (ex: passeports)
    
    Returns:
        Image PIL avec texte noir sur fond blanc
    """
    import cv2
    
    try:
        # Convertir PIL -> OpenCV
        if zone_img.mode == 'L':
            gray = np.array(zone_img)
        else:
            img_cv = cv2.cvtColor(np.array(zone_img), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        
        # 1. Seuillage agressif: ne garder que les pixels très foncés
        # Les pixels < dark_threshold deviennent noirs (texte), les autres blancs (fond)
        _, binary = cv2.threshold(gray, dark_threshold, 255, cv2.THRESH_BINARY_INV)
        
        # 1b. NOUVEAU: Supprimer les lignes verticales du fond texturé
        if remove_vlines:
            # Détecter les lignes verticales avec un kernel élongé verticalement
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, gray.shape[0] // 4))
            detected_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
            
            # Soustraire les lignes verticales de l'image binaire
            binary = cv2.subtract(binary, detected_lines)
            logger.debug(f"🔧 Lignes verticales supprimées")
        
        # 2. Nettoyage morphologique pour éliminer le bruit du fond texturé
        # Kernel horizontal plus grand pour connecter les lettres arabes
        kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
        kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2))
        
        # Opening pour éliminer le petit bruit
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_v)
        
        # Closing pour connecter les parties des lettres
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel_h)
        
        # 3. Filtrer par taille des composantes connectées
        # Les vrais caractères sont plus grands que le bruit du fond
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, connectivity=8)
        
        # Calculer la taille moyenne des composantes (excluant le fond)
        sizes = stats[1:, cv2.CC_STAT_AREA]  # Ignorer le fond (label 0)
        if len(sizes) > 0:
            median_size = np.median(sizes)
            min_size = max(10, median_size * 0.2)  # Au moins 20% de la taille médiane
            
            # Créer un masque avec seulement les grandes composantes
            filtered = np.zeros_like(cleaned)
            for i in range(1, num_labels):
                if stats[i, cv2.CC_STAT_AREA] >= min_size:
                    filtered[labels == i] = 255
        else:
            filtered = cleaned
        
        # Inverser pour avoir texte noir sur fond blanc (meilleur pour OCR)
        result = cv2.bitwise_not(filtered)
        
        vlines_str = " +vlines_removed" if remove_vlines else ""
        logger.info(f"🎯 Isolation texte: seuil={dark_threshold}, composantes gardées={np.sum(sizes >= min_size) if len(sizes) > 0 else 0}{vlines_str}")
        return Image.fromarray(result)
        
    except Exception as e:
        logger.warning(f"Erreur isolation texte: {e}")
        return zone_img.convert('L')

def preprocess_for_arabic_ocr(zone_img, apply_binarization=True):
    """
    Prétraitement optimisé pour le texte arabe dans des zones larges.
    
    1. Améliore le contraste avec CLAHE
    2. Détecte les limites réelles du contenu
    3. Recadre pour éliminer les espaces vides
    4. Applique une binarisation adaptative
    
    Args:
        zone_img: Image PIL de la zone
        apply_binarization: Si True, applique la binarisation
    
    Returns:
        Image PIL prétraitée
    """
    import cv2
    
    try:
        # Convertir PIL -> OpenCV
        img_cv = cv2.cvtColor(np.array(zone_img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        
        original_size = gray.shape
        original_h, original_w = original_size
        
        # 1. Améliorer le contraste avec CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # 2. Binarisation adaptative pour détecter le contenu
        # Essayer plusieurs méthodes pour une meilleure détection
        binary = None
        
        # Méthode 1: Binarisation adaptative locale (meilleure pour arrière-plans non uniformes)
        binary_adaptive = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY_INV, 21, 10
        )
        
        # Méthode 2: Otsu classique sur l'image améliorée
        _, binary_otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Combiner les deux méthodes (OR logique) pour capturer plus de contenu
        binary = cv2.bitwise_or(binary_adaptive, binary_otsu)
        
        # 3. Nettoyage morphologique pour réduire le bruit
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        
        # 4. Trouver les contours du contenu
        coords = cv2.findNonZero(binary)
        
        crop_applied = False
        if coords is not None and len(coords) > 50:  # Au moins quelques pixels de contenu
            x, y, w, h = cv2.boundingRect(coords)
            
            # Vérifier que le contenu détecté est significatif (pas juste du bruit)
            content_ratio = (w * h) / (original_w * original_h)
            
            if content_ratio > 0.01 and w > 20 and h > 10:  # Au moins 1% de la zone et taille minimale
                # Ajouter une marge généreuse (15% de la dimension ou min 15px)
                margin_x = max(15, int(w * 0.15))
                margin_y = max(15, int(h * 0.15))
                
                x1 = max(0, x - margin_x)
                y1 = max(0, y - margin_y)
                x2 = min(original_w, x + w + margin_x)
                y2 = min(original_h, y + h + margin_y)
                
                # Ne recadrer que si on gagne significativement en taille
                new_w = x2 - x1
                new_h = y2 - y1
                
                if new_w < original_w * 0.9 or new_h < original_h * 0.9:
                    gray_cropped = enhanced[y1:y2, x1:x2]
                    crop_applied = True
                    logger.info(f"🔍 Auto-crop arabe: {original_size} -> {gray_cropped.shape} (content ratio: {content_ratio:.2%})")
                else:
                    gray_cropped = enhanced
                    logger.info(f"🔍 Auto-crop arabe: pas de crop nécessaire (contenu occupe toute la zone)")
            else:
                gray_cropped = enhanced
                logger.warning(f"⚠️ Contenu détecté trop petit: w={w}, h={h}, ratio={content_ratio:.2%}")
        else:
            gray_cropped = enhanced
            n_coords = len(coords) if coords is not None else 0
            logger.warning(f"⚠️ Pas assez de contenu détecté ({n_coords} pixels)")
        
        # 5. Binarisation finale sur l'image recadrée
        if apply_binarization and gray_cropped.size > 0:
            # Binarisation adaptative pour un meilleur rendu
            processed = cv2.adaptiveThreshold(
                gray_cropped, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 15, 8
            )
        else:
            processed = gray_cropped
        
        # Convertir retour en PIL
        result = Image.fromarray(processed)
        return result
        
    except Exception as e:
        logger.warning(f"Erreur prétraitement arabe: {e}")
        return zone_img.convert('L')  # Fallback: juste convertir en niveaux de gris


def auto_crop_zone(zone_img, margin=5, min_content_ratio=0.01):
    """
    Recadre automatiquement une zone pour supprimer les espaces blancs.
    Améliore la reconnaissance OCR, surtout pour le texte arabe dans des zones larges.
    
    Args:
        zone_img: Image PIL de la zone
        margin: Marge en pixels à conserver autour du contenu détecté
        min_content_ratio: Ratio minimum de pixels non-blancs pour considérer qu'il y a du contenu
    
    Returns:
        Image PIL recadrée, ou l'originale si pas de contenu détecté
    """
    try:
        # Convertir en niveaux de gris
        gray = zone_img.convert('L')
        gray_np = np.array(gray)
        
        # Détecter les pixels non-blancs (seuil adaptatif)
        # On considère qu'un pixel est "contenu" s'il est significativement plus sombre que le fond
        threshold = np.percentile(gray_np, 95)  # Le 95e percentile comme référence du "blanc"
        content_mask = gray_np < (threshold - 30)  # Pixels au moins 30 niveaux plus sombres
        
        # Vérifier s'il y a assez de contenu
        content_pixels = np.sum(content_mask)
        total_pixels = gray_np.size
        if content_pixels / total_pixels < min_content_ratio:
            # Pas assez de contenu détecté, retourner l'original
            return zone_img
        
        # Trouver les limites du contenu
        rows_with_content = np.any(content_mask, axis=1)
        cols_with_content = np.any(content_mask, axis=0)
        
        if not np.any(rows_with_content) or not np.any(cols_with_content):
            return zone_img
        
        row_indices = np.where(rows_with_content)[0]
        col_indices = np.where(cols_with_content)[0]
        
        top = max(0, row_indices[0] - margin)
        bottom = min(gray_np.shape[0], row_indices[-1] + margin + 1)
        left = max(0, col_indices[0] - margin)
        right = min(gray_np.shape[1], col_indices[-1] + margin + 1)
        
        # Recadrer
        cropped = zone_img.crop((left, top, right, bottom))
        
        logger.debug(f"Auto-crop: {zone_img.size} -> {cropped.size}")
        return cropped
        
    except Exception as e:
        logger.warning(f"Erreur auto-crop: {e}")
        return zone_img


# =============================================================================
# FONCTIONS POUR REPÈRE GÉOMÉTRIQUE (DÉTECTION PAR ANCRES)
# =============================================================================

def ocr_global_avec_positions(image_path, lang='ara+fra'):
    """
    Fait un OCR global du document et retourne tous les mots avec leurs positions.
    
    Args:
        image_path: Chemin vers l'image
        lang: Langue Tesseract
    
    Returns:
        list[dict]: Liste de mots avec {text, x, y, width, height, conf}
        tuple: (img_width, img_height)
    """
    import pytesseract
    
    img = Image.open(image_path)
    img_w, img_h = img.size
    
    try:
        data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
        
        mots = []
        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            conf = int(data['conf'][i]) if data['conf'][i] != '-1' else 0
            
            if text and conf > 20:  # Ignorer les résultats vides ou très faible confiance
                mots.append({
                    'text': text,
                    'x': data['left'][i],
                    'y': data['top'][i],
                    'width': data['width'][i],
                    'height': data['height'][i],
                    'conf': conf
                })
        
        logger.info(f"📄 OCR global: {len(mots)} mots détectés")
        return mots, (img_w, img_h)
        
    except Exception as e:
        logger.error(f"Erreur OCR global: {e}")
        return [], (img_w, img_h)


def detecter_ancres(mots_ocr, ancres_config, img_dims, seuil_similarite=0.7, image_path=None):
    """
    Cherche les ancres définies dans les résultats OCR.
    
    Args:
        mots_ocr: Liste de mots avec positions (depuis ocr_global_avec_positions)
        ancres_config: Liste d'ancres avec leurs labels à chercher
        img_dims: (width, height) de l'image
        seuil_similarite: Seuil minimum pour accepter un match (0.0 à 1.0)
        image_path: Chemin image source (optionnel, requis pour image matching)
    
    Formats de labels supportés:
        - Texte simple: "PASSEPORT" (recherche exacte ou fuzzy)
        - Expression régulière: "regex:\\d{9}" (9 chiffres consécutifs)
    
    Returns:
        dict: {ancre_id: {'text': ..., 'x': ..., 'y': ..., 'found': True/False}}
        bool: True si toutes les ancres sont trouvées
    """
    import re
    
    img_w, img_h = img_dims
    resultats = {}
    
    for ancre in ancres_config:
        ancre_id = ancre.get('id', 'unknown')
        labels = ancre.get('labels', [])
        
        meilleur_match = None
        meilleure_similarite = 0
        
        offset_x = ancre.get('offset_x', 0)
        offset_y = ancre.get('offset_y', 0)
        
        # 1. Recherche Textuelle (OCR)
        if labels and len(labels) > 0 and mots_ocr:
            for mot in mots_ocr:
                texte_mot = mot['text']
                texte_mot_upper = texte_mot.upper()
                
                for label in labels:
                    similarite = 0
                    is_regex = label.startswith('regex:')
                    
                    if is_regex:
                        # Mode expression régulière
                        pattern = label[6:]  # Enlever le préfixe "regex:"
                        try:
                            if re.search(pattern, texte_mot, re.IGNORECASE):
                                similarite = 1.0
                                logger.debug(f"  Regex match: '{texte_mot}' matches '{pattern}'")
                        except re.error as e:
                            logger.warning(f"  Regex invalide '{pattern}': {e}")
                            continue
                    else:
                        # Mode texte normal
                        label_upper = label.upper()
                        
                        # Vérifier si le label est contenu dans le mot (ex: "ID" dans "ID:")
                        if label_upper in texte_mot_upper:
                            similarite = 1.0
                        # Vérifier si le mot est dans le label (ex: "REPUBL" dans "REPUBLIQUE")
                        # Protection: Le mot doit être significatif (>=3 chars ou >70% du label)
                        elif texte_mot_upper in label_upper:
                            if len(texte_mot_upper) >= 3 or len(texte_mot_upper) / len(label_upper) > 0.7:
                                similarite = 1.0
                            else:
                                # Trop court pour être certain -> Fuzzy matching
                                similarite = SequenceMatcher(None, texte_mot_upper, label_upper).ratio()
                        else:
                            # Matching fuzzy
                            similarite = SequenceMatcher(None, texte_mot_upper, label_upper).ratio()
                    
                    if similarite > meilleure_similarite and similarite >= seuil_similarite:
                        meilleure_similarite = similarite
                        
                        abs_center_x = mot['x'] + mot['width'] / 2 + offset_x
                        abs_center_y = mot['y'] + mot['height'] / 2 + offset_y
                        
                        abs_min_x = mot['x'] + offset_x
                        abs_min_y = mot['y'] + offset_y
                        abs_max_x = mot['x'] + mot['width'] + offset_x
                        abs_max_y = mot['y'] + mot['height'] + offset_y
                        
                        # Centre du mot en pourcentage (avec offset appliqué)
                        meilleur_match = {
                            'text': texte_mot,
                            'x': abs_center_x / img_w,
                            'y': abs_center_y / img_h,
                            'x_min': abs_min_x / img_w,
                            'y_min': abs_min_y / img_h,
                            'x_max': abs_max_x / img_w,
                            'y_max': abs_max_y / img_h,
                            'x_abs': abs_center_x,
                            'y_abs': abs_center_y,
                            'similarite': similarite,
                            'label_matched': label,
                            'is_regex': is_regex
                        }
        
        # Si trouvé par OCR, on enregistre
        if meilleur_match:
            resultats[ancre_id] = {**meilleur_match, 'found': True}
            match_type = "regex" if meilleur_match.get('is_regex') else "text"
            logger.info(f"✅ Ancre '{ancre_id}' trouvée ({match_type}): '{meilleur_match['text']}' (sim={meilleure_similarite:.0%})")
        else:
            # 2. Fallback: Recherche par Template Image (ORB)
            template_path = ancre.get('template_path_abs') # Priorité au chemin absolu (temp files)
            if not template_path:
                 # Résoudre chemin relatif si nécessaire (cherche dans uploads_temp puis uploads)
                 rel_path = ancre.get('template_path')
                 if rel_path:
                     import flask
                     temp_folder = flask.current_app.config.get('UPLOAD_TEMP_FOLDER', 'uploads_temp')
                     perm_folder = flask.current_app.config.get('UPLOAD_FOLDER', 'uploads')
                     candidate_temp = os.path.join(temp_folder, rel_path)
                     candidate_perm = os.path.join(perm_folder, rel_path)
                     if os.path.exists(candidate_temp):
                         template_path = candidate_temp
                     elif os.path.exists(candidate_perm):
                         template_path = candidate_perm
            
            orb_match_found = False
            
            if template_path and os.path.exists(template_path) and image_path and os.path.exists(image_path):
                 logger.info(f"📷 Fallback OCR échoué: Tentative matching image pour ancre {ancre_id}...")
                 result = find_template_orb(image_path, template_path)
                 
                 if result.get('found'):
                     abs_x = result['x'] * img_w + offset_x
                     abs_y = result['y'] * img_h + offset_y
                     abs_x_min = result['x_min'] * img_w + offset_x
                     abs_y_min = result['y_min'] * img_h + offset_y
                     abs_x_max = result['x_max'] * img_w + offset_x
                     abs_y_max = result['y_max'] * img_h + offset_y
                     
                     resultats[ancre_id] = {
                        'found': True,
                        'text': f'[Image: {ancre_id}]',
                        'x': abs_x / img_w,
                        'y': abs_y / img_h,
                        'x_min': abs_x_min / img_w,
                        'y_min': abs_y_min / img_h,
                        'x_max': abs_x_max / img_w,
                        'y_max': abs_y_max / img_h,
                        'source': 'image_template',
                        'confidence': result.get('confidence', 0)
                    }
                     logger.info(f"  ✅ Template {ancre_id} trouvé à ({resultats[ancre_id]['x']:.3f}, {resultats[ancre_id]['y']:.3f}) après offset")
                     orb_match_found = True
                 else:
                     logger.warning(f"  ⚠️ Template {ancre_id} non trouvé via ORB: {result.get('error')}")

            if not orb_match_found:
                resultats[ancre_id] = {'found': False}
                if labels:
                    logger.warning(f"❌ Ancre '{ancre_id}' non trouvée par OCR ni par Image (labels: {labels})")
                else:
                    logger.warning(f"❌ Ancre '{ancre_id}' non trouvée (pas de labels ni template valide)")

    toutes_trouvees = all(r['found'] for r in resultats.values())
    return resultats, toutes_trouvees


def calculer_transformation(ancres_base, ancres_detectees):
    """
    Calcule la matrice de transformation affine entre les ancres de base et détectées.
    
    Args:
        ancres_base: dict {ancre_id: (x, y)} positions sur l'image de base (en %)
        ancres_detectees: dict {ancre_id: {'x': x, 'y': y}} positions détectées (en %)
    
    Returns:
        np.array ou None: Matrice 2x3 de transformation affine, ou None si pas assez d'ancres
    """
    import cv2
    
    # Récupérer les points correspondants
    pts_base = []
    pts_new = []
    
    for ancre_id, pos_base in ancres_base.items():
        if ancre_id in ancres_detectees and ancres_detectees[ancre_id].get('found'):
            pts_base.append(pos_base)
            pts_new.append((ancres_detectees[ancre_id]['x'], ancres_detectees[ancre_id]['y']))
    
    if len(pts_base) < 2:
        logger.warning("Pas assez d'ancres pour calculer la transformation")
        return None
    
    pts_base = np.float32(pts_base)
    pts_new = np.float32(pts_new)
    
    if len(pts_base) == 2:
        # Avec 2 points: calculer translation + rotation + échelle
        # Vecteur de référence
        v_base = pts_base[1] - pts_base[0]
        v_new = pts_new[1] - pts_new[0]
        
        # Échelle
        scale = np.linalg.norm(v_new) / np.linalg.norm(v_base) if np.linalg.norm(v_base) > 0 else 1.0
        
        # Angle
        angle_base = np.arctan2(v_base[1], v_base[0])
        angle_new = np.arctan2(v_new[1], v_new[0])
        rotation = angle_new - angle_base
        
        # Construire la matrice
        cos_r, sin_r = np.cos(rotation), np.sin(rotation)
        R = np.array([[cos_r, -sin_r], [sin_r, cos_r]]) * scale
        
        # Translation pour aligner le premier point
        t = pts_new[0] - R @ pts_base[0]
        
        M = np.zeros((2, 3), dtype=np.float32)
        M[:2, :2] = R
        M[:, 2] = t
        
        logger.info(f"📐 Transformation: échelle={scale:.3f}, rotation={np.degrees(rotation):.1f}°, translation=({t[0]:.3f}, {t[1]:.3f})")
        
    else:
        # Avec 3+ points: transformation affine complète
        M, _ = cv2.estimateAffine2D(pts_base, pts_new)
        if M is not None:
            logger.info(f"📐 Transformation affine calculée avec {len(pts_base)} ancres")
    
    return M


def transformer_zones(zones_config, matrice_transfo):
    """
    Applique la transformation aux coordonnées des zones.
    
    Args:
        zones_config: dict {nom_zone: {'coords': [x1, y1, x2, y2], ...}}
        matrice_transfo: Matrice 2x3 de transformation affine
    
    Returns:
        dict: zones_config avec coordonnées transformées
    """
    if matrice_transfo is None:
        return zones_config
    
    zones_transformees = {}
    
    for nom, config in zones_config.items():
        coords = config.get('coords', [0, 0, 1, 1])
        x1, y1, x2, y2 = coords
        
        # Transformer les 4 coins
        coin1 = matrice_transfo @ np.array([x1, y1, 1])
        coin2 = matrice_transfo @ np.array([x2, y2, 1])
        
        # Reconstruire le rectangle (peut être légèrement déformé si rotation)
        new_x1 = min(coin1[0], coin2[0])
        new_y1 = min(coin1[1], coin2[1])
        new_x2 = max(coin1[0], coin2[0])
        new_y2 = max(coin1[1], coin2[1])
        
        # Clamp aux limites [0, 1]
        new_coords = [
            max(0, min(1, new_x1)),
            max(0, min(1, new_y1)),
            max(0, min(1, new_x2)),
            max(0, min(1, new_y2))
        ]
        
        zones_transformees[nom] = {**config, 'coords': new_coords}
        logger.debug(f"Zone {nom}: {coords} -> {new_coords}")
    
    return zones_transformees

# --- CONFIG TESSERACT ---
TESSERACT_DISPONIBLE = False
try:
    import pytesseract
    TESSERACT_CMD = shutil.which('tesseract')
    if not TESSERACT_CMD:
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            '/usr/bin/tesseract',
            '/usr/local/bin/tesseract'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                TESSERACT_CMD = path
                break
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        TESSERACT_DISPONIBLE = True
        logger.info(f"✅ Tesseract activé : {TESSERACT_CMD}")
    else:
        logger.warning("⚠️ Tesseract non trouvé.")
except ImportError:
    logger.error("❌ Module 'pytesseract' non installé.")

# --- CONFIG EASYOCR ---
EASYOCR_DISPONIBLE = False
try:
    import easyocr
    EASYOCR_DISPONIBLE = True
    logger.info("✅ EasyOCR disponible")
except ImportError:
    logger.warning("⚠️ EasyOCR non disponible.")

# EasyOCR Lazy Loading - Multiple readers for different language combinations
_easyocr_readers = {}

def get_easyocr_reader(zone_lang='ara+fra'):
    """
    Retourne le reader EasyOCR approprié pour la langue de la zone.
    Cache les readers pour éviter de les recharger.
    """
    global _easyocr_readers
    
    # Mapper les langues Tesseract vers EasyOCR
    if zone_lang in ['ara', 'ara+fra']:
        langs = ['ar', 'en']  # Arabe + fallback anglais
        key = 'ar_en'
    elif zone_lang == 'fra':
        langs = ['fr', 'en']  # Français + fallback anglais  
        key = 'fr_en'
    elif zone_lang == 'eng':
        langs = ['en']
        key = 'en'
    else:
        langs = ['ar', 'en']  # Défaut: arabe
        key = 'ar_en'
    
    if key not in _easyocr_readers and EASYOCR_DISPONIBLE:
        try:
            use_gpu = False
            try:
                import torch
                use_gpu = torch.cuda.is_available()
            except ImportError:
                pass

            logger.info(f"🔄 Chargement EasyOCR ({'+'.join(langs)}) [GPU={use_gpu}]...")
            _easyocr_readers[key] = easyocr.Reader(langs, gpu=use_gpu)
            logger.info(f"✅ EasyOCR chargé ({key}).")
        except Exception as e:
            logger.error(f"❌ Erreur EasyOCR: {e}")
            return None
    
    return _easyocr_readers.get(key)


def corriger_avec_valeurs_connues(texte_ocr, valeurs_possibles, seuil=0.6):
    """
    Corrige le texte OCR en le comparant aux valeurs connues.
    Utilise la similarité fuzzy pour trouver la meilleure correspondance.
    
    Args:
        texte_ocr: Le texte brut extrait par l'OCR
        valeurs_possibles: Liste des valeurs attendues (ex: ["M", "F", "Masculin", "Féminin"])
        seuil: Score minimum de similarité pour accepter une correction (0.0 à 1.0)
    
    Returns:
        tuple: (texte_corrigé, score_de_correspondance)
    """
    if not texte_ocr or not valeurs_possibles:
        return texte_ocr, 0.0
    
    meilleure_correspondance = texte_ocr
    meilleur_score = 0.0
    
    texte_normalise = texte_ocr.strip().lower()
    
    for valeur in valeurs_possibles:
        valeur_norm = str(valeur).strip().lower()
        
        # Calcul de similarité
        score = SequenceMatcher(None, texte_normalise, valeur_norm).ratio()
        
        # Bonus si le texte OCR contient la valeur ou vice-versa
        if valeur_norm in texte_normalise or texte_normalise in valeur_norm:
            score = min(1.0, score + 0.2)
        
        if score > meilleur_score:
            meilleur_score = score
            meilleure_correspondance = valeur  # Retourne la valeur originale, pas normalisée
    
    if meilleur_score >= seuil:
        logger.debug(f"Correction OCR: '{texte_ocr}' -> '{meilleure_correspondance}' (score: {meilleur_score:.2f})")
        return meilleure_correspondance, meilleur_score
    
    return texte_ocr, 0.0




def analyser_hybride(image_path, zones_config, cadre_reference=None):
    """
    Analyse hybride avec support pour le cadre de référence à 3 étiquettes.
    
    Args:
        image_path: Chemin vers l'image
        zones_config: Configuration des zones
        cadre_reference: Optionnel - Configuration du cadre de référence avec 3 étiquettes:
                        - origine: étiquette définissant le point (0,0)
                        - largeur: étiquette définissant la largeur du cadre
                        - hauteur: étiquette définissant la hauteur du cadre
        
    Returns:
        tuple: (resultats, alertes) ou (None, erreur) si étiquettes non trouvées
    """
    resultats = {}
    temp_crop_path = None  # IMPORTANT: Initialiser au niveau fonction pour portée globale
    x_ref_px = None
    y_ref_px = None
    largeur_cadre_rel = None
    hauteur_cadre_rel = None
    img_dims = None
    
    # 0. NOUVEAU: Si un cadre de référence est défini, détecter les étiquettes et transformer les coordonnées
    # Support des clés: haut, droite, gauche_bas (Nouveau) OU origine, largeur, hauteur (Legacy)
    if not cadre_reference:
        logger.warning("⚠️ DEBUG: Pas de cadre de référence fourni. Analyse en coordonnées Image (0,0).")
    
    if cadre_reference and (cadre_reference.get('haut') or cadre_reference.get('origine')):
        logger.info(f"📐 Détection du cadre de référence (3 étiquettes)...")
        
        # Convertir format cadre_reference vers format ancres pour détection
        ancres_config = []
        
        logger.info(f"🔍 DEBUG: Cadre reference reçu: {cadre_reference}")
        
        
        # Helper pour construire la config ancre
        def add_anchor_config(anchor_id, ref_data, default_pos):
            if not ref_data: return
            
            labels = ref_data.get('labels', [])
            template_path = ref_data.get('template_path')
            
            # Ajouter si labels OU template présent
            if labels or template_path:
                conf = {
                    'id': anchor_id, 
                    'labels': labels, 
                    'position_base': ref_data.get('position_base', default_pos),
                    'template_path': template_path,
                    'offset_x': ref_data.get('offset_x', 0),
                    'offset_y': ref_data.get('offset_y', 0)
                }
                ancres_config.append(conf)
                
                log_msg = f"  ✅ Ancre {anchor_id.upper()} configurée:"
                if labels: log_msg += f" Labels={labels}"
                if template_path: log_msg += f" Template={template_path}"
                logger.info(log_msg)

        add_anchor_config('haut', cadre_reference.get('haut'), [0.5, 0])
        add_anchor_config('droite', cadre_reference.get('droite'), [1, 0.5])
        add_anchor_config('gauche', cadre_reference.get('gauche'), [0, 0.5])
        add_anchor_config('bas', cadre_reference.get('bas'), [0.5, 1])
        
        # Support ancien format 3 ancres (backward compatibility)
        if not cadre_reference.get('gauche') and not cadre_reference.get('bas'):
             add_anchor_config('gauche_bas', cadre_reference.get('gauche_bas'), [0, 1])
            
        # Mapping legacy (si nouveau format absent)
        if not ancres_config and cadre_reference.get('origine'):
             add_anchor_config('origine', cadre_reference.get('origine'), [0, 0])
             add_anchor_config('largeur', cadre_reference.get('largeur'), [1, 0])
             add_anchor_config('hauteur', cadre_reference.get('hauteur'), [0, 1])
        
        logger.info(f"📋 Total ancres configurées: {len(ancres_config)}")
        
        etiquettes_detectees = {}
        
        # S'il y a des ancres à chercher
        if len(ancres_config) > 0:
            # OCR global pour trouver les étiquettes
            mots_ocr, img_dims = ocr_global_avec_positions(image_path, lang='fra+eng')
            
            # Note: mots_ocr peut être vide si pas de texte, mais on continue pour les templates
            if not mots_ocr:
                logger.warning("⚠️ OCR global vide (pas de texte détecté)")
                mots_ocr = []
                # Besoin de img_dims si OCR n'a rien renvoyé
                if not img_dims:
                    try: 
                        with Image.open(image_path) as img: img_dims = img.size
                    except: pass

            if not img_dims: # Si toujours pas de dims, erreur
                 return None, "Impossible de lire les dimensions de l'image"
            
            # Détecter les étiquettes (avec image_path pour fallback template)
            etiquettes_detectees, toutes_trouvees = detecter_ancres(
                mots_ocr, 
                ancres_config, 
                img_dims,
                image_path=image_path
            )
            
            if not toutes_trouvees:
                etiquettes_manquantes = [k for k, v in etiquettes_detectees.items() if not v.get('found')]
                logger.warning(f"⚠️ Certaines étiquettes non trouvées: {', '.join(etiquettes_manquantes)} -> Utilisation des bords de l'image par défaut")
        else:
            # Pas d'ancres configurées
            try:
                with Image.open(image_path) as img:
                    img_dims = img.size
                    logger.info(f"📏 Pas d'ancres configurées, dimensions image: {img_dims}")
            except Exception as e:
                logger.error(f"❌ Impossible d'ouvrir l'image: {e}")
                return None, str(e)

        # Calculer la transformation de coordonnées (Unified Logic)
        # On consruit les 4 bornes (Top, Bottom, Left, Right)
        # Priority: Detected Anchor > Legacy Anchor > Image Edge
        
        img_w, img_h = img_dims
        
        # 1. TOP (Y Min)
        if 'haut' in etiquettes_detectees and etiquettes_detectees['haut']['found']:
            y_ref_min = etiquettes_detectees['haut']['y_min'] * img_h
        else:
            y_ref_min = 0 # Default to Image Top
            
        # 2. BOTTOM (Y Max)
        if 'bas' in etiquettes_detectees and etiquettes_detectees['bas']['found']:
            y_ref_max = etiquettes_detectees['bas']['y_max'] * img_h
        elif 'gauche_bas' in etiquettes_detectees and etiquettes_detectees['gauche_bas']['found']:
             y_ref_max = etiquettes_detectees['gauche_bas']['y_max'] * img_h
        else:
            y_ref_max = img_h # Default to Image Bottom
            
        # 3. LEFT (X Min)
        if 'gauche' in etiquettes_detectees and etiquettes_detectees['gauche']['found']:
            x_ref_min = etiquettes_detectees['gauche']['x_min'] * img_w
        elif 'gauche_bas' in etiquettes_detectees and etiquettes_detectees['gauche_bas']['found']:
             x_ref_min = etiquettes_detectees['gauche_bas']['x_min'] * img_w
        else:
            x_ref_min = 0 # Default to Image Left
            
        # 4. RIGHT (X Max)
        if 'droite' in etiquettes_detectees and etiquettes_detectees['droite']['found']:
            x_ref_max = etiquettes_detectees['droite']['x_max'] * img_w
        else:
            x_ref_max = img_w # Default to Image Right
            
        
        # Validation des dimensions calculées
        detected_w_px = x_ref_max - x_ref_min
        detected_h_px = y_ref_max - y_ref_min
        
        # Protection contre croisements ou dimensions nulles
        if detected_w_px <= 10: detected_w_px = max(10, img_w - x_ref_min)
        if detected_h_px <= 10: detected_h_px = max(10, img_h - y_ref_min)
        
        # Set Global Variables for Crop Logic
        # Note: largeur_cadre_rel et hauteur_cadre_rel ne sont plus utilisés pour le calcul final pixel
        # mais peuvent être utiles pour le remapping si on devait recalculer.
        # Ici on a direct les pixels.
        
        x_ref_px = x_ref_min
        y_ref_px = y_ref_min
        
        # Pseudo-relative (juste pour info/log, pas critique car on a les pixels)
        largeur_cadre_rel = detected_w_px / img_w if img_w else 1
        hauteur_cadre_rel = detected_h_px / img_h if img_h else 1

        logger.info(f"📐 AABB Unifiée: H={y_ref_min:.0f}({'Ancre' if 'haut' in etiquettes_detectees else 'Edge'}), B={y_ref_max:.0f}, G={x_ref_min:.0f}, D={x_ref_max:.0f}")
        logger.info(f"📐 Cadre Final: Origine=({x_ref_px:.0f}px, {y_ref_px:.0f}px), L={detected_w_px:.0f}px, H={detected_h_px:.0f}px")

        # Flag pour déclencher le rognage
        has_4_anchors = True # On a toujours 4 bornes (réelles ou virtuelles)


    # --- Code Commun : Rognage physique ---
    if x_ref_px is not None:
        logger.info(f"✂️ Début du rognage de l'image sur le cadre...")
        import uuid
        try:
            with Image.open(image_path) as img_pil:
                left = int(x_ref_px)
                top = int(y_ref_px)
                right = int(left + detected_w_px)
                bottom = int(top + detected_h_px)
                
                # Clamp
                left = max(0, left)
                top = max(0, top)
                right = min(img_pil.width, right)
                bottom = min(img_pil.height, bottom)
                
                if right > left and bottom > top:
                    img_crop = img_pil.crop((left, top, right, bottom))
                    
                    temp_filename = f"crop_{uuid.uuid4().hex[:8]}.jpg"
                    temp_path = os.path.join(os.path.dirname(image_path), temp_filename)
                    img_crop.save(temp_path)
                    
                    logger.info(f"✂️ Image sauvegardée: {temp_path}")
                    
                    image_path = temp_path
                    temp_crop_path = temp_path
                else:
                    logger.error(f"❌ Crop invalide: L={left}, T={top}, R={right}, B={bottom}")
                
        except Exception as e:
            logger.error(f"❌ Erreur lors du rognage: {e}")
            
    logger.info(f"✅ Coordonnées ajustées selon cadre de référence")

    
    # 1. Détection QR codes/codes-barres pour les zones marquées
    zones_qr = {k: v for k, v in zones_config.items() if v.get('type') == 'qrcode' or v.get('type') == 'barcode'}
    for nom_zone, config in zones_qr.items():
        try:
            qr_result = decoder_code_hybride(image_path, config['coords'])
            if qr_result['success']:
                # Extraire les séquences séparées par des astérisques
                qr_data = qr_result['data']
                sequences = [s for s in qr_data.split('*') if s]  # Filtrer les chaînes vides
                
                resultats[nom_zone] = {
                    'texte_auto': qr_data,
                    'confiance_auto': 1.0,  # QR code = 100% confiance si décodé
                    'statut': 'ok',
                    'moteur': f"qrcode_{qr_result.get('moteur', 'pyzbar')}",
                    'coords': config['coords'],
                    'texte_final': qr_data,
                    'code_type': qr_result['type'],
                    'code_count': qr_result['count'],
                    'sequences': sequences  # Liste des séquences extraites
                }

            else:
                # QR code non détecté, on laissera l'OCR essayer
                logger.warning(f"QR code non détecté dans zone {nom_zone}: {qr_result.get('error')}")
        except Exception as e:
            logger.error(f"Erreur détection QR code zone {nom_zone}: {e}")
    
    # 2. Zones OCR classiques (exclure les zones QR déjà traitées)
    zones_ocr = {k: v for k, v in zones_config.items() if k not in resultats}
    
    # 3. Essai Tesseract sur zones OCR
    if zones_ocr and TESSERACT_DISPONIBLE:
        try:
            logger.info(f"🔤 Tesseract: analyse de {len(zones_ocr)} zone(s)")
            resultats_ocr = analyser_avec_tesseract(image_path, zones_ocr)
            resultats.update(resultats_ocr)
        except Exception as e:
            logger.error(f"Erreur Tesseract global: {e}")
    
    # 4. Identification des zones à refaire (échec ou faible confiance)
    zones_a_refaire = {k: v for k, v in zones_config.items() if k not in resultats or resultats[k]['confiance_auto'] < 0.6}
    
    # 5. Essai EasyOCR sur les zones difficiles
    if zones_a_refaire and EASYOCR_DISPONIBLE:
        try:
            logger.info(f"🔤 EasyOCR: analyse de {len(zones_a_refaire)} zone(s) à améliorer")
            res_easy = analyser_avec_easyocr(image_path, zones_a_refaire)
            for k, v in res_easy.items():
                # Garder le meilleur résultat entre Tesseract et EasyOCR
                if k in resultats:
                    tesseract_conf = resultats[k]['confiance_auto']
                    easyocr_conf = v['confiance_auto']
                    if easyocr_conf > tesseract_conf:
                        logger.info(f"✨ Zone {k}: EasyOCR meilleur ({easyocr_conf:.0%}) que Tesseract ({tesseract_conf:.0%})")
                        resultats[k] = v
                        resultats[k]['ameliore_par'] = 'easyocr'
                    else:
                        logger.info(f"✨ Zone {k}: on garde Tesseract ({tesseract_conf:.0%}) meilleur que EasyOCR ({easyocr_conf:.0%})")
                else:
                    resultats[k] = v
                    resultats[k]['ameliore_par'] = 'easyocr'
        except Exception as e:
            logger.error(f"Erreur EasyOCR global: {e}")
    
    # 6. Correction avec valeurs attendues (si définies)
    for nom_zone, config in zones_config.items():
        if nom_zone in resultats and 'valeurs_attendues' in config:
            valeurs = config.get('valeurs_attendues', [])
            if valeurs and resultats[nom_zone].get('texte_auto'):
                texte_original = resultats[nom_zone]['texte_auto']
                texte_corrige, score = corriger_avec_valeurs_connues(texte_original, valeurs)
                
                if score > 0:
                    resultats[nom_zone]['texte_final'] = texte_corrige
                    resultats[nom_zone]['correction_appliquee'] = True
                    resultats[nom_zone]['valeur_originale'] = texte_original
                    resultats[nom_zone]['score_correction'] = score
                    
                    # Améliorer le statut si la correction a un bon score
                    if score >= 0.8:
                        resultats[nom_zone]['statut'] = 'ok'
                        resultats[nom_zone]['confiance_auto'] = max(
                            resultats[nom_zone]['confiance_auto'], 
                            score
                        )
        
    # 7. Remplissage des échecs complets
    for k in zones_config:
        if k not in resultats:
            resultats[k] = {
                'texte_auto': '', 
                'confiance_auto': 0, 
                'statut': 'echec', 
                'moteur': 'aucun',
                'coords': zones_config[k]['coords'],
                'texte_final': ''
            }
            
    # RE-MAPPING DES COORDONNEES VERS L'IMAGE ORIGINALE
    # Si on a rogné, 'resultats' contient des coords relatives (0-1) au CROP.
    # Il faut les convertir en coords relatives (0-1) par rapport à l'IMAGE ORIGINALE.
    
    if temp_crop_path and x_ref_px is not None and y_ref_px is not None:
        logger.info(f"🔄 RE-MAPPING des coordonnées de {len(resultats)} zone(s) vers l'image originale...")
        
        orig_w, orig_h = img_dims  # Dimensions originales
        
        # Calculer les dimensions du cadre en pixels
        cadre_w_px = largeur_cadre_rel * orig_w
        cadre_h_px = hauteur_cadre_rel * orig_h
        
        for k, v in resultats.items():
            if 'coords' in v:
                c = v['coords']
                
                # Coords relatives au crop (0-1) -> Pixels dans le Crop
                # ATTENTION: Tesseract/EasyOCR renvoient des PIXELS absolus (valeurs > 1) relativement au crop.
                # Si les valeurs sont <= 1.0, on considère que c'est du relatif.
                
                if all(val <= 1.0 for val in c):
                    x1_c = c[0] * cadre_w_px
                    y1_c = c[1] * cadre_h_px
                    x2_c = c[2] * cadre_w_px
                    y2_c = c[3] * cadre_h_px
                else:
                    # Déjà en pixels (relatif au crop)
                    x1_c = c[0]
                    y1_c = c[1]
                    x2_c = c[2]
                    y2_c = c[3]
                
                # Pixels dans le Crop -> Pixels dans l'image Originale
                # (Simple translation psq pas de rotation)
                x1_orig = x1_c + x_ref_px
                y1_orig = y1_c + y_ref_px
                x2_orig = x2_c + x_ref_px
                y2_orig = y2_c + y_ref_px
                
                # Pixels Orig -> Relatif Orig
                v['coords'] = [
                    x1_orig / orig_w if orig_w else 0,
                    y1_orig / orig_h if orig_h else 0,
                    x2_orig / orig_w if orig_w else 0,
                    y2_orig / orig_h if orig_h else 0
                ]
    
    # NETTOYAGE DU CROP TEMPORAIRE
    if temp_crop_path and os.path.exists(temp_crop_path):
        try:
            os.remove(temp_crop_path)
            logger.info(f"🗑️ Fichier temporaire supprimé: {temp_crop_path}")
        except Exception as e:
            logger.warning(f"⚠️ Nettoyage impossible: {e}")

    # NORMALISATION FINALE DES COORDONNÉES
    # Assurer que toutes les coordonnées renvoyées sont en relatif (0-1) par rapport à l'image originale
    if not img_dims: # Si non défini plus tôt
        try:
            with Image.open(image_path) as img:
                img_dims = img.size
        except:
            img_dims = (1, 1) # Fallback pour éviter division par zero
            
    img_w, img_h = img_dims
    
    for k, v in resultats.items():
        if 'coords' in v and v['coords']:
            c = v['coords']
            # Détection heuristique: si valeurs > 1, ce sont des pixels -> convertir en relatif
            if any(val > 1.5 for val in c):
                v['coords'] = [
                    c[0] / img_w,
                    c[1] / img_h,
                    c[2] / img_w,
                    c[3] / img_h
                ]
                logger.debug(f"📏 Normalisation coords zone '{k}': {c} -> {v['coords']}")

    alertes = [k for k, v in resultats.items() if v['statut'] != 'ok']
    return resultats, alertes

def get_absolute_coords(coords, img_w, img_h):
    """
    Convertit les coordonnées en pixels absolus.
    Gère les coordonnées relatives (0.0-1.0) et absolues (pixels).
    """
    x1, y1, x2, y2 = coords
    
    # Détection automatique : si toutes les valeurs sont <= 1.0, on suppose du relatif
    if all(v <= 1.0 for v in coords):
        return (
            int(x1 * img_w),
            int(y1 * img_h),
            int(x2 * img_w),
            int(y2 * img_h)
        )
    return x1, y1, x2, y2

def analyser_avec_tesseract(image_path, zones_config):
    if not TESSERACT_DISPONIBLE:
        return {}
        
    img = Image.open(image_path)
    img_w, img_h = img.size
    resultats = {}
    for nom_zone, config in zones_config.items():
        # Récupérer la langue de la zone (défaut: ara+fra)
        zone_lang = config.get('lang', 'ara+fra')
        
        # Récupérer le mode de prétraitement (défaut: auto)
        preprocess_mode = config.get('preprocess', 'auto')
        
        # Mode auto: choisir selon la langue
        if preprocess_mode == 'auto':
            if zone_lang in ['ara', 'ara+fra']:
                preprocess_mode = 'arabic_textured'
            else:
                preprocess_mode = 'latin_simple'
        
        x1, y1, x2, y2 = get_absolute_coords(config['coords'], img_w, img_h)
        
        # Sécurité pour ne pas sortir de l'image
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img_w, x2), min(img_h, y2)
        
        if x2 <= x1 or y2 <= y1:
            logger.warning(f"Zone {nom_zone} invalide après conversion : {x1},{y1},{x2},{y2}")
            continue

        zone_img = img.crop((x1, y1, x2, y2))
        
        # Upscale pour les petits textes
        zone_img = upscale_for_ocr(zone_img)
        
        # Préparation des variantes selon le mode de prétraitement
        zone_img_gray = zone_img.convert('L')
        
        if preprocess_mode == 'arabic_textured':
            # Mode arabe: isolation du texte foncé + multi-variantes
            zone_img_processed = preprocess_for_arabic_ocr(zone_img, apply_binarization=True)
            zone_img_no_bin = preprocess_for_arabic_ocr(zone_img, apply_binarization=False)
            zone_img_isolated_60 = isolate_dark_text(zone_img, dark_threshold=60)
            zone_img_isolated_80 = isolate_dark_text(zone_img, dark_threshold=80)
            zone_img_isolated_100 = isolate_dark_text(zone_img, dark_threshold=100)
            
            variants = [
                (zone_img_isolated_60, "iso60"),
                (zone_img_isolated_80, "iso80"),
                (zone_img_isolated_100, "iso100"),
                (zone_img_gray, "gray"),
                (zone_img_no_bin, "nobin"),
            ]
            logger.info(f"� Zone {nom_zone}: mode arabic_textured (5 variantes)")
            
        elif preprocess_mode == 'latin_simple':
            # Mode latin simple AMÉLIORÉ: isolation du texte foncé + suppression lignes verticales
            import cv2
            
            # Binarisation Otsu classique
            _, binary = cv2.threshold(np.array(zone_img_gray), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            zone_img_binary = Image.fromarray(binary)
            
            # Isolation du texte foncé AVEC suppression des lignes verticales (passeports)
            zone_img_iso_novlines = isolate_dark_text(zone_img, dark_threshold=80, remove_vlines=True)
            zone_img_isolated_100 = isolate_dark_text(zone_img, dark_threshold=100, remove_vlines=True)
            
            variants = [
                (zone_img_iso_novlines, "iso_novlines"),  # Isolation + suppression lignes verticales
                (zone_img_isolated_100, "iso100_novlines"),  # Isolation légère + sans lignes
                (zone_img_gray, "gray"),                   # Grayscale simple
                (zone_img_binary, "binary"),               # Binarisation Otsu
            ]
            logger.info(f"🔧 Zone {nom_zone}: mode latin_simple (4 variantes, vlines removed)")
            
        else:  # preprocess_mode == 'none'
            # Pas de prétraitement: image brute upscalée
            variants = [
                (zone_img_gray, "raw"),
            ]
            logger.info(f"🔧 Zone {nom_zone}: mode none (1 variante)")
        
        # DEBUG: Sauvegarder les images des zones pour inspection (désactivé en production)
        DEBUG_SAVE_IMAGES = False
        if DEBUG_SAVE_IMAGES:
            debug_dir = os.path.join(os.path.dirname(image_path), 'debug')
            os.makedirs(debug_dir, exist_ok=True)
            try:
                zone_img.save(os.path.join(debug_dir, f'{nom_zone}_upscaled.png'))
                zone_img_gray.save(os.path.join(debug_dir, f'{nom_zone}_gray.png'))
                logger.info(f"🖼️ Debug: images sauvegardées dans {debug_dir}")
            except Exception as e:
                logger.debug(f"Debug save error: {e}")
        
        # Stratégie multi-PSM: essayer plusieurs modes et garder le meilleur
        # PSM 7 = ligne unique, PSM 6 = bloc uniforme, PSM 13 = ligne brute, PSM 8 = mot unique
        psm_modes = [7, 6, 13, 8]
        best_text = ""
        best_conf = 0.0
        best_psm = 7
        best_variant_name = ""
        
        for psm in psm_modes:
            for img_variant, variant_name in variants:
                try:
                    tess_config = f'--oem 3 --psm {psm}'
                    text = pytesseract.image_to_string(img_variant, lang=zone_lang, config=tess_config).strip()
                    
                    if text:
                        data = pytesseract.image_to_data(img_variant, lang=zone_lang, config=tess_config, output_type=pytesseract.Output.DICT)
                        confs = [int(c) for c in data['conf'] if c != '-1' and str(c).isdigit()]
                        conf = sum(confs) / len(confs) / 100 if confs else 0.0
                        
                        if conf > best_conf or (conf == best_conf and len(text) > len(best_text)):
                            best_text = text
                            best_conf = conf
                            best_psm = psm
                            logger.debug(f"Zone {nom_zone}: PSM {psm} ({variant_name}) -> '{text[:30]}...' conf={conf:.0%}")
                except Exception as e:
                    logger.debug(f"Zone {nom_zone}: PSM {psm} erreur: {e}")
        
        texte = best_text
        confiance = best_conf
        
        if texte:
            logger.info(f"✅ Zone {nom_zone} [{zone_lang}]: meilleur PSM={best_psm}, conf={confiance:.0%}, texte='{texte[:30]}...'")
        else:
            logger.warning(f"⚠️ Zone {nom_zone}: aucun texte détecté avec tous les PSM")
        statut = "ok" if confiance >= 0.6 and texte else "faible_confiance"
        resultats[nom_zone] = {
            'texte_auto': texte, 
            'confiance_auto': confiance, 
            'statut': statut, 
            'moteur': 'tesseract',
            'coords': [x1, y1, x2, y2], # On renvoie les coords absolues utilisées
            'texte_final': texte
        }
    return resultats

def analyser_avec_easyocr(image_path, zones_config):
    img = Image.open(image_path).convert('RGB')
    img_w, img_h = img.size
    img_np = np.array(img)
    resultats = {}
    
    for nom_zone, config in zones_config.items():
        # Récupérer la langue de la zone pour choisir le bon reader EasyOCR
        zone_lang = config.get('lang', 'ara+fra')
        reader = get_easyocr_reader(zone_lang)
        
        if not reader:
            logger.warning(f"⚠️ EasyOCR non disponible pour zone {nom_zone}")
            continue
            
        x1, y1, x2, y2 = get_absolute_coords(config['coords'], img_w, img_h)
        
        # Sécurité
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img_w, x2), min(img_h, y2)
        
        if x2 <= x1 or y2 <= y1:
            continue

        zone_img_pil = img.crop((x1, y1, x2, y2))
        
        # Upscale pour les petits textes
        zone_img_upscaled = upscale_for_ocr(zone_img_pil)
        
        # Essayer avec l'image brute, upscalée ET avec prétraitement, garder le meilleur
        variants = [
            (np.array(zone_img_pil), "brute"),  # Image originale
            (np.array(zone_img_upscaled), "upscaled"),  # Image agrandie
            (np.array(preprocess_for_arabic_ocr(zone_img_upscaled, apply_binarization=False).convert('RGB')), "upscaled+preprocess"),
        ]
        
        best_text = ""
        best_conf = 0.0
        best_variant = "brute"
        
        for zone_img, variant_name in variants:
            try:
                results = reader.readtext(zone_img)
                textes = [text for _, text, _ in results]
                confs = [conf for _, _, conf in results]
                texte = " ".join(textes)
                conf = sum(confs) / len(confs) if confs else 0.0
                
                if conf > best_conf or (conf == best_conf and len(texte) > len(best_text)):
                    best_text = texte
                    best_conf = conf
                    best_variant = variant_name
            except Exception as e:
                logger.debug(f"EasyOCR {variant_name} erreur: {e}")
        
        texte_final = best_text
        conf_moy = best_conf
        
        if texte_final:
            logger.info(f"📖 EasyOCR Zone {nom_zone} [{zone_lang}]: {best_variant} -> conf={conf_moy:.0%}, texte='{texte_final[:30]}...'")
        else:
            logger.warning(f"⚠️ EasyOCR Zone {nom_zone}: aucun texte détecté")
        
        statut = "ok" if conf_moy >= 0.6 and texte_final else "faible_confiance"
        resultats[nom_zone] = {
            'texte_auto': texte_final, 
            'confiance_auto': conf_moy, 
            'statut': statut, 
            'moteur': 'easyocr',
            'coords': [x1, y1, x2, y2],
            'texte_final': texte_final
        }
            
    return resultats
