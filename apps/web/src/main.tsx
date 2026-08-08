import React from "react";
import { createRoot } from "react-dom/client";

function App() {
  return <main><h1>SparkDeck 007</h1><p>旧生成链路已清理。新的领域协议将从 Phase 1 开始实现。</p></main>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
