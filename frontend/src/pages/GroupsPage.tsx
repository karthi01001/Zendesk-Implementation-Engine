// Superseded by the generic AreaPage in Phase 1 and no longer used. Safe to delete.
import AreaPage from "./AreaPage";

export default function GroupsPage() {
  return (
    <AreaPage areaKey="groups" label="Groups" snapshotId={null} onNavigate={() => undefined} />
  );
}
