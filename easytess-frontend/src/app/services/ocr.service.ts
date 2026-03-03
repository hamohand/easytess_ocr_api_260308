// ocr.service.ts - Service Angular pour les opérations OCR
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AnalyseResponse, ResultatOCR, CadreReference, BatchAnalyseResponse, AppariementResponse } from './models';

@Injectable({
    providedIn: 'root'
})
export class OcrService {
    private apiUrl = 'http://localhost:8082/api';

    constructor(private http: HttpClient) { }

    /**
     * Analyse une image avec OCR
     * @param filename - Nom du fichier uploadé (retourné par uploadImage)
     * @param zones - (Optionnel) Configuration des zones à analyser
     * @param cadre_reference - (Optionnel) Cadre de référence pour transformation des zones
     */
    analyserImage(filename: string, zones?: any, cadre_reference?: CadreReference): Observable<AnalyseResponse> {
        const body = { filename, zones, cadre_reference };
        return this.http.post<AnalyseResponse>(`${this.apiUrl}/analyser`, body);
    }

    /**
     * Récupère les résultats stockés en session
     */
    getResultats(): Observable<{ [zoneName: string]: ResultatOCR }> {
        return this.http.get<{ [zoneName: string]: ResultatOCR }>(`${this.apiUrl}/resultats`);
    }

    /**
     * Sauvegarde les corrections manuelles
     * @param corrections - Objet avec les corrections { zoneName: texteCorrigé }
     */
    sauvegarderCorrections(corrections: { [key: string]: string }): Observable<{ success: boolean }> {
        return this.http.post<{ success: boolean }>(`${this.apiUrl}/resultats`, corrections);
    }

    /**
     * Récupère les zones nécessitant une correction
     */
    getCorrections(): Observable<{ [zoneName: string]: ResultatOCR }> {
        return this.http.get<{ [zoneName: string]: ResultatOCR }>(`${this.apiUrl}/corrections`);
    }

    /**
     * Analyse un batch de fichiers avec OCR (synchrone)
     */
    analyserBatch(filenames: string[], zones?: any, cadre_reference?: CadreReference): Observable<BatchAnalyseResponse> {
        const body = { filenames, zones, cadre_reference };
        return this.http.post<BatchAnalyseResponse>(`${this.apiUrl}/analyser-batch`, body);
    }

    /**
     * Lance une analyse batch asynchrone (retourne un job_id)
     */
    analyserBatchAsync(filenames: string[], zones?: any, cadre_reference?: CadreReference): Observable<{ success: boolean; job_id: string; total: number }> {
        const body = { filenames, zones, cadre_reference };
        return this.http.post<{ success: boolean; job_id: string; total: number }>(`${this.apiUrl}/analyser-batch-async`, body);
    }

    /**
     * Connecte au SSE pour suivre la progression d'un job batch
     */
    connectBatchProgress(jobId: string): EventSource {
        return new EventSource(`${this.apiUrl}/batch-progress/${jobId}`);
    }

    /**
     * Polling fallback: récupère l'état d'un job batch
     */
    getBatchResult(jobId: string): Observable<any> {
        return this.http.get<any>(`${this.apiUrl}/batch-result/${jobId}`);
    }

    // ─── Matching ───────────────────────────

    /**
     * Appariement recto/verso de deux images
     */
    apparierRectoVerso(entite: string, rectoFilename: string, versoFilename: string): Observable<AppariementResponse> {
        const formData = new FormData();
        formData.append('entite', entite);
        formData.append('recto_filename', rectoFilename);
        formData.append('verso_filename', versoFilename);
        return this.http.post<AppariementResponse>(`${this.apiUrl}/apparier-recto-verso`, formData);
    }
}
