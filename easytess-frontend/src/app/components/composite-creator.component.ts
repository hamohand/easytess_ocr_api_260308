// composite-creator.component.ts
import { Component, signal, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { EntityService } from '../services/entity.service';
import { Entite, AppariementConfig } from '../services/models';

@Component({
    selector: 'app-composite-creator',
    standalone: true,
    imports: [CommonModule, FormsModule],
    templateUrl: './composite-creator.component.html',
    styleUrls: ['./composite-creator.component.css']
})
export class CompositeCreatorComponent implements OnInit {
    private entityService = inject(EntityService);

    // State
    mode = signal<'compose' | 'manual'>('compose');
    simpleEntities = signal<Entite[]>([]);
    compositeEntities = signal<Entite[]>([]);
    loading = signal(false);
    status = signal('');
    statusType = signal<'info' | 'success' | 'error'>('info');

    // Form
    entityName = '';
    entityDesc = '';
    matchMethod: 'numero_piece' | 'photo' | 'combinee' = 'numero_piece';
    matchField = 'numeroPiece';

    // Compose mode
    selectedRecto = '';
    selectedVerso = '';
    rectoInfo = signal('');
    versoInfo = signal('');

    ngOnInit() {
        this.loadEntities();
    }

    loadEntities() {
        this.entityService.listerEntites().subscribe({
            next: (all) => {
                this.simpleEntities.set(
                    all.filter((e: any) => e.type === 'simple' || (!e.pages && !e.type))
                );
                this.compositeEntities.set(
                    all.filter((e: any) => e.type === 'composite' || e.pages)
                );
            },
            error: (err) => console.error('Erreur chargement entités:', err)
        });
    }

    setMode(m: 'compose' | 'manual') {
        this.mode.set(m);
    }

    onRectoSelected() {
        this.rectoInfo.set(this.getEntityInfo(this.selectedRecto));
    }

    onVersoSelected() {
        this.versoInfo.set(this.getEntityInfo(this.selectedVerso));
    }

    getEntityInfo(name: string): string {
        if (!name) return '';
        const ent = this.simpleEntities().find(e => e.nom === name);
        if (!ent) return '';
        const zones = (ent.zones || []).map(z => z.nom).join(', ');
        return `${(ent.zones || []).length} zones : ${zones}`;
    }

    canSave(): boolean {
        if (!this.entityName.trim()) return false;
        if (this.mode() === 'compose') {
            return !!(this.selectedRecto && this.selectedVerso && this.selectedRecto !== this.selectedVerso);
        }
        return false; // Manual mode would need canvas logic
    }

    save() {
        if (!this.canSave()) return;
        this.loading.set(true);
        this.setStatus('Sauvegarde en cours...', 'info');

        const appariement: AppariementConfig = {
            methode: this.matchMethod,
            champ_commun: this.matchField
        };

        if (this.mode() === 'compose') {
            this.entityService.composerEntiteComposite(
                this.entityName.trim(),
                this.selectedRecto,
                this.selectedVerso,
                this.entityDesc,
                appariement
            ).subscribe({
                next: (res) => {
                    this.loading.set(false);
                    if (res.success) {
                        this.setStatus(res.message || `Entité "${this.entityName}" créée !`, 'success');
                        this.loadEntities();
                        this.resetForm();
                    } else {
                        this.setStatus('Erreur lors de la sauvegarde', 'error');
                    }
                },
                error: (err) => {
                    this.loading.set(false);
                    this.setStatus(`Erreur : ${err.error?.error || err.message}`, 'error');
                }
            });
        }
    }

    deleteComposite(nom: string) {
        if (!confirm(`Supprimer l'entité composite "${nom}" ?`)) return;
        this.entityService.supprimerEntite(nom).subscribe({
            next: () => {
                this.setStatus(`Entité "${nom}" supprimée`, 'success');
                this.loadEntities();
            },
            error: (err) => this.setStatus(`Erreur suppression: ${err.message}`, 'error')
        });
    }

    private setStatus(msg: string, type: 'info' | 'success' | 'error') {
        this.status.set(msg);
        this.statusType.set(type);
    }

    private resetForm() {
        this.entityName = '';
        this.entityDesc = '';
        this.selectedRecto = '';
        this.selectedVerso = '';
        this.rectoInfo.set('');
        this.versoInfo.set('');
    }
}
