import React from "react";
import { createRoot } from "react-dom/client";
import { CreatePage, GeneratePage } from "./features/create/CreateAndGenerate";
import { Editor } from "./features/editor/Editor";
import "./styles.css";
import "./editor-enhancements.css";

function App() {
  const generate = location.pathname.match(/^\/presentations\/([^/]+)\/generate$/);
  const edit = location.pathname.match(/^\/presentations\/([^/]+)\/edit$/);
  if (generate?.[1]) return <GeneratePage presentationId={generate[1]} />;
  if (edit?.[1]) return <Editor presentationId={edit[1]} />;
  return <CreatePage />;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
