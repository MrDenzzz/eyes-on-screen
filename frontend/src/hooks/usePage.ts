import { useEffect, useState } from "react";

export type Page = "live" | "record";

export function pageFromHash(hash: string): Page {
  return hash === "#record" ? "record" : "live";
}

/** The page named by the URL hash, so `/#record` can be bookmarked on a phone. */
export function usePage(): Page {
  const [page, setPage] = useState(() => pageFromHash(window.location.hash));
  useEffect(() => {
    const update = () => setPage(pageFromHash(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return page;
}
