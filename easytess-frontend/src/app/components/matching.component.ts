// matching.component.ts
import { Component, signal, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { EntityService } from '../services/entity.service';
import { OcrService } from '../services/ocr.service';
import { FileService } from '../services/file.service';
import { AppariementResponse, ResultatOCR } from '../services/models';

@Component({
    selector: 'app-matching',
    standalone: true,
    imports: [CommonModule, FormsModule],
    templateUrl: './matching.component.html',
    styleUrls: ['./matching.component.css']
})
export class MatchingComponent implements OnInit {
    private entityService = inject(EntityService);
    private ocrService = inject(OcrService);
    private fileService = inject(FileService);

    // State
    compositeEntities = signal<any[]>([]);
    selectedEntity = '';
    loading = signal(false);
    rectoFile: File | null = null;
    versoFile: File | null = null;
    rectoPreview = signal('');
    versoPreview = signal('');
    rectoFilename = '';
    versoFilename = '';

    // Results
    result = signal<AppariementResponse | null>(null);

    ngOnInit() {
        this.loadEntities();
    }

    loadEntities() {
        this.entityService.listerEntites().subscribe({
            next: (all) => {
                this.compositeEntities.set(
                    all.filter((e: any) => e.type === 'composite' || e.pages)
                );
            }
        });
    }

    onRectoSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        this.rectoFile = file;
        this.rectoPreview.set(URL.createObjectURL(file));
        this.uploadPage(file, 'recto');
    }

    onVersoSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        this.versoFile = file;
        this.versoPreview.set(URL.createObjectURL(file));
        this.uploadPage(file, 'verso');
    }

    private uploadPage(file: File, pageId: string) {
        this.entityService.uploadImageEntitePage(file, pageId).subscribe({
            next: (res) => {
                if (pageId === 'recto') this.rectoFilename = res.filename;
                else this.versoFilename = res.filename;
            },
            error: (err) => console.error(`Upload ${pageId} error:`, err)
        });
    }

    canAnalyse(): boolean {
        return !!(this.selectedEntity && this.rectoFilename && this.versoFilename);
    }

    analyse() {
        if (!this.canAnalyse()) return;
        this.loading.set(true);
        this.result.set(null);

        this.ocrService.apparierRectoVerso(
            this.selectedEntity,
            this.rectoFilename,
            this.versoFilename
        ).subscribe({
            next: (res) => {
                this.loading.set(false);
                this.result.set(res);
            },
            error: (err) => {
                this.loading.set(false);
                console.error('Matching error:', err);
            }
        });
    }

    getConfidencePercent(): number {
        return Math.round((this.result()?.appariement?.confiance || 0) * 100);
    }

    getMatchLabel(): string {
        const r = this.result()?.appariement;
        if (!r) return '';
        if (r.apparie === true) return '✅ MÊME PIÈCE';
        if (r.apparie === false) return '❌ PIÈCES DIFFÉRENTES';
        return '⚠️ INDÉTERMINÉ';
    }

    getMatchClass(): string {
        const r = this.result()?.appariement;
        if (!r) return '';
        if (r.apparie === true) return 'match';
        if (r.apparie === false) return 'no-match';
        return 'unknown';
    }

    getResultEntries(resultats: { [key: string]: ResultatOCR } | undefined): { key: string; value: string }[] {
        if (!resultats) return [];
        return Object.entries(resultats).map(([key, val]) => ({
            key,
            value: (val as any)?.texte_final || (val as any)?.texte_auto || (typeof val === 'string' ? val : JSON.stringify(val))
        }));
    }
}
