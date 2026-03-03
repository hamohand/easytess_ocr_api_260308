// app.component.ts - Composant principal avec 2 sections : EasyTess OCR + Extraction
import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OcrUploadComponent } from './components/ocr-upload.component';
import { EntityCreatorComponent } from './components/entity-creator.component';
import { DocumentExtractorComponent } from './components/document-extractor.component';
import { CompositeCreatorComponent } from './components/composite-creator.component';
import { MatchingComponent } from './components/matching.component';

type Section = 'ocr' | 'extraction';
type OcrTab = 'analyse' | 'entity' | 'composite' | 'appariement';

@Component({
    selector: 'app-root',
    standalone: true,
    imports: [CommonModule, OcrUploadComponent, EntityCreatorComponent, DocumentExtractorComponent, CompositeCreatorComponent, MatchingComponent],
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.css']
})
export class AppComponent {
    title = 'EasyTess';
    activeSection = signal<Section>('ocr');
    activeOcrTab = signal<OcrTab>('analyse');

    setSection(section: Section) {
        this.activeSection.set(section);
    }

    setOcrTab(tab: OcrTab) {
        this.activeOcrTab.set(tab);
    }
}

