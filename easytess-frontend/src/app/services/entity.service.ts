import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Entite, Zone, ImageEntiteUploadResponse, CadreReference, EntiteComposite, AppariementConfig } from './models';

@Injectable({
    providedIn: 'root'
})
export class EntityService {
    private apiUrl = 'http://localhost:8082/api';

    constructor(private http: HttpClient) { }

    /**
     * Liste toutes les entités disponibles
     */
    listerEntites(): Observable<Entite[]> {
        return this.http.get<Entite[]>(`${this.apiUrl}/entites`);
    }

    /**
     * Récupère une entité spécifique
     * @param nom - Nom de l'entité
     */
    getEntite(nom: string): Observable<Entite> {
        return this.http.get<Entite>(`${this.apiUrl}/entite/${nom}`);
    }

    /**
     * Définit une entité comme active (pour l'analyse)
     * @param nom - Nom de l'entité, ou 'none' pour désactiver
     */
    setEntiteActive(nom: string): Observable<{ success: boolean; active: string | null }> {
        return this.http.post<{ success: boolean; active: string | null }>(
            `${this.apiUrl}/set-entite-active/${nom}`,
            {}
        );
    }

    /**
     * Upload une image de référence pour une entité
     * @param file - Fichier image
     */
    uploadImageEntite(file: File): Observable<ImageEntiteUploadResponse> {
        const formData = new FormData();
        formData.append('image', file);
        return this.http.post<ImageEntiteUploadResponse>(`${this.apiUrl}/upload-image-entite`, formData);
    }

    /**
     * Sauvegarde une nouvelle entité (Angular-ready: envoie tout d'un coup)
     * @param nom - Nom de l'entité
     * @param zones - Liste des zones définies
     * @param imageFilename - Nom du fichier image uploadé
     * @param description - Description optionnelle
     * @param cadre_reference - Cadre de référence (3 étiquettes: haut, droite, gauche_bas)
     */
    sauvegarderEntite(
        nom: string,
        zones: Zone[],
        imageFilename?: string,
        description?: string,
        cadre_reference?: CadreReference
    ): Observable<{ success: boolean }> {
        const body = {
            nom,
            zones,
            image_filename: imageFilename,
            description,
            cadre_reference  // Cadre de référence à 3 étiquettes
        };
        return this.http.post<{ success: boolean }>(`${this.apiUrl}/sauvegarder-entite`, body);
    }

    /**
     * Modifie une zone existante dans une entité
     * @param nomEntite - Nom de l'entité
     * @param zoneId - ID de la zone
     * @param zone - Nouvelles données de la zone
     */
    modifierZone(nomEntite: string, zoneId: number, zone: Zone): Observable<{ success: boolean }> {
        return this.http.put<{ success: boolean }>(
            `${this.apiUrl}/entite/${nomEntite}/modifier-zone/${zoneId}`,
            zone
        );
    }

    /**
     * Supprime une zone d'une entité
     * @param nomEntite - Nom de l'entité
     * @param zoneId - ID de la zone
     */
    supprimerZone(nomEntite: string, zoneId: number): Observable<{ success: boolean }> {
        return this.http.delete<{ success: boolean }>(
            `${this.apiUrl}/entite/${nomEntite}/supprimer-zone/${zoneId}`
        );
    }

    /**
     * Supprime une entité complète
     * @param nom - Nom de l'entité à supprimer
     */
    supprimerEntite(nom: string): Observable<{ success: boolean }> {
        return this.http.delete<{ success: boolean }>(`${this.apiUrl}/entite/${nom}`);
    }

    /**
     * Détecte automatiquement les positions des étiquettes du cadre de référence via OCR
     * @param filename - Nom du fichier image
     * @param etiquettes - Objet avec les labels à chercher pour chaque étiquette
     */
    detecterEtiquettes(
        filename: string,
        etiquettes: {
            haut?: { labels?: string[], template_coords?: number[] } | string[];
            droite?: { labels?: string[], template_coords?: number[] } | string[];
            gauche?: { labels?: string[], template_coords?: number[] } | string[];
            bas?: { labels?: string[], template_coords?: number[] } | string[];
            gauche_bas?: string[]; // Legacy (toujours string[])
            origine?: string[]; // Legacy
            largeur?: string[]; // Legacy
            hauteur?: string[]; // Legacy
        }
    ): Observable<{
        success: boolean;
        toutes_trouvees: boolean;
        positions: {
            [key: string]: { x: number; y: number; found: boolean; text?: string; bbox?: [number, number, number, number]; }
        };
        image_dimensions?: { width: number; height: number };
        error?: string;
    }> {
        return this.http.post<any>(`${this.apiUrl}/detecter-etiquettes`, {
            filename,
            etiquettes
        });
    }

    // ─── Composite entity methods ───────────────────────────

    /**
     * Upload une image pour une page d'entité composite
     */
    uploadImageEntitePage(file: File, pageId: string): Observable<ImageEntiteUploadResponse> {
        const formData = new FormData();
        formData.append('image', file);
        formData.append('page_id', pageId);
        return this.http.post<ImageEntiteUploadResponse>(`${this.apiUrl}/upload-image-entite-page`, formData);
    }

    /**
     * Sauvegarde une entité composite (mode manuel)
     */
    sauvegarderEntiteComposite(body: any): Observable<{ success: boolean }> {
        return this.http.post<{ success: boolean }>(`${this.apiUrl}/sauvegarder-entite-composite`, body);
    }

    /**
     * Compose une entité composite à partir de deux entités simples
     */
    composerEntiteComposite(
        nom: string,
        entiteRecto: string,
        entiteVerso: string,
        description: string,
        appariement: AppariementConfig
    ): Observable<{ success: boolean; message: string }> {
        return this.http.post<{ success: boolean; message: string }>(`${this.apiUrl}/composer-entite-composite`, {
            nom,
            description,
            entite_recto: entiteRecto,
            entite_verso: entiteVerso,
            appariement
        });
    }
}
