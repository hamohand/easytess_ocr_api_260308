import json
import os
from datetime import datetime
from PIL import Image, ImageDraw
import base64
from io import BytesIO

class EntityManager:
    def __init__(self, entities_dir="entities"):
        self.entities_dir = entities_dir
        os.makedirs(entities_dir, exist_ok=True)
    
    def sauvegarder_entite(self, nom_entite, zones, image_path=None, description="", cadre_reference=None):
        """Sauvegarde une entité simple (mono-page) avec ses zones et cadre de référence optionnel"""
        entite_data = {
            'nom': nom_entite,
            'description': description,
            'type': 'simple',
            'date_creation': datetime.now().isoformat(),
            'image_reference': image_path,
            'zones': zones,
            'cadre_reference': cadre_reference,
            'metadata': {
                'nombre_zones': len(zones),
                'image_dimensions': self._get_image_dimensions(image_path) if image_path else None
            }
        }
        
        fichier_entite = os.path.join(self.entities_dir, f"{nom_entite}.json")
        
        with open(fichier_entite, 'w', encoding='utf-8') as f:
            json.dump(entite_data, f, ensure_ascii=False, indent=2)
        
        return fichier_entite
    
    def sauvegarder_entite_composite(self, nom_entite, pages, description="", appariement=None):
        """Sauvegarde une entité composite (multi-pages, ex: recto/verso).
        
        Args:
            nom_entite: Nom unique de l'entité
            pages: Dict de pages, ex: {
                "recto": { "zones": [...], "image_path": "...", "cadre_reference": {...} },
                "verso": { "zones": [...], "image_path": "...", "cadre_reference": {...} }
            }
            description: Description de l'entité
            appariement: Config d'appariement optionnelle, ex:
                { "methode": "numero_piece", "champ_commun": "numeroPiece" }
        """
        pages_data = {}
        total_zones = 0
        
        for page_id, page_info in pages.items():
            zones = page_info.get('zones', [])
            image_path = page_info.get('image_path')
            cadre_reference = page_info.get('cadre_reference')
            zone_photo = page_info.get('zone_photo')  # [x1, y1, x2, y2] coords relatives de la photo d'identité
            total_zones += len(zones)
            
            pages_data[page_id] = {
                'image_reference': image_path,
                'zones': zones,
                'cadre_reference': cadre_reference,
                'zone_photo': zone_photo,
                'metadata': {
                    'nombre_zones': len(zones),
                    'image_dimensions': self._get_image_dimensions(image_path) if image_path else None
                }
            }
        
        entite_data = {
            'nom': nom_entite,
            'description': description,
            'type': 'composite',
            'date_creation': datetime.now().isoformat(),
            'pages': pages_data,
            'appariement': appariement,
            'metadata': {
                'nombre_pages': len(pages_data),
                'nombre_zones_total': total_zones
            }
        }
        
        fichier_entite = os.path.join(self.entities_dir, f"{nom_entite}.json")
        
        with open(fichier_entite, 'w', encoding='utf-8') as f:
            json.dump(entite_data, f, ensure_ascii=False, indent=2)
        
        return fichier_entite
    
    def composer_entite_composite(self, nom_entite, entite_recto_nom, entite_verso_nom,
                                   description='', appariement=None):
        """Crée une entité composite à partir de deux entités simples existantes.
        
        Args:
            nom_entite: Nom de la nouvelle entité composite
            entite_recto_nom: Nom de l'entité simple pour le recto
            entite_verso_nom: Nom de l'entité simple pour le verso
            description: Description de l'entité composite
            appariement: Config d'appariement optionnelle
        """
        entite_recto = self.charger_entite(entite_recto_nom)
        entite_verso = self.charger_entite(entite_verso_nom)
        
        if not entite_recto:
            raise ValueError(f"Entité recto '{entite_recto_nom}' non trouvée")
        if not entite_verso:
            raise ValueError(f"Entité verso '{entite_verso_nom}' non trouvée")
        
        if self.is_composite(entite_recto):
            raise ValueError(f"'{entite_recto_nom}' est déjà composite, utilisez une entité simple")
        if self.is_composite(entite_verso):
            raise ValueError(f"'{entite_verso_nom}' est déjà composite, utilisez une entité simple")
        
        # Construire les pages à partir des entités simples
        pages = {
            'recto': {
                'image_path': entite_recto.get('image_reference'),
                'zones': entite_recto.get('zones', []),
                'cadre_reference': entite_recto.get('cadre_reference'),
                'zone_photo': None,
                'entite_source': entite_recto_nom
            },
            'verso': {
                'image_path': entite_verso.get('image_reference'),
                'zones': entite_verso.get('zones', []),
                'cadre_reference': entite_verso.get('cadre_reference'),
                'zone_photo': None,
                'entite_source': entite_verso_nom
            }
        }
        
        return self.sauvegarder_entite_composite(
            nom_entite, pages, description, appariement
        )
    
    @staticmethod
    def is_composite(entite):
        """Retourne True si l'entité est composite (multi-pages)"""
        return entite.get('type') == 'composite' or 'pages' in entite
    
    def charger_entite(self, nom_entite):
        """Charge une entité (simple ou composite)"""
        fichier_entite = os.path.join(self.entities_dir, f"{nom_entite}.json")
        
        if os.path.exists(fichier_entite):
            with open(fichier_entite, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    def lister_entites(self):
        """Liste toutes les entités disponibles"""
        entites = []
        if not os.path.exists(self.entities_dir):
            return []
            
        for fichier in os.listdir(self.entities_dir):
            if fichier.endswith('.json'):
                nom = fichier[:-5]  # Retirer .json
                entite_data = self.charger_entite(nom)
                if entite_data:
                    # Ajouter le type si absent (rétro-compatibilité)
                    if 'type' not in entite_data:
                        entite_data['type'] = 'composite' if 'pages' in entite_data else 'simple'
                    entites.append(entite_data)
        return entites
    
    def _get_image_dimensions(self, image_path):
        """Récupère les dimensions d'une image"""
        try:
            with Image.open(image_path) as img:
                return {'width': img.width, 'height': img.height}
        except:
            return None
    
    def generer_image_annotation(self, image_path, zones, output_path=None, cadre_reference=None):
        """Génère une image avec les zones annotées
        Args:
            image_path: Chemin image source
            zones: Liste des zones
            output_path: Chemin sortie (optonnel)
            cadre_reference: Dikto du cadre pour transformation des coords (ou None)
        """
        try:
            with Image.open(image_path) as img:
                draw = ImageDraw.Draw(img)
                img_w, img_h = img.size
                
                # Paramètres du cadre par défaut (Image entière)
                x_ref_min = 0.0
                y_ref_min = 0.0
                larg_cadre = 1.0
                haut_cadre = 1.0
                
                # Si cadre fourni, calculer les paramètres de transformation
                if cadre_reference and cadre_reference.get('haut') and cadre_reference.get('gauche_bas'):
                     # Récupérer les ancres (supposées normalisées 0-1 dans l'Image)
                     # Note: Ici on utilise les positions "théoriques" ou détectées stockées dans l'entité
                     # Si l'entité a été sauvegardée, position_base contient les coords dans l'IMAGE.
                     
                     # Attention: position_base dans le JSON est [x, y]
                     gb = cadre_reference['gauche_bas'].get('position_base', [0, 1])
                     h = cadre_reference['haut'].get('position_base', [0.5, 0])
                     d = cadre_reference['droite'].get('position_base', [1, 0])
                     
                     x_ref_min = gb[0]
                     y_ref_min = h[1]
                     larg_cadre = d[0] - gb[0]
                     haut_cadre = gb[1] - h[1]
                
                for i, zone in enumerate(zones):
                    coords = zone['coords']
                    # Coords sont [x1, y1, x2, y2] RELATIFS AU CADRE
                    
                    # 1. Transformer Relatif Cadre -> Relatif Image
                    rx1, ry1, rx2, ry2 = coords
                    gx1 = rx1 * larg_cadre + x_ref_min
                    gy1 = ry1 * haut_cadre + y_ref_min
                    gx2 = rx2 * larg_cadre + x_ref_min
                    gy2 = ry2 * haut_cadre + y_ref_min
                    
                    # 2. Transformer Relatif Image -> Absolu Pixels
                    x1 = int(gx1 * img_w)
                    y1 = int(gy1 * img_h)
                    x2 = int(gx2 * img_w)
                    y2 = int(gy2 * img_h)
                    
                    nom = zone.get('nom', f'Zone {i+1}')
                    
                    # Dessiner le rectangle
                    draw.rectangle([x1, y1, x2, y2], outline='red', width=3)
                    
                    # Ajouter le nom de la zone
                    draw.text((x1, y1-25), nom, fill='blue')
                    
                    # Ajouter un numéro
                    draw.ellipse([x1-15, y1-15, x1, y1], fill='green')
                    draw.text((x1-10, y1-12), str(i+1), fill='white')
                
                if output_path:
                    img.save(output_path)
                    return output_path
                else:
                    # Retourner en base64 pour l'affichage web
                    buffered = BytesIO()
                    img.save(buffered, format="JPEG", quality=85)
                    return base64.b64encode(buffered.getvalue()).decode()
                    
        except Exception as e:
            print(f"Erreur génération image: {e}")
            return None
