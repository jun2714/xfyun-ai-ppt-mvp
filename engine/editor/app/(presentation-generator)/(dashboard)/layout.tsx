import React from "react";
import DashboardShell from "./Components/DashboardShell";

const layout = ({ children }: { children: React.ReactNode }) => {
  return <DashboardShell>{children}</DashboardShell>;
};

export default layout;
