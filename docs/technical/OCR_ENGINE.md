# ⚙️ Moteur OCR & Analyse Hybride

Ce document détaille le fonctionnement interne du moteur OCR (`ocr_engine.py`) d'EasyTess. Il explique comment le système combine plusieurs technologies pour garantir une extraction de données précise et robuste.

---

## 🏗️ Architecture

Le moteur utilise une approche **hybride** combinant plusieurs bibliothèques pour tirer profit de leurs forces respectives :

| Technologie | Usage Principal | Pourquoi ? |
|-------------|-----------------|------------|
| **Tesseract** | Analyse Globale & Zones simples | Rapide, bonne détection structurelle, standard industriel. |
| **EasyOCR** | Zones complexes, manuscrites, faible contraste | Plus lent mais beaucoup plus robuste (Deep Learning), supporte mieux les textes stylisés. |
| **ZBar (PyZbar)** | Codes-barres & QR Codes | Détection spécialisée et ultra-rapide des codes 1D/2D. |

---

## 📐 Système de Cadre de Référence (AABB)

Pour garantir que les zones d'extraction (Nom, Date, etc.) sont toujours localisées au bon endroit, même si l'image est décalée, scannée de travers ou redimensionnée, nous utilisons un **Cadre de Référence Dynamique**.

### Ancienne Méthode (Legacy)
Basée sur 3 points d'ancrage (Haut, Droite, Gauche-Bas).

### Nouvelle Méthode : AABB (Axis-Aligned Bounding Box) à 4 ancres
Le cadre est défini par **4 points d'ancrage** indépendants (étiquettes) :

1.  **HAUT (📍)** : Définit la limite supérieure (Y_min).
2.  **DROITE (📍)** : Définit la limite droite (X_max).
3.  **GAUCHE (📍)** : Définit la limite gauche (X_min).
4.  **BAS (📍)** : Définit la limite inférieure (Y_max).

Pour chaque ancre, 3 méthodes de détection sont possibles, évaluées en priorité :
1. **Mot-Clé / Regex OCR** : Le texte est recherché sur le document.
2. **Template Image** : Une zone d'image est cherchée par Pattern Matching OpenCV.
3. **Ancre Algorithmique (Formule de Secours)** *(Nouveau)* : Si l'ancre n'est pas détectée visuellement, elle peut être déduite mathématiquement des autres !

### Ancres Algorithmiques (Fallback Rules)
Si l'OCR ou l'image échouent à trouver un bord (ex: "BAS"), le système peut utiliser une formule mathématique (ex: `H + 0.40`).
- Les variables disponibles sont `H`, `B`, `G`, `D`.
- Le moteur gère les dépendances croisées en effectuant plusieurs passes de résolution via `ast.parse` en Python, garantissant que les formules sont sécurisées et robustes.

### Calcul du Cadre
Une fois ces 4 ancres détectées ou calculées :
- **X_min** = GAUCHE.x
- **X_max** = DROITE.x
- **Y_min** = HAUT.y
- **Y_max** = BAS.y

Cela forme un rectangle précis qui "enferme" la zone de recadrage du document.

> **Note :** Le système convertit automatiquement les anciens modèles 3 ancres vers le nouveau format 4 ancres à l'ouverture.

---

## ✂️ Pipeline d'Analyse (Physical Crop)

Pour assurer une fiabilité maximale ("Region of Interest" stricte), l'analyse suit ces étapes rigoureuses :

1.  **OCR Global** : Scan rapide de l'image entière pour trouver les ancres (Textes ou Templates).
2.  **Résolution Algorithmique** : Évaluation des "Formules de Secours" pour les ancres non trouvées physiquement.
3.  **Calcul du Cadre** : Détermination des coordonnées du cadre AABB complet en pixels.
4.  **Rognage Physique (Physical Crop)** :
    *   Le système crée une **copie temporaire** de l'image, coupée *exactement* aux bords du cadre.
    *   Tout le reste de l'image (bruit, bords de table, autres documents) est physiquement supprimé.
5.  **Analyse des Zones** :
    *   L'extraction (Tesseract/EasyOCR) se fait sur cette image rognée.
    *   Les coordonnées des zones sont relatives à ce crop.
5.  **Re-mapping des Coordonnées** :
    *   Une fois les textes extraits, les coordonnées des zones trouvées sont **reconverties** vers le repère de l'image originale.
    *   Cela permet à l'interface utilisateur d'afficher les résultats (rectangles bleus) exactement au bon endroit sur l'image source.

---

## 📊 Visualisation des résultats

Dans l'interface de test (`OCR Upload`) :

- **Avant Analyse (🟩 Vert)** : Affiche les zones telles qu'elles sont définies dans le modèle.
    *   *Position approximative (car le cadre n'est pas encore détecté).*
- **Après Analyse (🟦 Bleu)** : Affiche les zones réellement analysées.
    *   *Position exacte, alignée sur le document grâce au calcul du cadre.*

---

## 🛠️ Dépannage Technique

### "Pas de cadre de référence détecté"
Si les logs indiquent cette erreur, l'analyse bascule en mode "Image Complète" (fallback) sans crop. Les zones risquent d'être décalées.
*   **Solution** : Vérifiez que l'entité possède bien ses 4 ancres, soit par reconnaissance OCR, Template visuel, ou Formule mathématique de secours (Fallback Rule).

### Zones affichées en haut à gauche (0,0)
Signifie que le re-mapping des coordonnées a échoué ou que le cadre n'a pas été trouvé.
*   **Solution** : Sauvegardez à nouveau l'entité avec la dernière version de l'éditeur pour mettre à jour ses métadonnées.
