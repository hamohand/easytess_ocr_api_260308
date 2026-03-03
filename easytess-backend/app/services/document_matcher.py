"""
document_matcher.py — Service d'appariement recto/verso de pièces d'identité.

Deux méthodes complémentaires :
1. Comparaison du numéro de pièce (OCR + Levenshtein)
2. Comparaison des photos d'identité (SSIM + ORB fallback)
"""
import cv2
import numpy as np
import logging
from difflib import SequenceMatcher
from PIL import Image

logger = logging.getLogger(__name__)


def comparer_numeros(texte_recto, texte_verso, seuil=0.8):
    """
    Compare les numéros de pièce extraits par OCR des deux faces.
    Utilise la similarité de Levenshtein (SequenceMatcher).

    Args:
        texte_recto: Numéro extrait du recto (str)
        texte_verso: Numéro extrait du verso (str)
        seuil: Score minimum pour considérer un match (0.0 à 1.0)

    Returns:
        dict: {
            "match": bool,
            "score": float,
            "recto": str,
            "verso": str
        }
    """
    if not texte_recto or not texte_verso:
        return {
            "match": False,
            "score": 0.0,
            "recto": texte_recto or "",
            "verso": texte_verso or "",
            "erreur": "Numéro manquant sur l'une des faces"
        }

    # Nettoyer les textes (supprimer espaces, tirets, points)
    clean_recto = "".join(c for c in texte_recto if c.isalnum())
    clean_verso = "".join(c for c in texte_verso if c.isalnum())

    score = SequenceMatcher(None, clean_recto, clean_verso).ratio()

    return {
        "match": score >= seuil,
        "score": round(score, 4),
        "recto": texte_recto,
        "verso": texte_verso
    }


def comparer_photos(image_recto_path, coords_photo_recto,
                    image_verso_path, coords_photo_verso,
                    seuil_ssim=0.4):
    """
    Compare les photos d'identité présentes sur le recto et le verso.
    Utilise SSIM (Structural Similarity) avec un fallback ORB.

    Args:
        image_recto_path: Chemin vers l'image recto
        coords_photo_recto: [x1, y1, x2, y2] coords relatives (0-1) de la photo sur le recto
        image_verso_path: Chemin vers l'image verso
        coords_photo_verso: [x1, y1, x2, y2] coords relatives (0-1) de la photo sur le verso
        seuil_ssim: Score SSIM minimum pour considérer un match

    Returns:
        dict: {
            "match": bool,
            "score_ssim": float,
            "score_orb": float | None,
            "methode_decisive": "ssim" | "orb"
        }
    """
    try:
        photo_recto = _extraire_zone(image_recto_path, coords_photo_recto)
        photo_verso = _extraire_zone(image_verso_path, coords_photo_verso)

        if photo_recto is None or photo_verso is None:
            return {
                "match": False,
                "score_ssim": 0.0,
                "score_orb": None,
                "erreur": "Impossible d'extraire la zone photo"
            }

        # Redimensionner les deux à la même taille pour SSIM
        target_size = (150, 200)  # largeur x hauteur
        photo_recto_resized = cv2.resize(photo_recto, target_size, interpolation=cv2.INTER_AREA)
        photo_verso_resized = cv2.resize(photo_verso, target_size, interpolation=cv2.INTER_AREA)

        # --- Méthode 1 : SSIM ---
        score_ssim = _calculer_ssim(photo_recto_resized, photo_verso_resized)
        logger.info(f"📊 SSIM score: {score_ssim:.4f} (seuil: {seuil_ssim})")

        if score_ssim >= seuil_ssim:
            return {
                "match": True,
                "score_ssim": round(score_ssim, 4),
                "score_orb": None,
                "methode_decisive": "ssim"
            }

        # --- Méthode 2 : ORB fallback ---
        score_orb = _calculer_orb_similarity(photo_recto, photo_verso)
        logger.info(f"📊 ORB score: {score_orb:.4f}")

        # ORB score > 0.3 est considéré comme un match raisonnable
        orb_match = score_orb >= 0.3

        return {
            "match": orb_match,
            "score_ssim": round(score_ssim, 4),
            "score_orb": round(score_orb, 4),
            "methode_decisive": "orb"
        }

    except Exception as e:
        logger.error(f"Erreur comparaison photos: {e}")
        return {
            "match": False,
            "score_ssim": 0.0,
            "score_orb": None,
            "erreur": str(e)
        }


def apparier_documents(resultats_recto, resultats_verso, config_appariement, images_info=None):
    """
    Orchestre l'appariement en combinant les deux méthodes.

    Args:
        resultats_recto: dict des résultats OCR du recto (ex: {"numeroPiece": {"texte_final": "123456789"}})
        resultats_verso: dict des résultats OCR du verso
        config_appariement: config depuis l'entité, ex: {
            "methode": "numero_piece",           # ou "photo" ou "combinee"
            "champ_commun": "numeroPiece",
            "zone_photo_recto": [x1, y1, x2, y2],
            "zone_photo_verso": [x1, y1, x2, y2]
        }
        images_info: dict optionnel {
            "recto_path": str,
            "verso_path": str
        }

    Returns:
        dict: {
            "apparie": bool,
            "confiance": float (0-1),
            "details": {
                "numero": { ... } ou None,
                "photo": { ... } ou None
            }
        }
    """
    if not config_appariement:
        return {"apparie": None, "confiance": 0.0, "details": {}, "erreur": "Pas de config d'appariement"}

    methode = config_appariement.get("methode", "combinee")
    details = {}
    scores = []

    # --- Méthode numéro ---
    if methode in ("numero_piece", "combinee"):
        champ = config_appariement.get("champ_commun", "numeroPiece")
        texte_recto = _extraire_texte_champ(resultats_recto, champ)
        texte_verso = _extraire_texte_champ(resultats_verso, champ)

        result_num = comparer_numeros(texte_recto, texte_verso)
        details["numero"] = result_num
        scores.append(result_num["score"])

    # --- Méthode photo ---
    if methode in ("photo", "combinee") and images_info:
        zone_recto = config_appariement.get("zone_photo_recto")
        zone_verso = config_appariement.get("zone_photo_verso")
        recto_path = images_info.get("recto_path")
        verso_path = images_info.get("verso_path")

        if zone_recto and zone_verso and recto_path and verso_path:
            result_photo = comparer_photos(recto_path, zone_recto, verso_path, zone_verso)
            details["photo"] = result_photo
            # Utiliser le meilleur score entre SSIM et ORB
            best_photo_score = max(
                result_photo.get("score_ssim", 0),
                result_photo.get("score_orb", 0) or 0
            )
            scores.append(best_photo_score)

    # --- Score combiné ---
    if not scores:
        return {"apparie": None, "confiance": 0.0, "details": details, "erreur": "Aucune méthode applicable"}

    confiance = sum(scores) / len(scores)

    # Décision : au moins une méthode doit matcher
    apparie = any([
        details.get("numero", {}).get("match", False),
        details.get("photo", {}).get("match", False)
    ]) if len(scores) > 1 else (confiance >= 0.5)

    return {
        "apparie": apparie,
        "confiance": round(confiance, 4),
        "details": details
    }


# =============================================================================
# FONCTIONS UTILITAIRES INTERNES
# =============================================================================

def _extraire_zone(image_path, coords):
    """Extrait une zone d'une image à partir de coordonnées relatives (0-1)."""
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return None

        h, w = img.shape[:2]
        x1 = int(coords[0] * w)
        y1 = int(coords[1] * h)
        x2 = int(coords[2] * w)
        y2 = int(coords[3] * h)

        # Clamp
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return None

        return img[y1:y2, x1:x2]

    except Exception as e:
        logger.error(f"Erreur extraction zone: {e}")
        return None


def _calculer_ssim(img1, img2):
    """Calcule le SSIM entre deux images (même taille requise)."""
    try:
        from skimage.metrics import structural_similarity as ssim

        # Convertir en niveaux de gris
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY) if len(img1.shape) == 3 else img1
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY) if len(img2.shape) == 3 else img2

        score = ssim(gray1, gray2)
        return float(score)

    except Exception as e:
        logger.error(f"Erreur SSIM: {e}")
        return 0.0


def _calculer_orb_similarity(img1, img2, min_matches=5):
    """Calcule un score de similarité basé sur ORB features (0-1)."""
    try:
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY) if len(img1.shape) == 3 else img1
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY) if len(img2.shape) == 3 else img2

        orb = cv2.ORB_create(nfeatures=500)
        kp1, des1 = orb.detectAndCompute(gray1, None)
        kp2, des2 = orb.detectAndCompute(gray2, None)

        if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
            return 0.0

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des1, des2)
        matches = sorted(matches, key=lambda x: x.distance)

        if len(matches) < min_matches:
            return 0.0

        # Score basé sur le nombre de bons matches et leur qualité
        good_matches = [m for m in matches if m.distance < 60]
        total_kp = min(len(kp1), len(kp2))

        if total_kp == 0:
            return 0.0

        score = len(good_matches) / total_kp
        return min(1.0, score)

    except Exception as e:
        logger.error(f"Erreur ORB: {e}")
        return 0.0


def _extraire_texte_champ(resultats, champ):
    """Extrait le texte final d'un champ dans les résultats OCR.
    
    Recherche flexible : essaie la clé exacte, puis une recherche
    normalisée (insensible à la casse, underscores, tirets).
    Ex: "numeroPiece" matche "numpiece", "numero_piece", "NUMEROPIECE", etc.
    """
    if not resultats:
        return None

    # 1. Clé exacte
    champ_data = resultats.get(champ)

    # 2. Fallback : recherche normalisée
    if champ_data is None:
        champ_norm = _normaliser_cle(champ)
        for key, value in resultats.items():
            if _normaliser_cle(key) == champ_norm:
                champ_data = value
                logger.info(f"🔗 Champ '{champ}' trouvé via match normalisé → '{key}'")
                break

    if champ_data is None:
        return None

    if isinstance(champ_data, dict):
        return champ_data.get("texte_final") or champ_data.get("texte") or champ_data.get("text")
    elif isinstance(champ_data, str):
        return champ_data
    return None


def _normaliser_cle(cle):
    """Normalise une clé pour comparaison flexible.
    'numeroPiece' → 'numeropiece', 'numero_piece' → 'numeropiece'
    """
    return cle.lower().replace('_', '').replace('-', '').replace(' ', '')
