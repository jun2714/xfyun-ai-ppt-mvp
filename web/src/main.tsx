import React from "react";
import { createRoot } from "react-dom/client";
import { CreatePage, GenerationPage, OutlinePage } from "./features/create/CreateAndGenerate";
import { Editor } from "./features/editor/Editor";
import "./styles.css";

function App() {
  const outline = location.pathname.match(/^\/presentations\/([^/]+)\/outline$/);
  const generate = location.pathname.match(/^\/presentations\/([^/]+)\/generate$/);
  const edit = location.pathname.match(/^\/presentations\/([^/]+)\/edit$/);
  if (outline?.[1]) return <OutlinePage presentationId={outline[1]} />;
  if (generate?.[1]) return <GenerationPage presentationId={generate[1]} />;
  if (edit?.[1]) return <Editor presentationId={edit[1]} />;
  return <CreatePage />;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
