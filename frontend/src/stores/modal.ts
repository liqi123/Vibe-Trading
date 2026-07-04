import { create } from "zustand";

interface ModalState {
  stockCode: string | null;
  open: (code: string) => void;
  close: () => void;
}

export const useModalStore = create<ModalState>((set) => ({
  stockCode: null,
  open: (code) => set({ stockCode: code }),
  close: () => set({ stockCode: null }),
}));
