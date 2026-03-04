// models.ts - Interfaces TypeScript pour l'API EasyTess

export interface Zone {
    id?: number;
    nom: string;
    coords: [number, number, number, number]; // [x1, y1, x2, y2]
    type?: 'text' | 'qrcode' | 'barcode';
    lang?: 'fra' | 'ara' | 'ara+fra' | 'eng';  // Langue OCR pour cette zone
    preprocess?: 'auto' | 'arabic_textured' | 'latin_simple' | 'none';  // Mode prétraitement
    valeurs_attendues?: string[];
}

// Étiquette de référence pour le cadre utile
export interface EtiquetteReference {
    labels: string[];                        // Textes à chercher (ex: ["PASSPORT", "PASSEPORT"])
    position_base: [number, number];         // Position (x, y) sur l'image de base (0-1)
    template_coords?: [number, number, number, number]; // NEW: Image template region [x1, y1, x2, y2] relative (0-1)
    offset_x?: number;                       // Décalage X en pixels (optionnel)
    offset_y?: number;                       // Décalage Y en pixels (optionnel)
    fallback_rule?: string;                  // NOUVEAU: Règle de calcul algorithmique (ex: "H + 0.35")
}

// Cadre de référence pour définir le système de coordonnées
export interface CadreReference {
    // NOUVEAU SYSTÈME (HAUT, DROITE, GAUCHE, BAS) - 4 étiquettes
    haut: EtiquetteReference;        // Y min
    droite: EtiquetteReference;      // X max
    gauche: EtiquetteReference;      // X min
    bas: EtiquetteReference;         // Y max

    // Backward compatibility (deprecated - old 3-anchor system)
    gauche_bas?: EtiquetteReference;  // X min, Y max (sera migré automatiquement)

    // Legacy support (deprecated)
    origine?: EtiquetteReference;
    largeur?: EtiquetteReference;
    hauteur?: EtiquetteReference;

    // Dimensions de l'image de référence
    image_base_dimensions?: {
        width: number;
        height: number;
    };

    // Nouvelle propriété: Dimensions absolues et angle (L, H, A)
    dimensions_absolues?: {
        largeur: number;  // en pixels
        hauteur: number;  // en pixels
        angle: number;    // en degrés
    };
}

// Legacy: Ancre pour le repère géométrique (deprecated, use CadreReference)
export interface AncreRepere {
    id: string;
    labels: string[];
    position_base: [number, number];
}

export interface Repere {
    ancres: AncreRepere[];
    image_base_dimensions?: { width: number; height: number };
}

export interface Entite {
    nom: string;
    description?: string;
    date_creation?: string;
    image_reference?: string;
    zones: Zone[];
    cadre_reference?: CadreReference;        // NOUVEAU: Cadre de référence à 3 étiquettes
    repere?: Repere;                         // Legacy (deprecated)
    metadata?: {
        nombre_zones: number;
        image_dimensions?: {
            width: number;
            height: number;
        };
    };
}

export interface ResultatOCR {
    texte_auto: string;
    confiance_auto: number;
    statut: 'ok' | 'faible_confiance' | 'echec' | 'corrigé';
    moteur: 'tesseract' | 'easyocr' | 'aucun';
    ameliore_par?: string;
    texte_final?: string;
    texte_corrige_manuel?: string;
}

export interface AnalyseResponse {
    success: boolean;
    resultats: { [zoneName: string]: ResultatOCR };
    alertes: string[];
    stats_moteurs: { [moteur: string]: number };
}

export interface UploadResponse {
    success: boolean;
    filename: string;
    saved_filename: string;
    url: string;
}

export interface ImageEntiteUploadResponse {
    success: boolean;
    filepath: string;
    filename: string;
    image_url: string;
    dimensions: {
        width: number;
        height: number;
    };
}

// Batch OCR Analysis
export interface BatchUploadResponse {
    success: boolean;
    files: { filename: string; saved_filename: string; error?: string }[];
}

export interface BatchFileResult {
    filename: string;
    success: boolean;
    resultats?: { [zoneName: string]: ResultatOCR };
    alertes?: string[];
    stats_moteurs?: { [moteur: string]: number };
    error?: string;
}

export interface BatchAnalyseResponse {
    success: boolean;
    total: number;
    reussis: number;
    echoues: number;
    resultats_batch: BatchFileResult[];
}

// ─── Document extraction models ───────────────────────────

export interface DocumentBloc {
    type: 'texte' | 'tableau';
    contenu?: string;           // Pour type 'texte'
    page?: number;
    numero?: number;            // Pour type 'tableau'
    lignes?: { [key: string]: string }[];
    metadata?: TableMetadata;
}

export interface TableMetadata {
    nb_lignes: number;
    nb_colonnes: number;
    a_entete: boolean;
    entetes?: string[];
    bbox?: { x0: number; y0: number; x1: number; y1: number };
}

export interface PageStats {
    page: number;
    nb_textes: number;
    nb_tableaux: number;
}

export interface ExtractionStats {
    total_pages: number;
    pages_traitees: number;
    total_blocs: number;
    nb_textes: number;
    nb_tableaux: number;
    strategie_utilisee: string;
    detail_pages: PageStats[];
}

export interface ExtractDocumentResponse {
    success: boolean;
    filename: string;
    format?: 'pdf' | 'docx';
    total_blocs: number;
    contenu: DocumentBloc[];
    statistiques?: ExtractionStats;
}

export interface ConvertPdfResponse {
    success: boolean;
    filename_source: string;
    filename_docx: string;
    statistiques: ExtractionStats;
    message: string;
}

// ─── Composite entity models ───────────────────────────

export interface PageComposite {
    image_path?: string;
    zones: Zone[];
    cadre_reference?: CadreReference;
    zone_photo?: [number, number, number, number];
    entite_source?: string; // Nom de l'entité simple source (mode compose)
}

export interface AppariementConfig {
    methode: 'numero_piece' | 'photo' | 'combinee';
    champ_commun?: string;
}

export interface EntiteComposite {
    nom: string;
    description?: string;
    type: 'composite';
    date_creation?: string;
    pages: {
        recto: PageComposite;
        verso: PageComposite;
    };
    appariement?: AppariementConfig;
}

export interface AppariementDetailNumero {
    match: boolean;
    score: number;
    recto: string;
    verso: string;
    erreur?: string;
}

export interface AppariementDetailPhoto {
    match: boolean;
    score_ssim: number;
    score_orb?: number;
    methode_decisive?: string;
    erreur?: string;
}

export interface AppariementResult {
    apparie: boolean | null;
    confiance: number;
    details: {
        numero?: AppariementDetailNumero;
        photo?: AppariementDetailPhoto;
    };
    erreur?: string;
}

export interface AppariementResponse {
    success: boolean;
    entite: string;
    resultats_recto: { [key: string]: ResultatOCR };
    alertes_recto: string[];
    resultats_verso: { [key: string]: ResultatOCR };
    alertes_verso: string[];
    resultats_fusionnes: { [key: string]: ResultatOCR };
    appariement: AppariementResult;
}
