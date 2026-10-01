import { DICTS, type Dict } from "../i18n";
import { useEos } from "../store";

/** The dictionary of the language the viewer chose. */
export function useT(): Dict {
  return DICTS[useEos((state) => state.lang)];
}
