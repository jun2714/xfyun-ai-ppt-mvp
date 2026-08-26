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
  };
  const token = getBridgeSessionToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
};

export const getHeaderForFormData = () => {
  const headers: Record<string, string> = {};
  const token = getBridgeSessionToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
};
