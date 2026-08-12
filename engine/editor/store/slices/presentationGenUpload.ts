import { PresentationConfig } from "@/app/(presentation-generator)/upload/type";
import type { TeachingContextState } from "@/app/(presentation-generator)/presentation/components/chat/chat-prompts";
import { createSlice, PayloadAction } from "@reduxjs/toolkit";

interface PresentationGenUploadState {
  config: PresentationConfig | null;
  files: any;
  generationMode: "smart" | "standard";
  requestContent: string | null;
  requestContext: TeachingContextState | null;
}

const initialState: PresentationGenUploadState = {
  config: null,
  files: [],
  generationMode: "standard",
  requestContent: null,
  requestContext: null,
};

export const presentationGenUploadSlice = createSlice({
  name: "pptGenUpload",
  initialState,
  reducers: {
    setPptGenUploadState: (
      state,
      action: PayloadAction<Partial<PresentationGenUploadState>>
    ) => {
      const payload = action.payload;
      if (payload.config !== undefined) {
        state.config = payload.config;
      }
      if (payload.files !== undefined) {
        state.files = payload.files;
      }
      if (payload.generationMode) {
        state.generationMode = payload.generationMode;
      }
      if (payload.requestContent !== undefined) {
        state.requestContent = payload.requestContent;
      }
      if (payload.requestContext !== undefined) {
        state.requestContext = payload.requestContext;
      }
    },
  },
});

export const { setPptGenUploadState } = presentationGenUploadSlice.actions;
export default presentationGenUploadSlice.reducer;
