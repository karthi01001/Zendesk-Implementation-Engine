// Helpers for the configuration areas. The list itself comes from the backend (/api/areas),
// so the menu always matches what the engine can read.

import type { AreaInfo, AreaSummary, SnapshotSummary } from "./api";

export interface AreaSection {
  title: string;
  areas: AreaInfo[];
}

/** Group areas by section, keeping the backend's order. */
export function groupBySection(areas: AreaInfo[]): AreaSection[] {
  const sections: AreaSection[] = [];
  for (const area of areas) {
    let section = sections.find((s) => s.title === area.section);
    if (!section) {
      section = { title: area.section, areas: [] };
      sections.push(section);
    }
    section.areas.push(area);
  }
  return sections;
}

export function summaryFor(snapshot: SnapshotSummary | null, key: string): AreaSummary | undefined {
  return snapshot?.areas.find((area) => area.key === key);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

/** Open an area (or the Tags / History pages), optionally focusing one item. */
export type Navigate = (key: string, options?: { itemId?: string; unusedOnly?: boolean }) => void;

export function previewValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value === "" ? '""' : value;
  return JSON.stringify(value);
}
