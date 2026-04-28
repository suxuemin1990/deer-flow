import type { Root } from "hast";

// NOTE: The per-word fade-in splitter has been disabled for performance reasons.
// It walked the entire HAST tree on every streamed token and wrapped every word
// in a <span class="animate-fade-in">, producing O(N^2) work and visible jank
// during long answers. The hook below now returns a stable empty array so all
// existing call sites keep working without changes.

export function rehypeSplitWordsIntoSpans() {
  return (_tree: Root) => {
    // intentionally a no-op
  };
}

const EMPTY_REHYPE_PLUGINS: [] = [];

export function useRehypeSplitWordsIntoSpans(_enabled = true) {
  return EMPTY_REHYPE_PLUGINS;
}
