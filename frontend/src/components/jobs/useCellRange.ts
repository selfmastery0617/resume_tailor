/** Excel-style rectangular cell selection for AG Grid Community.
 *
 *  Range selection is an Enterprise feature, so this reimplements the part that
 *  matters: click a cell, drag, get a rectangle. It works off DOM events on the
 *  grid wrapper rather than grid callbacks, because AG Grid Community does not
 *  raise a cell mouse-down event, and reads `row-index` / `col-id` off the
 *  rendered cells — the same attributes AG Grid uses itself.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { GridApi } from "ag-grid-community";

export interface CellRef {
  rowIndex: number;
  colId: string;
}

export interface CellRange {
  top: number;
  bottom: number;
  /** Column ids in visual order, left to right. */
  columns: string[];
}

interface Options {
  /** Columns that may be selected, in display order. */
  columnIds: string[];
  /** Ignore drags starting here — a click on a button should not select. */
  isInteractive?: (target: HTMLElement) => boolean;
}

function cellFromEvent(event: Event): CellRef | null {
  const target = event.target as HTMLElement | null;
  const cell = target?.closest?.(".ag-cell") as HTMLElement | null;
  if (!cell) return null;
  const colId = cell.getAttribute("col-id");
  const row = cell.closest(".ag-row") as HTMLElement | null;
  const rowIndex = row?.getAttribute("row-index");
  if (!colId || rowIndex === null || rowIndex === undefined) return null;
  return { rowIndex: Number(rowIndex), colId };
}

export function useCellRange(gridRef: React.RefObject<HTMLDivElement | null>, options: Options) {
  const { columnIds, isInteractive } = options;
  const [anchor, setAnchor] = useState<CellRef | null>(null);
  const [focus, setFocus] = useState<CellRef | null>(null);
  const dragging = useRef(false);
  const apiRef = useRef<GridApi | null>(null);

  const setApi = useCallback((api: GridApi | null) => {
    apiRef.current = api;
  }, []);

  const range: CellRange | null =
    anchor && focus
      ? (() => {
          const a = columnIds.indexOf(anchor.colId);
          const b = columnIds.indexOf(focus.colId);
          if (a === -1 || b === -1) return null;
          return {
            top: Math.min(anchor.rowIndex, focus.rowIndex),
            bottom: Math.max(anchor.rowIndex, focus.rowIndex),
            columns: columnIds.slice(Math.min(a, b), Math.max(a, b) + 1),
          };
        })()
      : null;

  const inRange = useCallback(
    (rowIndex: number | null | undefined, colId: string | undefined) => {
      if (!range || rowIndex == null || !colId) return false;
      return (
        rowIndex >= range.top &&
        rowIndex <= range.bottom &&
        range.columns.includes(colId)
      );
    },
    [range],
  );

  const clear = useCallback(() => {
    setAnchor(null);
    setFocus(null);
  }, []);

  const select = useCallback((from: CellRef, to: CellRef = from) => {
    setAnchor(from);
    setFocus(to);
  }, []);

  useEffect(() => {
    const host = gridRef.current;
    if (!host) return;

    const onMouseDown = (event: MouseEvent) => {
      // Left button only; right-click should not redraw the selection.
      if (event.button !== 0) return;
      const target = event.target as HTMLElement;
      if (isInteractive?.(target)) return;
      const cell = cellFromEvent(event);
      // Columns outside the list hold controls, not data — the checkbox and
      // the delete button. They take no part in a range.
      if (!cell || !columnIds.includes(cell.colId)) return;
      dragging.current = true;
      // Shift extends the existing range, matching a spreadsheet.
      if (event.shiftKey && anchor) setFocus(cell);
      else select(cell);
    };

    const onMouseOver = (event: MouseEvent) => {
      if (!dragging.current) return;
      const cell = cellFromEvent(event);
      // Dragging out over a control column holds the range where it was rather
      // than collapsing it, so passing over one on the way back is harmless.
      if (cell && columnIds.includes(cell.colId)) setFocus(cell);
    };

    // On window, not the grid: a drag that ends outside it must still finish.
    const onMouseUp = () => {
      dragging.current = false;
    };

    host.addEventListener("mousedown", onMouseDown);
    host.addEventListener("mouseover", onMouseOver);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      host.removeEventListener("mousedown", onMouseDown);
      host.removeEventListener("mouseover", onMouseOver);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [gridRef, anchor, select, isInteractive, columnIds]);

  // Repaint the highlight. AG Grid owns the cell DOM, so the class has to come
  // from a cellClass callback and be refreshed rather than set directly.
  useEffect(() => {
    apiRef.current?.refreshCells({ force: true });
  }, [range?.top, range?.bottom, range?.columns.join(",")]);

  return { range, anchor, focus, inRange, clear, select, setApi };
}
