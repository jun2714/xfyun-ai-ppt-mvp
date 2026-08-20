"use client";

import { useEffect } from "react";
import { bootstrapTeachnovaSession } from "@/utils/teachnovaSession";

/** Capture TeachNova bridge session before dashboard/API calls. */
export default function TeachnovaSessionBootstrap() {
  useEffect(() => {
    bootstrapTeachnovaSession();
  }, []);
  return null;
}
