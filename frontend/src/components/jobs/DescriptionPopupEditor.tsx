import { useRef } from "react";
import { useGridCellEditor, type CustomCellEditorProps } from "ag-grid-react";
import type { Job } from "../../types/job";

/** The description column's cell editor: a job description is too long for a
 *  single-line inline box, so editing (however it starts -- double-click,
 *  typing over a selected cell, F2) opens this tooltip-style popup instead
 *  (see cellEditorPopup/cellEditorPopupPosition on the column in
 *  JobsPage.tsx) rather than the grid's default one-line text editor.
 */
export function DescriptionPopupEditor(props: CustomCellEditorProps<Job, string>) {
  const { value, onValueChange } = props;
  const cancelledRef = useRef(false);

  useGridCellEditor({
    isCancelAfterEnd: () => cancelledRef.current,
  });

  const cancel = () => {
    cancelledRef.current = true;
    props.stopEditing();
  };

  const save = () => {
    props.stopEditing();
  };

  return (
    <div
      className="description-popup-editor"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          cancel();
        } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.stopPropagation();
          save();
        } else {
          // Everything else (including plain Enter, which should insert a
          // newline) stays inside the textarea rather than being read by
          // the grid as a navigation or edit-stop key.
          event.stopPropagation();
        }
      }}
    >
      <textarea
        className="description-popup-textarea"
        rows={10}
        autoFocus
        value={value ?? ""}
        onChange={(event) => onValueChange(event.target.value)}
        placeholder="Type a job description…"
      />
      <div className="description-popup-actions">
        <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={cancel}>
          Cancel
        </button>
        <button
          type="button"
          className="primary"
          onMouseDown={(event) => event.preventDefault()}
          onClick={save}
        >
          Save
        </button>
      </div>
    </div>
  );
}
