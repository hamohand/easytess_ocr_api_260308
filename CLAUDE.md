# CLAUDE.md — Guide de développement pour agents IA

Ce fichier décrit le projet EasyTess pour les agents IA qui contribuent au code.

## Vue d'ensemble

**EasyTess** est une plateforme d'analyse OCR et d'extraction de documents, composée d'un backend Flask (Python) et d'un frontend Angular (TypeScript). Deux sections principales :
1. **EasyTess-OCR** : Analyse OCR avec gestion d'entités (zones, ancres, QR codes)
2. **Extraction de Documents** : Extraction de contenu structuré (texte + tableaux) depuis PDF/DOCX, conversion PDF → Word

## Architecture

```
easytess_api/
├── easytess-backend/           # API Flask (port 8082)
│   ├── run.py                  # Point d'entrée
│   ├── config.py               # Configuration
│   ├── app/
│   │   ├── __init__.py         # create_app(), CORS, blueprints
│   │   ├── api/
│   │   │   ├── file_routes.py      # Upload, upload-batch, export JSON
│   │   │   ├── ocr_routes.py       # Analyse simple, batch sync, batch async (SSE), dossier
│   │   │   ├── entity_routes.py    # CRUD entités
│   │   │   ├── docx_routes.py      # Extraction DOCX (legacy, single endpoint)
│   │   │   └── document_routes.py  # Extraction unifiée PDF/DOCX + conversion PDF→Word
│   │   ├── services/
│   │   │   ├── ocr_engine.py       # Moteurs OCR (Tesseract + EasyOCR), analyse hybride, AABB
│   │   │   ├── entity_manager.py   # CRUD fichiers JSON entités
│   │   │   ├── image_matcher.py    # Template matching ORB
│   │   │   ├── pdf_extractor.py    # Extraction contenu PDF (texte + tableaux) — pdfplumber
│   │   │   ├── docx_extractor.py   # Extraction contenu Word (texte + tableaux) — python-docx
│   │   │   └── pdf_to_docx.py      # Conversion PDF → Word (.docx)
│   │   └── utils/
│   │       ├── pdf_utils.py        # Conversion PDF → image (pour OCR)
│   │       ├── image_utils.py      # Traitement images, patch Pillow
│   │       └── qrcode_utils.py     # Détection QR codes / codes-barres
│   ├── entities/               # Stockage entités (JSON)
│   └── uploads/                # Fichiers uploadés
│
├── easytess-frontend/          # Angular 18+ (port 4200)
│   └── src/app/
│       ├── app.component.*             # Layout principal, 2 sections (OCR / Extraction)
│       ├── components/
│       │   ├── ocr-upload.component.*          # Section OCR : analyse (3 modes: single/multi/folder)
│       │   ├── entity-creator.component.*      # Section OCR : création entités
│       │   └── document-extractor.component.*  # Section Extraction : PDF/DOCX + conversion
│       └── services/
│           ├── file.service.ts        # Upload simple/batch, export JSON
│           ├── ocr.service.ts         # Analyse simple/batch/async, SSE progress
│           ├── entity.service.ts      # CRUD entités
│           ├── document.service.ts    # Extraction de documents + conversion PDF→DOCX
│           └── models.ts              # Interfaces TypeScript (OCR + Document extraction)
│
└── docs/                       # Documentation
```

## Commandes essentielles

```bash
# Backend
cd easytess-backend
pip install -r requirements.txt
python run.py                    # → http://localhost:8082

# Frontend
cd easytess-frontend
npm install
ng serve                         # → http://localhost:4200

# Build frontend (dev)
npx ng build --configuration=development

# Test extraction documents
cd easytess-backend
python test_document_extraction.py [fichier.pdf ou fichier.docx]
```

## Points d'attention

### Backend — Flask Context
- `ocr_engine.py` utilise `flask.current_app.config` dans `detecter_ancres()` (ligne ~440)
- **Les threads en arrière-plan** doivent envelopper leur code dans `with app.app_context():`
- **Ne PAS utiliser `ThreadPoolExecutor`** car les sous-threads perdent le contexte Flask
- Utiliser un seul thread + traitement séquentiel dans `app.app_context()`

### Backend — Coordonnées (OCR)
- Les coordonnées des zones sont **relatives** (0.0 à 1.0), pas en pixels
- Le système AABB utilise **4 ancres** indépendantes : Haut (Y_min), Bas (Y_max), Gauche (X_min), Droite (X_max)
- Chaque ancre peut être détectée par : **texte OCR/regex**, **template image (ORB)**, ou **formule de secours (`fallback_rule`)**
- `analyser_hybride()` rogne physiquement l'image selon le cadre détecté

### Backend — Ancres Algorithmiques (`fallback_rule`)
- Si une ancre n'est pas trouvée par OCR/template, le champ `fallback_rule` permet de la calculer via une formule mathématique
- Variables disponibles : `H` (Haut Y), `B` (Bas Y), `G` (Gauche X), `D` (Droite X)
- Exemples : `H + 0.40`, `H + (D - G) * 1.58`
- Évaluation sécurisée via `ast.parse` (Python) — seuls les opérateurs arithmétiques sont autorisés
- Résolution multi-passes (jusqu'à 4 itérations) pour gérer les dépendances croisées entre variables
- Implémentée dans `entity_routes.py` (`detecter_etiquettes`) et `ocr_engine.py` (`analyser_hybride`)

### Backend — Extraction de documents
- `pdf_extractor.py` retourne un tuple `(content, stats)` — l'ancien code ne retournait que `content`
- **4 stratégies de détection des tableaux** : `auto`, `standard`, `text`, `lines_strict`
- `auto` essaie `standard` puis fallback `text` si aucun tableau détecté
- Les métadonnées de tableaux incluent en-têtes, bbox, dimensions
- `pdf_to_docx.py` reconstruit un .docx à partir du contenu structuré

### Frontend — 2 sections distinctes
- **Section "EasyTess — OCR"** : analyse OCR + gestion des entités (sous-onglets)
- **Section "Extraction de Documents"** : 3 modes (Unifiée / PDF / Conversion PDF→Word)
- Navigation via `activeSection` signal (`'ocr' | 'extraction'`)
- Le composant `document-extractor` utilise des **signals Angular** et `FormsModule` pour les options

### Frontend — Signaux Angular
- Tous les composants utilisent des **signals Angular** (pas de BehaviorSubject)
- OCR : 3 modes : `single`, `multi`, `folder` (toggle via `activeMode` signal)
- Extraction : 3 modes : `unified`, `pdf`, `convert`
- SSE via `EventSource` natif avec `NgZone.run()` pour la détection de changements
- Cleanup du `EventSource` dans `ngOnDestroy()`

### Langues OCR
- Par défaut : Arabe + Français (`ara+fra` pour Tesseract, `['ar', 'en']` pour EasyOCR)
- Configurable par zone via le champ `lang`

## Endpoints API principaux

### OCR & Fichiers

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| POST | `/api/upload` | Upload fichier unique |
| POST | `/api/upload-batch` | Upload multi-fichiers |
| POST | `/api/analyser` | Analyse OCR fichier unique |
| POST | `/api/analyser-batch` | Analyse batch synchrone |
| POST | `/api/analyser-batch-async` | Analyse batch async → retourne `job_id` |
| GET | `/api/batch-progress/<job_id>` | SSE progression temps réel |
| GET | `/api/batch-result/<job_id>` | Polling fallback progression |
| POST | `/api/analyser-dossier` | Analyse dossier côté serveur |
| POST | `/api/export-json-file` | Export JSON résultats |
| POST | `/api/export-json-batch` | Export JSON batch |
| GET/POST | `/api/entites` | Lister / créer entités |
| GET/PUT/DELETE | `/api/entites/<nom>` | CRUD entité |
| POST | `/api/detecter-etiquettes` | Détection des ancres AABB (OCR + template + fallback_rule) |
| POST | `/api/sauvegarder-entite` | Sauvegarde entité avec zones, ancres et fallback_rules |

### Extraction & Conversion de documents

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| POST | `/api/extract-pdf` | Extraction contenu PDF (texte + tableaux) |
| POST | `/api/extract-docx` | Extraction contenu Word (.docx) |
| POST | `/api/extract-document` | Extraction unifiée (PDF ou DOCX, auto-détection) |
| POST | `/api/convert-pdf-to-docx` | Conversion PDF → Word (.docx) avec téléchargement |

#### Paramètres communs (`extract-*` et `convert-*`)
- `file` : fichier PDF ou DOCX (obligatoire)
- `table_columns` : JSON array d'indices de colonnes (optionnel, ex: `[0, 2]`)
- `pages` : JSON array de pages 1-based (optionnel, PDF uniquement, ex: `[1, 3]`)
- `strategy` : Stratégie de détection tableaux (optionnel, PDF uniquement) — `auto` | `standard` | `text` | `lines_strict`
- `download` : `true`/`false` (pour `convert-pdf-to-docx` uniquement)

## Conventions

- **CSS Budget** : `entity-creator.component.css` dépasse le budget production (~12 kB). Le build `--configuration=development` fonctionne toujours.
- **Pas de tests automatisés** : Tester manuellement via le navigateur ou `test_document_extraction.py`.
- **Stockage** : Entités en JSON dans `entities/`, uploads dans `uploads/`.
- **Pas d'auth** : L'API est ouverte (usage interne).
