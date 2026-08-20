import {
  getBridgeSessionToken,
  bootstrapTeachnovaSession,
} from "@/utils/teachnovaSession";

// Capture embed session as early as this module loads in the browser.
if (typeof window !== "undefined") {
  bootstrapTeachnovaSession();
}

export const getHeader = () => {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };
  const token = getBridgeSessionToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
};

export const getHeaderForFormData = () => {
  const headers: Record<string, string> = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };
  const token = getBridgeSessionToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
};
