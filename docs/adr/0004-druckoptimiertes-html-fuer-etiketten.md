# 0004 — Druckoptimiertes HTML statt PDF-Bibliothek für Etiketten

- **Status:** entschieden
- **Datum:** 2026-08-11
- **Meilenstein:** M0

## Kontext

M5 liefert ein Sammel-PDF mit Etikettenbögen (QR-Code + Artikelname im A4-Raster) zur Erstbeklebung
des Haushalts. Zu entscheiden ist der Erzeugungsweg — eine echte PDF-Bibliothek oder eine
druckoptimierte HTML-Ansicht, die über den Browserdialog gedruckt wird.

## Entscheidung

Etikettenbögen entstehen als druckoptimierte HTML-Seite mit `@page`-CSS und einem
Millimeter-Raster, gedruckt über den Browser-Druckdialog. Keine PDF-Bibliothek. Eine
Kalibrierseite mit einer 100-mm-Referenz sichert gegen Skalierungsfehler des Druckertreibers ab.

## Alternativen

- **ReportLab:** Liefert echte, gerätunabhängige PDF-Kontrolle über Maße und Umbruch, ist aber eine
  weitere Abhängigkeit auf einer Zielhardware, die laut `CLAUDE.md` §4 sparsam bei Paketen bleiben
  soll. Als Rückfallposition in M5 vorgemerkt, falls sich der Browserdruck in der Praxis als nicht
  maßhaltig genug herausstellt.

## Konsequenzen

Null zusätzliche Abhängigkeit, sofortige Vorschau im Browser, funktioniert von jedem Gerät im
Heimnetz ohne weitere Software. Das Risiko liegt bei Druckertreiber- und Skalierungsabweichungen
zwischen Geräten, dem die Kalibrierseite (100-mm-Referenz vor dem eigentlichen Druck) begegnet.
Stellt sich in M5 heraus, dass der Browserdruck bei den verfügbaren Geräten nicht zuverlässig
maßhaltig ist, ist ReportLab die vorgemerkte Rückfallposition — diese Entscheidung müsste dann
ersetzt, nicht nur ergänzt werden.
