import { useEffect, useState } from "react";
import ReaderKeys from "./ReaderKeys";
import AuditPanel from "./utilities/AuditPanel";
import AudiobookToolsPanel from "./utilities/AudiobookToolsPanel";
import BackupsPanel from "./utilities/BackupsPanel";
import MetadataPanel from "./utilities/MetadataPanel";
import RecycleBinPanel from "./utilities/RecycleBinPanel";
import SeriesDetectionPanel from "./utilities/SeriesDetectionPanel";
import StorageCleanupPanel from "./utilities/StorageCleanupPanel";

const utilityPages = [
  { key: "audit", label: "Library Audit" },
  { key: "series", label: "Detect Series" },
  { key: "metadata", label: "Sync Online Metadata" },
  { key: "audiobooks", label: "Audiobooks" },
  { key: "recycle-bin", label: "Recycle Bin" },
  { key: "storage", label: "Storage Cleanup" },
  { key: "backups", label: "Backup & Restore" },
  { key: "reader-access", label: "Reader API Keys" },
];

function getRequestedUtilityTab() {
  const requested = new URLSearchParams(window.location.search).get("section");
  return utilityPages.some((tab) => tab.key === requested)
    ? requested
    : "audit";
}

function Utilities({
  onBack,
  section,
  reviewOnly = false,
}: {
  onBack?: () => void;
  section?: string;
  reviewOnly?: boolean;
}) {
  const [activeTab, setActiveTab] = useState(
    () => section || getRequestedUtilityTab(),
  );

  useEffect(() => {
    const onPopState = () => setActiveTab(section || getRequestedUtilityTab());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [section]);

  return (
    <div className={`${onBack ? "book-settings " : ""}utilities-page`}>
      <div className="settings-header">
        {onBack && (
          <button
            className="btn-text"
            onClick={onBack}
            style={{ flexShrink: 0 }}
          >
            ← Back
          </button>
        )}
        <h2>
          {reviewOnly
            ? "Review suggestions"
            : utilityPages.find((page) => page.key === activeTab)?.label}
        </h2>
      </div>

      <div className="sub-tab-content utilities-tab-content">
        {activeTab === "audit" && <AuditPanel />}
        {activeTab === "series" && <SeriesDetectionPanel />}
        {activeTab === "metadata" && <MetadataPanel />}
        {activeTab === "audiobooks" && <AudiobookToolsPanel />}
        {activeTab === "recycle-bin" && <RecycleBinPanel />}
        {activeTab === "storage" && <StorageCleanupPanel />}
        {activeTab === "backups" && <BackupsPanel />}
        {activeTab === "reader-access" && <ReaderKeys showHeading={false} />}
      </div>
    </div>
  );
}

export default Utilities;
